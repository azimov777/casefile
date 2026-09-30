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
    PARTICIPANT_NAME_MAX,
    ParticipantKind,
    normalize_participant_name,
    validate_participant_name,
)
from app.services.auth import Actor


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
    return await get_participant(session, name)


async def list_participants(
    session: AsyncSession,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Participant]:
    """Реестр участников: кого можно адресовать вопросом и чьё имя может стоять подписью."""
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


#: Префикс имени агента по клиенту (TRK-475#14); прочие клиенты получают `agent`.
_CLIENT_PREFIXES = {"claude": "claude", "codex": "codex"}
_DEFAULT_PREFIX = "agent"


def agent_name_prefix(client: str) -> str:
    """Префикс имени агента: `claude`, `codex` или `agent` для прочих клиентов."""
    return _CLIENT_PREFIXES.get(client.strip().lower(), _DEFAULT_PREFIX)


async def agent_of(session: AsyncSession, *, client: str, owner: Participant) -> Participant:
    """Находит агента человека для клиента или заводит его: `<клиент>_<человек>`.

    Имя агента — префикс клиента, `_` и имя человека (дефис шаблон имени не пропускает).
    Длиннее предела или занято чужим (нет хозяина или хозяин другой) — суффикс `_2`,
    `_3`…; имя, уже принадлежащее этому человеку, возвращается как есть. Повторный вызов
    отдаёт того же участника.
    """
    if owner.kind is not ParticipantKind.HUMAN:
        raise ValueError("The owner of an agent must be a human participant")
    repository = ParticipantRepository(session)
    base = f"{agent_name_prefix(client)}_{owner.name}"[:PARTICIPANT_NAME_MAX]
    attempt = 1
    while True:
        name = base if attempt == 1 else _suffixed(base, attempt)
        existing = await repository.get_by_name(name)
        if existing is None:
            return await repository.add(
                Participant(
                    kind=ParticipantKind.AGENT,
                    name=name,
                    owner=owner,
                    **created_by_columns(owner.author),
                )
            )
        if existing.kind is ParticipantKind.AGENT and existing.owner_id == owner.id:
            return existing
        attempt += 1


def _suffixed(base: str, attempt: int) -> str:
    suffix = f"_{attempt}"
    return base[: PARTICIPANT_NAME_MAX - len(suffix)] + suffix


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

    if description is not None:
        participant.description = description.strip()
    await session.flush()
    return participant
