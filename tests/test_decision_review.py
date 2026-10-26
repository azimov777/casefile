"""Проверка решений человеком (TRK-755, задача TRK-756): запись `decision_review`, статусы
`rejected` и `removed`, `review_state` при чтении, `supersedes` в REST, список решений
проектов и областей и число непроверенных.

Обзорные проверки задачи, которые здесь измеряются:

- 2: решение агента читается `unconfirmed`, после `confirmed` человека — `confirmed` с
  номером записи, повторное `confirmed` — `decision_already_confirmed`, решение, подписанное
  человеком, — `confirmed` без записи проверки, проверка от агента — `403 account_required`;
- 3: цепочка «B заменяет A, человек отклоняет (удаляет) B»;
- 4: человек исправляет решение через `POST …/entries` с `supersedes`;
- 5: `GET /api/v1/decisions` и число `unconfirmed_decisions` карточек и `bootstrap`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.project import Project
from app.domain.authors import Author, AuthorKind
from app.domain.case import EntryType
from app.domain.decisions import (
    DecisionStatus,
    Review,
    ReviewOutcome,
    ReviewState,
    confirmations,
    review_of_payload,
    review_state_of,
    status_of,
    withdrawals,
)
from app.domain.errors import (
    DecisionAlreadyConfirmedError,
    DecisionNotInForceError,
    ProjectArchivedError,
    TaskFieldsInvalidError,
)
from app.domain.participants import ParticipantKind
from app.services import areas as areas_service
from app.services import case as case_service
from app.services import decisions as decisions_service
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor
from conftest import make_task

AGENT = Actor(author=Author(kind=AuthorKind.AGENT, signature="claude"))


async def _decision(
    session: AsyncSession,
    owner: Any,
    actor: Actor,
    title: str,
    *,
    supersedes: list[int] | None = None,
) -> int:
    entry = await case_service.append_project_entry(
        session,
        owner,
        actor=actor,
        type=EntryType.DECISION,
        title=title,
        body="Почему так",
        supersedes=supersedes,
    )
    return entry.no


async def _by_no(session: AsyncSession, project: Project, actor: Actor) -> dict[int, Any]:
    found = await decisions_service.project_decisions(session, project, actor=actor)
    return {item.entry.no: item for item in found}


# --- Домен -------------------------------------------------------------------------------


def test_a_withdrawal_needs_a_review_after_a_decision_of_the_case() -> None:
    reviews = [
        Review(no=5, decision=1, outcome=ReviewOutcome.REJECTED),
        Review(no=6, decision=2, outcome=ReviewOutcome.REMOVED),
        Review(no=7, decision=3, outcome=ReviewOutcome.CONFIRMED),
        Review(no=2, decision=4, outcome=ReviewOutcome.REMOVED),  # раньше решения
        Review(no=9, decision=8, outcome=ReviewOutcome.REMOVED),  # 8 — не решение
    ]
    decisions = {1, 2, 3, 4}

    assert withdrawals(reviews, decisions) == {
        1: ReviewOutcome.REJECTED,
        2: ReviewOutcome.REMOVED,
    }
    assert confirmations(reviews, decisions) == {3: 7}


def test_a_superseded_decision_stays_superseded_and_a_withdrawn_one_has_its_status() -> None:
    withdrawn = {2: ReviewOutcome.REJECTED, 3: ReviewOutcome.REMOVED, 1: ReviewOutcome.REMOVED}

    assert status_of(1, {1: 2}, withdrawn) is DecisionStatus.SUPERSEDED
    assert status_of(2, {1: 2}, withdrawn) is DecisionStatus.REJECTED
    assert status_of(3, {}, withdrawn) is DecisionStatus.REMOVED
    assert status_of(4, {}, withdrawn) is DecisionStatus.IN_FORCE


def test_a_decision_is_confirmed_by_a_review_or_by_a_person_who_signed_it() -> None:
    assert review_state_of(1, {1: 9}, {1}) == (ReviewState.CONFIRMED, 9)
    assert review_state_of(2, {}, {2}) == (ReviewState.CONFIRMED, None)
    assert review_state_of(3, {}, {2}) == (ReviewState.UNCONFIRMED, None)


def test_a_review_payload_of_a_wrong_shape_is_skipped_not_read_as_a_review() -> None:
    assert review_of_payload(3, {"decision": 1, "outcome": "removed"}) == Review(
        no=3, decision=1, outcome=ReviewOutcome.REMOVED
    )
    assert review_of_payload(3, {"decision": "1", "outcome": "removed"}) is None
    assert review_of_payload(3, {"decision": 1, "outcome": "maybe"}) is None
    assert review_of_payload(3, {}) is None


# --- Проверка 2: состояние проверки ------------------------------------------------------


async def test_review_state_unconfirmed_confirmed_and_signed_by_a_person(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Проверка 2, случаи 1–3: решение агента `unconfirmed`; после `confirmed` человека —
    `confirmed` с номером записи, повтор — `decision_already_confirmed`; решение, которое
    подписал человек, — `confirmed` без записи проверки."""
    by_agent = await _decision(db_session, project, AGENT, "Решение агента")
    by_person = await _decision(db_session, project, main_actor, "Решение человека")

    before = await _by_no(db_session, project, main_actor)
    assert (before[by_agent].review_state, before[by_agent].review_entry) == (
        ReviewState.UNCONFIRMED,
        None,
    )
    assert (before[by_person].review_state, before[by_person].review_entry) == (
        ReviewState.CONFIRMED,
        None,
    )

    review = await decisions_service.review_decision(
        db_session, project, by_agent, actor=main_actor, outcome=ReviewOutcome.CONFIRMED
    )

    assert review.type is EntryType.DECISION_REVIEW
    assert review.title == f"Decision TRK#{by_agent} confirmed"
    assert review.payload == {"decision": by_agent, "outcome": "confirmed"}
    assert review.refs == [f"TRK#{by_agent}"]
    after = await _by_no(db_session, project, main_actor)
    assert (after[by_agent].review_state, after[by_agent].review_entry) == (
        ReviewState.CONFIRMED,
        review.no,
    )
    assert after[by_agent].status is DecisionStatus.IN_FORCE

    for confirmed in (by_agent, by_person):
        with pytest.raises(DecisionAlreadyConfirmedError) as again:
            await decisions_service.review_decision(
                db_session, project, confirmed, actor=main_actor, outcome=ReviewOutcome.CONFIRMED
            )
        assert again.value.code == "decision_already_confirmed"
        assert again.value.details["ref"] == f"TRK#{confirmed}"


async def test_a_confirmed_decision_can_still_be_rejected(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    no = await _decision(db_session, project, AGENT, "Решение")
    await decisions_service.review_decision(
        db_session, project, no, actor=main_actor, outcome=ReviewOutcome.CONFIRMED
    )

    await decisions_service.review_decision(
        db_session, project, no, actor=main_actor, outcome=ReviewOutcome.REJECTED, reason="Нет"
    )

    item = (await _by_no(db_session, project, main_actor))[no]
    assert (item.status, item.review_state) == (DecisionStatus.REJECTED, ReviewState.CONFIRMED)


async def test_only_a_person_with_an_account_reviews(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """Проверка 2, случай 4: та же проверка от агента — `permission_denied`,
    `account_required`; в деле ничего не появляется."""
    no = await _decision(db_session, project, AGENT, "Решение")
    robot = await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="robot"
    )

    for caller in (AGENT, Actor(author=robot.author, participant=robot), TRACKER_ACTOR):
        with pytest.raises(PermissionDeniedError) as refused:
            await decisions_service.review_decision(
                db_session, project, no, actor=caller, outcome=ReviewOutcome.REMOVED
            )
        assert refused.value.details == {
            "action": "decision.review",
            "reason": "account_required",
        }
    reviews = await case_service.list_project_entries(
        db_session, project, actor=main_actor, types=[EntryType.DECISION_REVIEW]
    )
    assert reviews.items == []


async def test_a_review_refuses_a_decision_that_is_not_in_force_or_not_a_decision(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    old = await _decision(db_session, project, AGENT, "Старое")
    new = await _decision(db_session, project, AGENT, "Новое", supersedes=[old])
    note = await case_service.append_project_entry(
        db_session, project, actor=AGENT, type=EntryType.FINDING, title="Заметка"
    )

    with pytest.raises(DecisionNotInForceError) as superseded:
        await decisions_service.review_decision(
            db_session, project, old, actor=main_actor, outcome=ReviewOutcome.REMOVED
        )
    assert superseded.value.details["decisions"] == [
        {"ref": f"TRK#{old}", "superseded_by": f"TRK#{new}"}
    ]
    await decisions_service.review_decision(
        db_session, project, new, actor=main_actor, outcome=ReviewOutcome.REMOVED
    )
    with pytest.raises(DecisionNotInForceError) as removed:
        await decisions_service.review_decision(
            db_session, project, new, actor=main_actor, outcome=ReviewOutcome.REJECTED
        )
    assert removed.value.details["decisions"] == [
        {"ref": f"TRK#{new}", "superseded_by": None, "status": "removed"}
    ]
    for missing in (note.no, 99):
        with pytest.raises(DecisionNotInForceError):
            await decisions_service.review_decision(
                db_session, project, missing, actor=main_actor, outcome=ReviewOutcome.CONFIRMED
            )


async def test_an_archived_project_is_not_reviewed(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    no = await _decision(db_session, project, AGENT, "Решение")
    await projects_service.archive_project(db_session, project, actor=main_actor, reason="Пауза")

    with pytest.raises(ProjectArchivedError):
        await decisions_service.review_decision(
            db_session, project, no, actor=main_actor, outcome=ReviewOutcome.CONFIRMED
        )


# --- Проверка 3: цепочка замен -----------------------------------------------------------


@pytest.mark.parametrize("outcome", [ReviewOutcome.REJECTED, ReviewOutcome.REMOVED])
async def test_a_withdrawn_decision_leaves_force_and_brings_back_nothing(
    db_session: AsyncSession, project: Project, main_actor: Actor, outcome: ReviewOutcome
) -> None:
    """Проверка 3: B заменяет A, человек отклоняет (или удаляет) B. B — `rejected`
    (`removed`) без преемника; A остаётся `superseded` с преемником B; ни A, ни B нет среди
    действующих; `supersedes=[B]` и ссылка задачи на B — `decision_not_in_force`."""
    a = await _decision(db_session, project, AGENT, "A")
    b = await _decision(db_session, project, AGENT, "B", supersedes=[a])

    await decisions_service.review_decision(
        db_session, project, b, actor=main_actor, outcome=outcome, reason="Причина"
    )

    items = await _by_no(db_session, project, main_actor)
    expected = DecisionStatus(outcome.value)
    assert (items[b].status, items[b].superseded_by) == (expected, None)
    assert (items[a].status, items[a].superseded_by.no) == (DecisionStatus.SUPERSEDED, b)
    knowledge = await decisions_service.case_knowledge(db_session, project, actor=main_actor)
    assert knowledge.decisions == []
    in_force = await case_service.list_project_entries(
        db_session, project, actor=main_actor, in_force=True
    )
    assert in_force.items == []
    out_of_force = await case_service.list_project_entries(
        db_session, project, actor=main_actor, in_force=False
    )
    assert [entry.no for entry in out_of_force.items] == [a, b]
    assert out_of_force.standings[b].status is expected

    with pytest.raises(DecisionNotInForceError) as chained:
        await _decision(db_session, project, AGENT, "C", supersedes=[b])
    assert chained.value.details["decisions"] == [
        {"ref": f"TRK#{b}", "superseded_by": None, "status": expected.value}
    ]
    with pytest.raises(DecisionNotInForceError) as cited:
        await make_task(
            db_session,
            actor=main_actor,
            project=project,
            title="Задача",
            description="По решению",
            decisions=[f"TRK#{b}"],
        )
    assert cited.value.details["decisions"][0]["status"] == expected.value
    with pytest.raises((DecisionNotInForceError, TaskFieldsInvalidError)):
        await make_task(
            db_session,
            actor=main_actor,
            project=project,
            title="Задача",
            description="По старому",
            decisions=[f"TRK#{a}"],
        )


async def test_an_area_decision_is_reviewed_like_a_project_one(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    area = await areas_service.get_area(db_session, "TRK/core")
    no = await _decision(db_session, area, AGENT, "Решение области")

    entry = await decisions_service.review_decision(
        db_session, area, no, actor=main_actor, outcome=ReviewOutcome.REMOVED
    )

    assert entry.area_id == area.id
    assert entry.title == f"Decision TRK/core#{no} removed"
    standings = await decisions_service.case_standings(db_session, area)
    assert standings.of_number(no).status is DecisionStatus.REMOVED
    knowledge = await decisions_service.case_knowledge(db_session, area, actor=main_actor)
    assert knowledge.decisions == []


# --- REST --------------------------------------------------------------------------------


async def _agent_headers(session: AsyncSession, name: str = "robot") -> dict[str, str]:
    robot = await participants_service.register_participant(
        session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name=name
    )
    issued = await tokens_service.issue_token(
        session, actor=TRACKER_ACTOR, participant=robot, name=name
    )
    return {"Authorization": f"Bearer {issued.secret}"}


async def test_rest_review_files_the_entry_and_the_read_carries_the_state(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    no = await _decision(db_session, project, AGENT, "Решение агента")
    path = f"/api/v1/projects/TRK/decisions/{no}/review"

    refused = await auth_client.post(
        path, json={"outcome": "confirmed"}, headers=await _agent_headers(db_session)
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "account_required"
    unread = await auth_client.get(f"/api/v1/projects/TRK/entries/{no}")
    assert (unread.json()["data"]["review_state"], unread.json()["data"]["review_entry"]) == (
        "unconfirmed",
        None,
    )

    filed = await auth_client.post(path, json={"outcome": "confirmed", "reason": "Согласен"})
    assert filed.status_code == 201, filed.text
    entry = filed.json()["data"]
    assert (entry["type"], entry["payload"], entry["body"]) == (
        "decision_review",
        {"decision": no, "outcome": "confirmed"},
        "Согласен",
    )
    read = await auth_client.get(f"/api/v1/projects/TRK/entries/{no}")
    assert (read.json()["data"]["review_state"], read.json()["data"]["review_entry"]) == (
        "confirmed",
        entry["no"],
    )
    again = await auth_client.post(path, json={"outcome": "confirmed"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "decision_already_confirmed"
    detail = await auth_client.get("/api/v1/projects/TRK")
    (decision,) = detail.json()["data"]["decisions"]
    assert (decision["status"], decision["review_state"], decision["review_entry"]) == (
        "in_force",
        "confirmed",
        entry["no"],
    )
    bad = await auth_client.post(path, json={"outcome": "maybe"})
    assert bad.status_code == 422


async def test_rest_review_of_an_area_decision(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    area = await areas_service.get_area(db_session, "TRK/core")
    no = await _decision(db_session, area, AGENT, "Решение области")

    filed = await auth_client.post(
        f"/api/v1/projects/TRK/areas/core/decisions/{no}/review", json={"outcome": "removed"}
    )

    assert filed.status_code == 201, filed.text
    assert filed.json()["data"]["area"] == "TRK/core"
    read = await auth_client.get(f"/api/v1/projects/TRK/areas/core/entries/{no}")
    assert (read.json()["data"]["status"], read.json()["data"]["superseded_by"]) == (
        "removed",
        None,
    )
    gone = await auth_client.post(
        f"/api/v1/projects/TRK/areas/core/decisions/{no}/review", json={"outcome": "confirmed"}
    )
    assert gone.status_code == 409
    assert gone.json()["error"]["code"] == "decision_not_in_force"


async def test_a_person_corrects_a_decision_with_a_new_one_that_supersedes(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    """Проверка 4: человек шлёт `POST …/entries` с `supersedes` — новое решение сразу
    `confirmed`, прежнее — `superseded`. То же у дела области."""
    area = await areas_service.get_area(db_session, "TRK/core")
    for path, owner in (
        ("/api/v1/projects/TRK", project),
        ("/api/v1/projects/TRK/areas/core", area),
    ):
        old = await _decision(db_session, owner, AGENT, "Решение агента")

        created = await auth_client.post(
            f"{path}/entries",
            json={"type": "decision", "title": "Исправленное", "supersedes": [old]},
        )

        assert created.status_code == 201, created.text
        new = created.json()["data"]["no"]
        read_new = await auth_client.get(f"{path}/entries/{new}")
        read_old = await auth_client.get(f"{path}/entries/{old}")
        assert read_new.json()["data"]["status"] == "in_force"
        assert read_new.json()["data"]["review_state"] == "confirmed"
        assert read_old.json()["data"]["status"] == "superseded"
        assert read_old.json()["data"]["superseded_by"] == new


# --- Проверка 5: список решений и счётчики ----------------------------------------------


async def test_the_list_holds_decisions_of_projects_and_areas_and_counts_the_unconfirmed(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    area = await areas_service.get_area(db_session, "TRK/core")
    first = await _decision(db_session, project, AGENT, "Проектное")
    second = await _decision(
        db_session, project, AGENT, "Проектное, заменённое", supersedes=[first]
    )
    in_area = await _decision(db_session, area, AGENT, "Областное")
    await _decision(db_session, area, main_actor, "Областное человека")
    removed = await _decision(db_session, project, AGENT, "Удалённое")
    await decisions_service.review_decision(
        db_session, project, removed, actor=main_actor, outcome=ReviewOutcome.REMOVED
    )
    task = await make_task(
        db_session,
        actor=main_actor,
        project=project,
        title="Задача",
        description="По решению",
        decisions=[f"TRK#{second}"],
    )
    # Архивный проект: его решения не входят в список без `project` и в `bootstrap`.
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OLD", title="Старый", description=""
    )
    await _decision(db_session, other, AGENT, "Из архивного проекта")
    await projects_service.archive_project(db_session, other, actor=main_actor, reason="Конец")

    listed = await auth_client.get(
        "/api/v1/decisions", params={"project": "TRK", "review_state": "unconfirmed"}
    )

    assert listed.status_code == 200, listed.text
    body = listed.json()
    refs = [(item["ref"], item["area"]) for item in body["data"]]
    assert refs == [
        (f"TRK#{first}", None),
        (f"TRK#{second}", None),
        (f"TRK/core#{in_area}", "TRK/core"),
        (f"TRK#{removed}", None),
    ]
    by_ref = {item["ref"]: item for item in body["data"]}
    assert by_ref[f"TRK#{first}"]["status"] == "superseded"
    assert by_ref[f"TRK#{first}"]["superseded_by"] == f"TRK#{second}"
    assert by_ref[f"TRK#{second}"]["supersedes"] == [f"TRK#{first}"]
    assert by_ref[f"TRK#{second}"]["tasks"] == 1
    assert by_ref[f"TRK#{removed}"]["status"] == "removed"
    assert by_ref[f"TRK#{removed}"]["refs"] == []
    assert task.key == "TRK-1"
    card = (await auth_client.get("/api/v1/projects/TRK")).json()["data"]
    area_card = (await auth_client.get("/api/v1/projects/TRK/areas/core")).json()["data"]
    assert body["unconfirmed"] == card["unconfirmed_decisions"] == 2
    assert area_card["unconfirmed_decisions"] == 1

    everywhere = await auth_client.get(
        "/api/v1/decisions", params={"review_state": "unconfirmed", "status": "in_force"}
    )
    assert {item["ref"] for item in everywhere.json()["data"]} == {
        f"TRK#{second}",
        f"TRK/core#{in_area}",
    }
    assert not any(item["ref"].startswith("OLD") for item in everywhere.json()["data"])
    boot = (await auth_client.get("/api/v1/bootstrap")).json()["data"]
    assert everywhere.json()["unconfirmed"] == boot["unconfirmed_decisions"] == 2

    old_list = await auth_client.get("/api/v1/decisions", params={"project": "OLD"})
    assert [item["title"] for item in old_list.json()["data"]] == ["Из архивного проекта"]
    assert old_list.json()["unconfirmed"] == 1


async def test_the_list_pages_by_cursor_oldest_first(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    numbers = [await _decision(db_session, project, AGENT, f"Решение {i}") for i in range(5)]

    first = await auth_client.get("/api/v1/decisions", params={"project": "TRK", "limit": 2})
    second = await auth_client.get(
        "/api/v1/decisions",
        params={"project": "TRK", "limit": 2, "cursor": first.json()["meta"]["next_cursor"]},
    )
    third = await auth_client.get(
        "/api/v1/decisions",
        params={"project": "TRK", "limit": 2, "cursor": second.json()["meta"]["next_cursor"]},
    )

    seen = [item["ref"] for page in (first, second, third) for item in page.json()["data"]]
    assert seen == [f"TRK#{no}" for no in numbers]
    assert first.json()["meta"]["has_more"] is True
    assert third.json()["meta"]["has_more"] is False
    assert third.json()["unconfirmed"] == 5


async def test_an_old_decision_reads_unconfirmed_without_a_migration_of_data(
    auth_client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    """Решения, подшитые агентами до выпуска, читаются `unconfirmed` сами: состояние
    считается при чтении, строк проверки у них нет."""
    no = await _decision(db_session, project, AGENT, "Подшито до выпуска")

    read = await auth_client.get(f"/api/v1/projects/TRK/entries/{no}")

    assert read.json()["data"]["review_state"] == "unconfirmed"
    entries = await auth_client.get(
        "/api/v1/projects/TRK/entries", params={"types": "decision_review"}
    )
    assert entries.json()["data"] == []
