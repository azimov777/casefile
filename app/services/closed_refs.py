"""Закрытый агенту проект в чужих записях: его ключ не называется (TRK-753).

`app/db/project_scope.py` убирает закрытый проект из выборок и отказывает по адресу. Остаётся
то, что называет проект изнутри открытого дела: запись `link_added`/`moved`/`attached` в
описи и теле, адрес обсуждения в отказе, ключ блокера. Здесь одно место, которое их
заменяет меткой `CLOSED_PROJECT_LABEL`: связь остаётся фактом, её сторона — нет.
Вызов без ограничений ничего не меняет.
"""

import dataclasses
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.project_scope import access_of, open_to
from app.domain.case import (
    AttachmentFacts,
    EntryHeading,
    EntryType,
    LinkFacts,
    MovedFacts,
    ResolutionFacts,
)
from app.domain.project_access import (
    CLOSED_PROJECT_LABEL,
    UNRESTRICTED,
    ProjectAccess,
    mask_closed_keys,
)

#: Записи, которые трекер собирает сам и в которых названа другая сторона: связь, перенос,
#: привязка к обсуждению, продолжение работы по замечанию.
NAMING_TYPES = frozenset(
    {
        EntryType.LINK_ADDED,
        EntryType.LINK_REMOVED,
        EntryType.MOVED,
        EntryType.ATTACHED,
        EntryType.DETACHED,
        EntryType.RESOLUTION,
    }
)


async def closed_keys(session: AsyncSession, access: ProjectAccess | None = None) -> frozenset[str]:
    """Ключи проектов, закрытых этому доступу; доступ по умолчанию - с сессии вызова."""
    found = access_of(session) if access is None else access
    if found == UNRESTRICTED:
        return frozenset()
    rows = await session.scalars(select(Project.key).where(~open_to(found, Project.id)))
    return frozenset(rows)


def _mask(value: str | None, keys: frozenset[str]) -> str | None:
    return None if value is None else mask_closed_keys(value, keys)


def _mask_payload(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, str):
        return mask_closed_keys(value, keys)
    if isinstance(value, dict):
        return {key: _mask_payload(item, keys) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_payload(item, keys) for item in value]
    return value


async def mask_headings(
    session: AsyncSession, headings: list[EntryHeading], access: ProjectAccess | None = None
) -> list[EntryHeading]:
    """Опись без ключей закрытых проектов в заголовках и фактах записей из `NAMING_TYPES`."""
    keys = await closed_keys(session, access)
    if not keys:
        return headings
    return [_mask_heading(item, keys) if item.type in NAMING_TYPES else item for item in headings]


def _mask_heading(item: EntryHeading, keys: frozenset[str]) -> EntryHeading:
    facts = item.facts
    if isinstance(facts, LinkFacts):
        facts = dataclasses.replace(
            facts, other_key=_mask(facts.other_key, keys), other_area=_mask(facts.other_area, keys)
        )
    elif isinstance(facts, MovedFacts):
        facts = dataclasses.replace(
            facts, from_key=_mask(facts.from_key, keys), to_key=_mask(facts.to_key, keys)
        )
    elif isinstance(facts, AttachmentFacts):
        facts = dataclasses.replace(
            facts, task_key=_mask(facts.task_key, keys), discussion=_mask(facts.discussion, keys)
        )
    elif isinstance(facts, ResolutionFacts):
        facts = dataclasses.replace(facts, continuation_key=_mask(facts.continuation_key, keys))
    return dataclasses.replace(item, title=mask_closed_keys(item.title, keys), facts=facts)


async def mask_entries(
    session: AsyncSession, entries: Sequence[Entry], access: ProjectAccess | None = None
) -> None:
    """Те же записи без ключей закрытых проектов в заголовке и нагрузке - только для ответа.

    Запись отделяется от сессии (`expunge`), и правка остаётся на её копии в памяти: в базу
    она не уйдёт ни сбросом, ни коммитом. Вызывать надо после всего, что читает записи
    из сессии (подъёмы черновиков и тому подобное).
    """
    keys = await closed_keys(session, access)
    if not keys:
        return
    for entry in entries:
        if entry.type not in NAMING_TYPES:
            continue
        title, payload = mask_closed_keys(entry.title, keys), _mask_payload(entry.payload, keys)
        session.expunge(entry)
        entry.title, entry.payload = title, payload


def mask_addresses(addresses: Iterable[str], keys: frozenset[str]) -> list[str]:
    """Адреса и ключи списка: названное закрытым проектом заменяется меткой, число сохраняется."""
    return [
        CLOSED_PROJECT_LABEL if mask_closed_keys(item, keys) != item else item for item in addresses
    ]


async def mask_discussion_questions(
    session: AsyncSession,
    pairs: Sequence[tuple[Entry, str]],
    access: ProjectAccess | None = None,
) -> list[tuple[Entry, str]]:
    """Вопросы привязанных обсуждений: вопрос закрытого проекта остаётся (он держит задачу),
    а его заголовок и адрес обсуждения - метка. Копия записи отделена от сессии."""
    keys = await closed_keys(session, access)
    masked: list[tuple[Entry, str]] = []
    for entry, address in pairs:
        if mask_closed_keys(address, keys) == address:
            masked.append((entry, address))
            continue
        session.expunge(entry)
        entry.title = CLOSED_PROJECT_LABEL
        masked.append((entry, CLOSED_PROJECT_LABEL))
    return masked
