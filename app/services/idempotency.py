"""Сценарий «выполнить один раз»: повтор создающего вызова не заводит второй объект.

Один механизм на оба интерфейса: REST передаёт сюда заголовок `Idempotency-Key`
(`app/api/idempotency.py`), MCP — аргумент `idempotency_key` инструмента. Второй
механизм для агентов развёл бы интерфейсы ровно там, где расхождение стоит дороже
всего: агент, повторивший вызов, получил бы дубль в одном интерфейсе и первый ответ в
другом.

## Как устроена защита от одновременных повторов

Всё держится на уникальности пары `(token_id, key)` в базе, а не на проверке в коде.
Порядок такой:

1. быстрый поиск ключа — это **оптимизация**, а не защита: он отвечает на обычный
   случай «повтор пришёл, когда первый вызов давно закончился»;
2. вставка строки ключа **до** самой работы, внутри точки сохранения;
3. работа;
4. запись ответа в ту же строку.

Шаги 2–4 идут в одной транзакции с созданием объекта, поэтому строка ключа и её ответ
становятся видны другим ровно в тот момент, когда становится виден объект. Промежуточное
состояние «ключ занят, ответа ещё нет» снаружи не наблюдается никогда.

Второй одновременный запрос упирается в уникальный индекс на шаге 2 и **ждёт** на нём
конца первой транзакции. Дальше два исхода, и оба верные: первая зафиксировалась —
второй получает нарушение уникальности, перечитывает строку и отдаёт её ответ; первая
откатилась — строки нет, второй вставляется сам и делает работу.

## Почему точка сохранения обязательна

Нарушение уникальности здесь — рабочий исход, а не сбой. Но упавший `flush` без точки
сохранения делает непригодной **всю** транзакцию: перечитать строку в ней уже нельзя.
`session.begin_nested()` ограничивает откат одной вставкой, и после него сессия
продолжает работать.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, UnauthorizedError
from app.core.logging import get_logger
from app.db.models.idempotency import IdempotencyKey
from app.db.repositories import IdempotencyRepository
from app.domain.errors import IdempotencyKeyReusedError
from app.domain.idempotency import KEY_TTL, fingerprint, normalize_idempotency_key
from app.services.auth import Actor

logger = get_logger("services.idempotency")


async def run_once(
    session: AsyncSession,
    *,
    actor: Actor,
    key: str | None,
    operation: str,
    request: Any,
    build: Callable[[], Awaitable[Any]],
    status_code: int | None = None,
) -> Any:
    """Выполняет `build` один раз на ключ и отдаёт его результат — хоть первому, хоть повтору.

    `key` пуст — механизм не участвует вовсе: `build` зовётся, ничего не хранится. Так
    выглядит обычный вызов без заголовка, и отдельной ветки у вызывающего для этого нет.

    `operation` — имя вызова (`operation_id` маршрута или имя инструмента MCP), `request`
    — его запрос в виде, пригодном для JSON. Вместе они дают отпечаток: тот же ключ с
    другим отпечатком — это `409 idempotency_key_reused`, а не второй объект и не тихая
    подмена ответа.

    Результат `build` обязан быть JSON-значением: он ложится в базу как есть и оттуда же
    достаётся повтору. Собирать ответ заново при повторе нельзя — у выпуска токена в
    ответе секрет, которого во второй раз взять неоткуда.

    Требование к вызывающему одно, и оно невыразимо сигнатурой: `build` не должен сам
    фиксировать транзакцию. Промежуточный коммит опубликовал бы занятый ключ с пустым
    ответом, и одновременный повтор получил бы строку, отвечать по которой нечем.
    """
    if key is None:
        return await build()

    token_id = _token_of(actor)
    value = normalize_idempotency_key(key)
    print_of_request = fingerprint(operation, request)
    repository = IdempotencyRepository(session)
    now = datetime.now(UTC)

    known = await repository.find(token_id=token_id, key=value)
    if known is not None and not _is_expired(known, now):
        return _replay(known, expected=print_of_request, operation=operation)

    # Чужие изменения фиксируются до точки сохранения: откат к ней снял бы и их. В этой
    # же транзакции успела отметиться аутентификация (`tokens.last_used_at`), и терять
    # её отметку из-за занятого ключа незачем.
    await session.flush()

    record = IdempotencyKey(
        token_id=token_id,
        key=value,
        operation=operation,
        fingerprint=print_of_request,
        status_code=status_code,
    )
    try:
        async with session.begin_nested():
            # Уборка идёт попутно, вместе с записью нового ключа: фоновых процессов в
            # трекере нет. Внутри точки сохранения, потому что при занятом ключе
            # откатывается всё вместе — и уборка не пропадёт, её сделает следующая запись.
            await repository.delete_expired(before=now - KEY_TTL)
            await repository.add(record)
    except IntegrityError:
        # Ключ занят другой транзакцией, и она уже зафиксировалась — иначе вставка ждала
        # бы на индексе, а не падала. Поэтому строка с ответом здесь есть наверняка.
        taken = await repository.find(token_id=token_id, key=value)
        if taken is None:
            raise AppError(
                f"Idempotency key {value!r} conflicted but disappeared: the unique "
                "constraint on (token_id, key) is the only thing that can reject this "
                "insert, so the row must exist"
            ) from None
        return _replay(taken, expected=print_of_request, operation=operation)

    result = await build()
    record.response = result
    await session.flush()
    return result


def _token_of(actor: Actor) -> uuid.UUID:
    """Токен, в паре с которым живёт ключ.

    Действия самого трекера (первичная инициализация, служебные записи) токеном не
    подписаны, и пары «токен + ключ» у них нет. Снаружи такой вызов невозможен —
    аутентификация без токена не проходит, — но молча выбросить ключ нельзя: клиент
    считал бы вызов защищённым от повтора, не будучи защищённым.
    """
    if actor.token_id is None:
        raise UnauthorizedError(
            message="Idempotency key requires a token: keys live paired with one",
            details={"reason": "idempotency_requires_token"},
        )
    return actor.token_id


def _is_expired(record: IdempotencyKey, now: datetime) -> bool:
    """Пережил ли ключ свой срок.

    Сравнение по времени приложения, а не базы: разница между часами двух процессов —
    секунды, а срок ключа — сутки, и на исход это не влияет. Устаревший ключ не
    отвечает повтором и не мешает: следующая запись снимет его вместе с остальными.
    """
    return now - record.created_at >= KEY_TTL


def _replay(record: IdempotencyKey, *, expected: str, operation: str) -> Any:
    """Ответ, сохранённый первым вызовом, — или отказ, если запрос был другим."""
    if record.fingerprint != expected:
        raise IdempotencyKeyReusedError(
            details={
                "idempotency_key": record.key,
                "first_operation": record.operation,
                "operation": operation,
                "ttl_seconds": int(KEY_TTL.total_seconds()),
            }
        )
    if record.response is None:
        # Недостижимо: строка и её ответ фиксируются одной транзакцией. Достижимым это
        # станет, если сценарий внутри `build` начнёт коммитить сам, — и тогда молчание
        # было бы худшим из исходов: повтор получил бы пустой ответ вместо созданного.
        raise AppError(
            f"Idempotency key {record.key!r} has no stored response: the call that took "
            "the key committed before finishing"
        )
    logger.info("Replaying %s under an idempotency key", record.operation)
    return record.response
