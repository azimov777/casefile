"""Первичная инициализация: свежая установка размыкается, работающая — не трогается.

Сценарий проверяется здесь, а печать команды — живым прогоном в Docker: смысл проверки в
том, что именно делает `init` с базой, а не в том, как он это печатает.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.authors import AuthorKind
from app.domain.participants import ParticipantKind
from app.domain.tokens import TokenScope
from app.services import participants as participants_service
from app.services.auth import authenticate
from app.services.setup import initialize_installation


async def test_an_empty_installation_gets_an_owner_and_a_working_main_token(
    db_session: AsyncSession,
) -> None:
    """Обзорная проверка 6, первая половина: токен выпущен и им можно ходить."""
    issued = await initialize_installation(db_session)

    assert issued is not None
    assert issued.token.scope is TokenScope.MAIN
    assert issued.token.participant is not None
    assert issued.token.participant.kind is ParticipantKind.HUMAN
    # Заводит трекер: другого автора на пустой установке не существует.
    assert issued.token.created_by.kind is AuthorKind.TRACKER

    actor = await authenticate(db_session, issued.secret)
    assert actor.scope is TokenScope.MAIN
    assert actor.author.signature == issued.token.participant.name


async def test_a_second_run_creates_nothing(db_session: AsyncSession) -> None:
    """Обзорная проверка 6, вторая половина: признак — наличие токена, а не участника.

    Возврат `None` — это и есть «ничего не создано»: команда по нему печатает, что
    установка уже инициализирована, вместо того чтобы плодить действующие доступы.
    """
    first = await initialize_installation(db_session)
    assert first is not None

    second = await initialize_installation(db_session)

    assert second is None
    page = await participants_service.list_participants(
        db_session,
        actor=await authenticate(db_session, first.secret),
    )
    assert [participant.name for participant in page.items] == ["owner"]


async def test_a_participant_without_a_token_does_not_count_as_initialized(
    db_session: AsyncSession,
    owner: object,
) -> None:
    """Участник без токена доступа не даёт — такая установка осталась бы запертой."""
    issued = await initialize_installation(db_session, name="root")

    assert issued is not None
    assert issued.token.participant is not None
    assert issued.token.participant.name == "root"
