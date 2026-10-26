"""Сценарии связей областей `see_also` (TRK-733): постановка, снятие, записи в обоих делах,
архив и REST на демо-данных."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.project import Project
from app.domain.area_links import MAX_AREA_LINK_REASON_LENGTH, AreaLinkKind
from app.domain.case import EntryType, LinkFacts
from app.domain.errors import (
    AreaArchivedError,
    AreaLinkExistsError,
    AreaLinkNotFoundError,
    AreaLinkReasonRequiredError,
    AreaLinkReasonTooLongError,
    AreaLinkSelfError,
    ProjectArchivedError,
)
from app.services import area_links as service
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import projects as projects_service
from app.services.auth import Actor
from app.services.demo import seed_demo

AREA = "/api/v1/projects/{key}/areas/{area}"


async def make_area(session: AsyncSession, actor: Actor, address: str) -> Area:
    return await areas_service.create_area(
        session,
        actor=actor,
        address=address,
        title=address.split("/")[1].upper(),
        description="область",
    )


async def link_entries(session: AsyncSession, area: Area, actor: Actor) -> list[dict[str, object]]:
    page = await case_service.list_project_entries(
        session,
        area,
        actor=actor,
        types=[EntryType.LINK_ADDED, EntryType.LINK_REMOVED],
        limit=50,
    )
    return [
        {
            "type": entry.type,
            "title": entry.title,
            "payload": entry.payload,
            "action": entry.action_id,
        }
        for entry in page.items
    ]


async def test_a_link_is_one_row_with_an_entry_in_each_case(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """A→B: одна строка; `see_also` в деле A, `see_also_from` в деле B, причина в обеих;
    повтор, связь с собой и пустая или длинная причина отказывают; B→A — вторая связь."""
    a = await make_area(db_session, main_actor, "TRK/a")
    b = await make_area(db_session, main_actor, "TRK/b")

    link = await service.add_area_link(db_session, a, b, actor=main_actor, reason="  читать там ")
    assert link.reason == "читать там"
    assert [item.target.address for item in await service.list_see_also(db_session, a)] == ["TRK/b"]
    assert [item.source.address for item in await service.list_see_also_from(db_session, b)] == [
        "TRK/a"
    ]
    assert await service.list_see_also(db_session, b) == []

    on_a = await link_entries(db_session, a, main_actor)
    on_b = await link_entries(db_session, b, main_actor)
    assert [(e["type"], e["payload"]) for e in on_a] == [
        (EntryType.LINK_ADDED, {"kind": "see_also", "other": "TRK/b", "reason": "читать там"})
    ]
    assert [(e["type"], e["payload"]) for e in on_b] == [
        (
            EntryType.LINK_ADDED,
            {"kind": "see_also_from", "other": "TRK/a", "reason": "читать там"},
        )
    ]
    assert on_a[0]["title"] == "Link added: see also TRK/b"
    assert on_b[0]["title"] == "Link added: TRK/a lists this area in see also"
    assert on_a[0]["action"] == on_b[0]["action"]

    with pytest.raises(AreaLinkExistsError):
        await service.add_area_link(db_session, a, b, actor=main_actor, reason="снова")
    with pytest.raises(AreaLinkSelfError):
        await service.add_area_link(db_session, a, a, actor=main_actor, reason="себя")
    with pytest.raises(AreaLinkReasonRequiredError):
        await service.add_area_link(db_session, b, a, actor=main_actor, reason="   ")
    with pytest.raises(AreaLinkReasonTooLongError):
        await service.add_area_link(
            db_session, b, a, actor=main_actor, reason="я" * (MAX_AREA_LINK_REASON_LENGTH + 1)
        )

    back = await service.add_area_link(db_session, b, a, actor=main_actor, reason="обратно")
    assert back.reason == "обратно"
    assert len(await service.list_see_also(db_session, a)) == 1
    assert len(await service.list_see_also_from(db_session, a)) == 1


async def test_the_case_index_names_the_link_kind_and_the_other_area(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    a = await make_area(db_session, main_actor, "TRK/a")
    b = await make_area(db_session, main_actor, "TRK/b")
    await service.add_area_link(db_session, a, b, actor=main_actor, reason="причина")

    on_a = (await case_service.project_case_index(db_session, a, actor=main_actor))[-1]
    on_b = (await case_service.project_case_index(db_session, b, actor=main_actor))[-1]
    assert on_a.facts == LinkFacts(
        type=EntryType.LINK_ADDED, link_kind=AreaLinkKind.SEE_ALSO, other_area="TRK/b"
    )
    assert on_b.facts == LinkFacts(
        type=EntryType.LINK_ADDED, link_kind=AreaLinkKind.SEE_ALSO_FROM, other_area="TRK/a"
    )


async def test_removing_a_link_files_link_removed_and_a_missing_one_refuses(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    a = await make_area(db_session, main_actor, "TRK/a")
    b = await make_area(db_session, main_actor, "TRK/b")
    with pytest.raises(AreaLinkNotFoundError):
        await service.remove_area_link(db_session, a, b, actor=main_actor)
    await service.add_area_link(db_session, a, b, actor=main_actor, reason="причина")
    # Обратного направления нет: снять B→A нельзя, A→B цела.
    with pytest.raises(AreaLinkNotFoundError):
        await service.remove_area_link(db_session, b, a, actor=main_actor)
    await service.remove_area_link(db_session, a, b, actor=main_actor)

    assert await service.list_see_also(db_session, a) == []
    for area, kind, other in ((a, "see_also", "TRK/b"), (b, "see_also_from", "TRK/a")):
        entries = await link_entries(db_session, area, main_actor)
        assert [e["type"] for e in entries] == [EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
        assert entries[1]["payload"] == {"kind": kind, "other": other, "reason": "причина"}


async def test_an_archived_area_takes_no_link_but_gives_it_up(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Постановка к архивной области (с любой стороны) — `area_archived`; связь, поставленная
    до архива, снимается, и `link_removed` ложится в оба дела, включая архивное."""
    a = await make_area(db_session, main_actor, "TRK/a")
    b = await make_area(db_session, main_actor, "TRK/b")
    c = await make_area(db_session, main_actor, "TRK/c")
    await service.add_area_link(db_session, a, b, actor=main_actor, reason="причина")
    await areas_service.archive_area(db_session, b, actor=main_actor, reason="пауза")

    with pytest.raises(AreaArchivedError):
        await service.add_area_link(db_session, c, b, actor=main_actor, reason="причина")
    with pytest.raises(AreaArchivedError):
        await service.add_area_link(db_session, b, c, actor=main_actor, reason="причина")
    # Архив называется раньше причины.
    with pytest.raises(AreaArchivedError):
        await service.add_area_link(db_session, c, b, actor=main_actor, reason="")
    assert len(await service.list_see_also(db_session, a)) == 1  # архив связь не прячет

    await service.remove_area_link(db_session, a, b, actor=main_actor)
    for area in (a, b):
        types = [e["type"] for e in await link_entries(db_session, area, main_actor)]
        assert types == [EntryType.LINK_ADDED, EntryType.LINK_REMOVED]


async def test_an_archived_project_takes_no_link_but_gives_it_up(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OTH", title="Другой", description="д"
    )
    a = await make_area(db_session, main_actor, "TRK/a")
    z = await make_area(db_session, main_actor, "OTH/z")
    c = await make_area(db_session, main_actor, "TRK/c")
    # Область другого проекта — можно.
    await service.add_area_link(db_session, a, z, actor=main_actor, reason="причина")
    await projects_service.archive_project(db_session, other, actor=main_actor, reason="всё")

    with pytest.raises(ProjectArchivedError):
        await service.add_area_link(db_session, c, z, actor=main_actor, reason="причина")
    with pytest.raises(ProjectArchivedError):
        await service.add_area_link(db_session, z, c, actor=main_actor, reason="причина")

    await service.remove_area_link(db_session, a, z, actor=main_actor)
    for area in (a, z):
        types = [e["type"] for e in await link_entries(db_session, area, main_actor)]
        assert types == [EntryType.LINK_ADDED, EntryType.LINK_REMOVED]


async def test_rest_shows_the_demo_link_from_both_sides_and_in_both_cases(
    db_session: AsyncSession, auth_client: AsyncClient
) -> None:
    """Демо: `DEMO/ui` → `DEMO/core`. Карточка источника отдаёт `see_also`, цели —
    `see_also_from`; в делах обеих лежит `link_added` с фактами описи."""
    await seed_demo(db_session)

    ui = (await auth_client.get(AREA.format(key="DEMO", area="ui"))).json()["data"]
    core = (await auth_client.get(AREA.format(key="DEMO", area="core"))).json()["data"]
    assert len(ui["see_also"]) == 1
    row = ui["see_also"][0]
    assert (row["address"], row["title"]) == ("DEMO/core", core["title"])
    assert row["description"] == core["description"]
    assert row["reason"] == "Экраны показывают механики ядра: их правила — там."
    assert row["created_by"]["kind"] == "agent" and row["created_at"]
    assert ui["see_also_from"] == []
    assert core["see_also"] == []
    assert len(core["see_also_from"]) == 1
    incoming = core["see_also_from"][0]
    assert (incoming["address"], incoming["title"]) == ("DEMO/ui", ui["title"])
    assert incoming["reason"] == row["reason"]
    assert "description" not in incoming

    for key, kind, other in (("ui", "see_also", "DEMO/core"), ("core", "see_also_from", "DEMO/ui")):
        response = await auth_client.get(
            AREA.format(key="DEMO", area=key) + "/entries", params={"types": "link_added"}
        )
        items = response.json()["data"]
        assert [(i["type"], i["payload"]["kind"], i["payload"]["other"]) for i in items] == [
            ("link_added", kind, other)
        ]
