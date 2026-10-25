"""Репозиторий связей областей: направленная пара, обе стороны, ограничения базы (TRK-732)."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.area_link import AreaLink
from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.repositories.area_links import AreaLinkRepository


async def make_areas(session: AsyncSession, owner: Participant) -> list[Area]:
    project = Project(key="ALK", title="Проект", **_author(owner))
    session.add(project)
    await session.flush()
    areas = [
        Area(project_id=project.id, key=key, title=key, **_author(owner))
        for key in ("alpha", "beta", "gamma")
    ]
    session.add_all(areas)
    await session.flush()
    return areas


def _author(owner: Participant) -> dict[str, object]:
    return {
        "created_by_kind": owner.author.kind,
        "created_by_signature": owner.author.signature,
    }


def link(source: Area, target: Area, owner: Participant, reason: str = "читать") -> AreaLink:
    return AreaLink(
        source_area_id=source.id, target_area_id=target.id, reason=reason, **_author(owner)
    )


async def test_a_link_is_directed_and_read_from_both_sides(
    db_session: AsyncSession, owner: Participant
) -> None:
    alpha, beta, gamma = await make_areas(db_session, owner)
    alpha_id, beta_id, gamma_id = alpha.id, beta.id, gamma.id
    repo = AreaLinkRepository(db_session)
    await repo.add(link(alpha, beta, owner, "первая"))
    await repo.add(link(beta, alpha, owner, "обратная"))
    await repo.add(link(gamma, beta, owner, "третья"))
    db_session.expire_all()

    assert (await repo.find(source_id=alpha_id, target_id=beta_id)).reason == "первая"  # type: ignore[union-attr]
    assert (await repo.find(source_id=beta_id, target_id=alpha_id)).reason == "обратная"  # type: ignore[union-attr]
    assert await repo.find(source_id=alpha_id, target_id=gamma_id) is None
    assert [item.target.address for item in await repo.list_outgoing(alpha_id)] == ["ALK/beta"]
    assert [item.source.address for item in await repo.list_incoming(beta_id)] == [
        "ALK/alpha",
        "ALK/gamma",
    ]
    found = await repo.find(source_id=gamma_id, target_id=beta_id)
    assert found is not None
    await repo.delete(found)
    assert await repo.find(source_id=gamma_id, target_id=beta_id) is None


@pytest.mark.parametrize("reason", ["", "я" * 201])
async def test_the_database_refuses_a_reason_out_of_range(
    db_session: AsyncSession, owner: Participant, reason: str
) -> None:
    alpha, beta, _ = await make_areas(db_session, owner)
    with pytest.raises(IntegrityError, match="ck_area_links_reason_length"):
        await AreaLinkRepository(db_session).add(link(alpha, beta, owner, reason))
