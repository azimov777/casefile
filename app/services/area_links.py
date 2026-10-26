"""Сценарии по связям областей `see_also`: поставить, снять, прочитать.

Связь области с областью — отдельная сущность рядом со связями задач, а не их частный
случай: у неё один вид, направление и причина (`app/domain/area_links.py`). Модуль
повторяет устройство `app/services/links.py` там, где правило то же, и расходится там, где
у областей иное.

## Поставить и снять — не одно и то же для архива

Постановка идёт под очередью изменений с проверкой заморозки **обеих** областей
(`freeze.ensure_unfrozen` под `lock_changes`): архивная область — `area_archived`, область
архивного проекта — `project_archived`, проект называется первым. Снятие очередь занимает
без проверки заморозки: связь с архивной областью и с областью архивного проекта снимается, не
восстанавливая её, и `link_removed` — единственная запись, которую архив пропускает
(`freeze.UNFROZEN_ENTRY_TYPES`; для задач — TRK#98, TRK#101).

## Две записи в дело на одну связь

Событие обеих областей, поэтому запись подшивается в оба дела, в порядке адреса области, а
не порядка аргументов: `allocate_area_no` держит строку области до конца транзакции, и два
встречных запроса взаимно заблокировались бы (`TRK/links#5`). Обе записи делят один
`action_id`.

Автоматики нет: архив области связей не снимает и не прячет.

Сценарии не коммитят (TRK/db#4); повтор по ключу идемпотентности поставит обёртка `Once` на
границе MCP (TRK#171).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.area import Area
from app.db.models.area_link import AreaLink
from app.db.models.author import created_by_columns
from app.db.project_scope import access_of
from app.db.repositories import AreaLinkRepository
from app.domain.area_links import (
    AreaLinkKind,
    ensure_not_self,
    validate_area_link_reason,
)
from app.domain.errors import AreaLinkExistsError, AreaLinkNotFoundError
from app.domain.project_access import is_open
from app.services import case as case_service
from app.services import freeze
from app.services.auth import Actor

# --- Чтение -----------------------------------------------------------------------------


async def list_see_also(session: AsyncSession, area: Area) -> list[AreaLink]:
    """Исходящие связи области (`see_also`), по адресу цели.

    Связь с областью закрытого агенту проекта не показывается (TRK~28#6).
    """
    access = access_of(session)
    links = await AreaLinkRepository(session).list_outgoing(area.id)
    return [link for link in links if is_open(access, link.target.project_id)]


async def list_see_also_from(session: AsyncSession, area: Area) -> list[AreaLink]:
    """Входящие связи области (`see_also_from`), по адресу источника.

    Связь с областью закрытого агенту проекта не показывается (TRK~28#6).
    """
    access = access_of(session)
    links = await AreaLinkRepository(session).list_incoming(area.id)
    return [link for link in links if is_open(access, link.source.project_id)]


# --- Изменение --------------------------------------------------------------------------


async def add_area_link(
    session: AsyncSession,
    source: Area,
    target: Area,
    *,
    actor: Actor,
    reason: str | None,
) -> AreaLink:
    """Ставит связь `source → target` (`see_also`) и подшивает `link_added` в оба дела.

    Порядок проверок задан правилом связи: очередь и заморозка обеих областей первыми
    (архив называется раньше всего остального: агент, получивший отказ о причине в архивной
    области, чинил бы не то), затем причина, «не с собой» и повтор.
    """
    await lock_changes(session)
    await freeze.ensure_unfrozen(session, areas=(source, target))
    checked = validate_area_link_reason(reason)
    ensure_not_self(source.address, target.address)

    repository = AreaLinkRepository(session)
    if await repository.find(source_id=source.id, target_id=target.id) is not None:
        raise AreaLinkExistsError(details=_sides(source, target))
    link = await repository.add(
        AreaLink(
            source=source,
            target=target,
            reason=checked,
            **created_by_columns(actor.author),
        )
    )
    await _record_on_both_sides(session, link, actor=actor, added=True)
    return link


async def remove_area_link(
    session: AsyncSession,
    source: Area,
    target: Area,
    *,
    actor: Actor,
) -> None:
    """Снимает связь `source → target` и подшивает `link_removed` в оба дела.

    Обратная связь `target → source`, если она есть, — другая связь и остаётся. Заморозка
    не проверяется: снять можно и с архивной областью, и с областью архивного проекта.
    """
    await lock_changes(session)
    ensure_not_self(source.address, target.address)
    repository = AreaLinkRepository(session)
    link = await repository.find(source_id=source.id, target_id=target.id)
    if link is None:
        raise AreaLinkNotFoundError(details=_sides(source, target))
    # Записи — до удаления: имена связи для обоих дел считаются из строки.
    await _record_on_both_sides(session, link, actor=actor, added=False)
    await repository.delete(link)


# --- Внутреннее -------------------------------------------------------------------------


def _sides(source: Area, target: Area) -> dict[str, str]:
    """Подробности отказа: направленная пара адресов."""
    return {"source": source.address, "target": target.address}


async def _record_on_both_sides(
    session: AsyncSession, link: AreaLink, *, actor: Actor, added: bool
) -> None:
    """Подшивает запись о связи в дела обеих областей, в порядке их адресов."""
    action_id = uuid.uuid4()
    sides = (
        (link.source, AreaLinkKind.SEE_ALSO, link.target),
        (link.target, AreaLinkKind.SEE_ALSO_FROM, link.source),
    )
    for side, kind, opposite in sorted(sides, key=lambda side: side[0].address):
        await case_service.record_area_link_change(
            session,
            side,
            actor=actor,
            added=added,
            kind=kind,
            other_address=opposite.address,
            reason=link.reason,
            action_id=action_id,
        )
