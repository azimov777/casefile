"""Первичная инициализация установки.

Свежая база заперта снаружи: каждый маршрут `/api/v1` требует токена, а выпустить
первый токен через API нельзя — для этого уже нужен токен. Разомкнуть круг может только
код, работающий с базой напрямую, поэтому сценарий живёт здесь, а команда
`python -m app.cli init` — тонкая обёртка над ним (и её же зовёт сервис `init` в Compose).

Автор всего заведённого — сам трекер (`TRACKER_ACTOR`): участника, который завёл бы
первого участника, в этот момент ещё не существует.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import TokenRepository
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope
from app.services.auth import TRACKER_ACTOR
from app.services.participants import register_participant
from app.services.tokens import IssuedToken, issue_token

DEFAULT_OWNER_NAME = "owner"
DEFAULT_OWNER_DESCRIPTION = "Владелец установки"
DEFAULT_TOKEN_NAME = "bootstrap"


async def initialize_installation(
    session: AsyncSession,
    *,
    name: str = DEFAULT_OWNER_NAME,
    description: str = DEFAULT_OWNER_DESCRIPTION,
    token_name: str = DEFAULT_TOKEN_NAME,
) -> IssuedToken | None:
    """Заводит участника-человека и выпускает ему токен набора `main`.

    `None` означает «установка уже инициализирована»: в базе есть хотя бы один токен, и
    сценарий не делает ничего. Признак — именно токен, а не участник: участник без
    токена доступа не даёт, и на такой базе установка осталась бы запертой.

    Почему повтор не выпускает новый токен, хотя это было бы удобно: команда идёт в
    Compose рядом с миграциями, и её случайный повторный запуск на работающей установке
    не должен плодить действующие доступы. Способ вернуть себе доступ, потеряв секрет,
    есть отдельный и явный — `python -m app.cli issue-token`.
    """
    if await TokenRepository(session).any_exists():
        return None

    owner = await register_participant(
        session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.HUMAN,
        name=name,
        description=description,
    )
    return await issue_token(
        session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name=token_name,
    )
