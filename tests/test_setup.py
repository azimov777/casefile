"""Первичная инициализация: свежая установка размыкается, работающая — не трогается.

Сценарий проверяется здесь, а печать команды — `tests/test_init_command.py`: смысл
проверки в том, что именно делает `init` с базой. Токена он не выпускает (TRK-472):
человек входит в интерфейс.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import AccountRepository, ParticipantRepository, TokenRepository
from app.domain.participants import ParticipantKind
from app.services.auth import TRACKER_ACTOR
from app.services.participants import register_participant
from app.services.setup import initialize_installation


async def test_an_empty_installation_gets_an_owner_and_an_administrator_without_a_token(
    db_session: AsyncSession,
) -> None:
    """Владелец и его учётная запись заведены, строк `tokens` нет."""
    account = await initialize_installation(db_session)

    assert account is not None
    assert account.participant.kind is ParticipantKind.HUMAN
    assert account.participant.name == "owner"
    assert account.is_admin
    assert not await TokenRepository(db_session).any_exists()


async def test_a_second_run_creates_nothing(db_session: AsyncSession) -> None:
    """Признак «уже сделано» — человек с учётной записью: `None` и ничего нового."""
    first = await initialize_installation(db_session)
    assert first is not None

    second = await initialize_installation(db_session)

    assert second is None
    participants = await ParticipantRepository(db_session).list_page()
    assert [participant.name for participant in participants.items] == ["owner"]


async def test_a_participant_without_an_account_does_not_count_as_initialized(
    db_session: AsyncSession,
) -> None:
    """Участник без учётной записи входа не даёт: `init` заводит её ему."""
    await register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.HUMAN, name="root"
    )

    account = await initialize_installation(db_session, name="root")

    assert account is not None
    assert account.participant.name == "root"
    assert await AccountRepository(db_session).any_human_account()
