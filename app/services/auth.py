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

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.repositories import AccountRepository, TokenRepository
from app.domain.authors import TRACKER, Author, AuthorKind, label_author
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

    `token_id` пуст только у самого трекера: любой запрос снаружи приходит с токеном.
    Нужен он одному механизму — ключам идемпотентности, которые живут в паре с токеном
    (`CONCEPT.md`, 4.5), поэтому здесь лежит идентификатор, а не сама строка токена:
    больше о токене сценариям знать нечего, а лишняя ссылка на ORM-объект пережила бы
    свою сессию.
    """

    author: Author
    scope: TokenScope
    participant: Participant | None = None
    token_id: uuid.UUID | None = None


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
    if token.expired_at(moment):
        # Срок бывает только у токена сеанса браузера (`app/services/login.py`): вышел
        # срок — вышел и сеанс, и вкладке пора войти заново, а не перевыпускать ключ.
        raise UnauthorizedError(
            message="Token has expired",
            details={"reason": "token_expired"},
        )

    if await _person_disabled(session, token):
        # Отключение отзывает токены человека (`app/services/accounts.py`), но не мешает
        # выпустить ему новый — командой на сервере, администратором, подъёмом
        # `local-token`. Такой ключ не пускает, пока человека не включат (`TRK-114#13`).
        raise UnauthorizedError(
            message="The account behind this token is disabled",
            details={"reason": "account_disabled"},
        )

    actor = Actor(
        author=_author(token, label),
        scope=token.scope,
        participant=token.participant,
        token_id=token.id,
    )
    _touch(token, moment)
    return actor


async def _person_disabled(session: AsyncSession, token: Token) -> bool:
    """Отключена ли учётная запись человека этого токена: того, от чьего имени он говорит,
    или того, кто его выпустил.

    Токен, за которым человека нет вовсе (агент, выпущенный трекером), базу не трогает:
    эту цену платит только токен, связанный с человеком.
    """
    participant_ids = (
        {token.participant.id}
        if token.participant is not None and token.participant.author.kind is AuthorKind.HUMAN
        else set()
    )
    issuer = token.created_by
    names = {issuer.signature} if issuer.kind is AuthorKind.HUMAN and issuer.signature else set()
    return await AccountRepository(session).any_disabled(
        participant_ids=participant_ids, names=names
    )


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
