"""Аутентификация по токену — один механизм на все интерфейсы.

Здесь нет ничего про HTTP: функция принимает строку секрета и возвращает актора.
Поэтому REST-зависимость (`app/api/deps.py`), MCP-сервер (задача 16) и командная
строка пользуются одним и тем же кодом. Две параллельные схемы аутентификации —
для фронтенда и для агентов — соглашениями прямо запрещены: расходятся они мгновенно,
а замечают это, когда агент перестаёт видеть половину задач.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.actor import Actor
from app.db.models.api_token import ApiToken
from app.db.repositories import ApiTokenRepository
from app.domain.tokens import hash_token

#: Как часто обновляется отметка последнего использования токена.
#: Писать её на каждый запрос значило бы превратить любое чтение в запись строки:
#: минутной точности для ответа на вопрос «этим токеном ещё пользуются?» достаточно.
LAST_USED_THROTTLE = timedelta(minutes=1)


async def authenticate_by_token(
    session: AsyncSession,
    raw_token: str,
    *,
    now: datetime | None = None,
) -> Actor:
    """Находит актора по секрету токена.

    Любая неудача — один и тот же код `unauthorized`: так требуют соглашения. Причина
    уезжает в `details.reason`, и по ней клиент понимает, что делать — добавить
    заголовок, перевыпустить токен или включить актора обратно.
    """
    moment = now or datetime.now(UTC)
    secret = raw_token.strip()
    if not secret:
        raise UnauthorizedError(details={"reason": "missing_token"})

    token = await ApiTokenRepository(session).get_by_hash(hash_token(secret))
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
    if not token.actor.is_active:
        raise UnauthorizedError(
            message="Actor is inactive",
            details={"reason": "actor_inactive"},
        )

    _touch(token, moment)
    return token.actor


def _touch(token: ApiToken, moment: datetime) -> None:
    """Отмечает использование токена, если с прошлой отметки прошло достаточно времени."""
    previous = token.last_used_at
    if previous is None or moment - previous >= LAST_USED_THROTTLE:
        token.last_used_at = moment
