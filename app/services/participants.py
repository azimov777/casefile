"""Сценарии по участникам.

Один сценарий — одна функция, вызываемая и из REST, и из MCP, и из командной строки.
Транзакцию функции не фиксируют: коммитит вход в приложение (`get_session` для запроса,
`session_scope` для MCP и команды). `flush` внутри есть — он нужен, чтобы объект получил
идентификатор и значения по умолчанию до конца транзакции.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.participant import Participant
from app.db.pagination import Page
from app.db.repositories import ParticipantRepository
from app.domain.errors import ParticipantNameTakenError, ParticipantNotFoundError
from app.domain.participants import (
    ParticipantKind,
    normalize_participant_name,
    validate_participant_name,
)
from app.domain.tokens import TokenScope
from app.services.auth import Actor
from app.services.permissions import ensure_scope


async def get_participant(session: AsyncSession, name: str) -> Participant:
    """Участник по имени или `participant_not_found`.

    Адресация мягкая: `Alice` находит `alice`. Отдельно от `read_participant` — этот
    вызывается из других сценариев и прав не проверяет.
    """
    participant = await ParticipantRepository(session).get_by_name(normalize_participant_name(name))
    if participant is None:
        raise ParticipantNotFoundError(details={"name": name})
    return participant


async def read_participant(session: AsyncSession, name: str, *, actor: Actor) -> Participant:
    """Карточка участника: точка входа интерфейса, поэтому проверяет права."""
    ensure_scope(actor, TokenScope.TASK, action="participant.read")
    return await get_participant(session, name)


async def list_participants(
    session: AsyncSession,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Participant]:
    """Реестр участников: кого можно адресовать вопросом и чьё имя может стоять подписью."""
    ensure_scope(actor, TokenScope.TASK, action="participant.list")
    return await ParticipantRepository(session).list_page(limit=limit, cursor=cursor)


async def register_participant(
    session: AsyncSession,
    *,
    actor: Actor,
    kind: ParticipantKind,
    name: str,
    description: str = "",
) -> Participant:
    """Заводит человека или постоянного агента.

    Занятость имени проверяется до вставки, а не ловится нарушением ограничения: клиенту
    нужен `participant_name_taken` с именем в подробностях, а не общий `conflict` с
    именем ограничения. Ограничение при этом остаётся — оно страхует от гонки двух
    параллельных регистраций.
    """
    ensure_scope(actor, TokenScope.MAIN, action="participant.register")

    canonical = validate_participant_name(name)
    repository = ParticipantRepository(session)
    if await repository.get_by_name(canonical) is not None:
        raise ParticipantNameTakenError(details={"name": canonical})

    return await repository.add(
        Participant(
            kind=kind,
            name=canonical,
            description=description.strip(),
            **created_by_columns(actor.author),
        )
    )


async def update_participant(
    session: AsyncSession,
    participant: Participant,
    *,
    actor: Actor,
    description: str | None = None,
) -> Participant:
    """Меняет описание. Имя и род неизменяемы.

    Имя стоит подписью в уже подшитых записях дела, а род объясняет читателю, кто
    говорит: переименование и смена рода задним числом переписали бы историю, которую
    дело обязано хранить неизменной.

    `None` означает «поле не передано»: у описания нет осмысленного значения `null`,
    поэтому схема `ParticipantUpdate` отвергает явный `null` сама.
    """
    ensure_scope(actor, TokenScope.MAIN, action="participant.update")

    if description is not None:
        participant.description = description.strip()
    await session.flush()
    return participant
