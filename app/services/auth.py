"""Аутентификация по токену — один механизм на все интерфейсы.

Здесь нет ничего про HTTP: функция принимает строку секрета и метку и возвращает
структуру автора с набором. Поэтому REST-зависимость (`app/api/deps.py`), MCP-сервер
(`app/mcp/runtime.py`) и командная строка пользуются одним и тем же кодом. Две
параллельные схемы аутентификации — для фронтенда и для агентов — соглашениями прямо
запрещены: расходятся они мгновенно, а замечают это, когда агент перестаёт видеть
половину задач.

## Кого возвращает аутентификация

Не участника, а `Actor`: автора действия плюс набор его токена. Разница существенная —
у общего агентского токена участника нет вовсе, и функция, возвращающая участника,
такому запросу могла бы ответить только `None`, то есть переложить разбор двух случаев
на каждого вызывающего.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.repositories import TokenRepository
from app.domain.authors import TRACKER, Author, label_author
from app.domain.errors import ActorLabelRequiredError
from app.domain.tokens import TokenScope, hash_token

#: Как часто обновляется отметка последнего использования токена.
#: Писать её на каждый запрос значило бы превратить любое чтение в запись строки:
#: минутной точности для ответа на вопрос «этим токеном ещё пользуются?» достаточно.
LAST_USED_THROTTLE = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class Actor:
    """Кто делает запрос: автор действия, набор его токена и участник, если он есть.

    Ровно эта структура уезжает в сценарии, и другого способа узнать «кто зовёт» у них
    нет. Неизменяемая: подменить автора или набор посреди сценария нельзя даже случайно.

    `participant` пуст у временного агента и у самого трекера. Спрашивать его стоит
    только там, где нужна именно строка реестра (адресовать вопрос можно лишь
    участнику); для подписи есть `author.signature`, и он заполнен всегда, кроме
    служебных действий трекера.
    """

    author: Author
    scope: TokenScope
    participant: Participant | None = None


#: Автор служебных действий: команда первичной инициализации и служебные записи дела.
#: Набор `main`, потому что трекеру доступно всё, что доступно установке; токена за ним
#: нет и быть не может — иначе им можно было бы выдать себя за сам трекер.
TRACKER_ACTOR = Actor(author=TRACKER, scope=TokenScope.MAIN)


async def authenticate(
    session: AsyncSession,
    raw_token: str,
    *,
    label: str | None = None,
    now: datetime | None = None,
) -> Actor:
    """Находит автора запроса по секрету токена и, если нужно, по его метке.

    Любая неудача аутентификации — семейство `unauthorized`: так требуют соглашения.
    Причина уезжает в `details.reason`, и по ней клиент понимает, что делать — добавить
    заголовок, перевыпустить токен или взять другой.
    """
    moment = now or datetime.now(UTC)
    secret = raw_token.strip()
    if not secret:
        raise UnauthorizedError(details={"reason": "missing_token"})

    token = await TokenRepository(session).get_by_hash(hash_token(secret))
    if token is None:
        raise UnauthorizedError(
            message="Token is unknown or revoked",
            details={"reason": "unknown_token"},
        )
    if token.is_revoked:
        # Сообщение то же, что и для неизвестного токена: отвечать «токен существует,
        # но отозван» — значит подтверждать чужую догадку о валидном секрете.
        raise UnauthorizedError(
            message="Token is unknown or revoked",
            details={"reason": "token_revoked"},
        )

    actor = Actor(author=_author(token, label), scope=token.scope, participant=token.participant)
    _touch(token, moment)
    return actor


def _author(token: Token, label: str | None) -> Author:
    """Подпись запроса: имя участника или метка временного агента.

    У именного токена метка **игнорируется молча**, и это решение, а не недосмотр.
    Отказ выглядел бы строже, но заставлял бы клиента, который шлёт метку всегда (так
    проще настроить харнесс), держать две конфигурации. Подделать подпись это не
    позволяет: у именного токена подпись всегда его собственная.
    """
    if token.participant is not None:
        return token.participant.author
    if not label:
        raise ActorLabelRequiredError(details={"reason": "missing_actor_label"})
    return label_author(label)


def _touch(token: Token, moment: datetime) -> None:
    """Отмечает использование токена, если с прошлой отметки прошло достаточно времени."""
    previous = token.last_used_at
    if previous is None or moment - previous >= LAST_USED_THROTTLE:
        token.last_used_at = moment
