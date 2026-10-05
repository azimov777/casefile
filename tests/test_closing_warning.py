"""Исходы `partial` и `unverifiable` и предупреждение закрытия: обзорные проверки TRK-561.

Механика одна, обещания три:

- **честный исход не дороже `passed` с оговоркой.** Закрытие с `partial` и
  `unverifiable` проходит без новых аргументов: предупреждение подшивает само закрытие,
  агенту остаётся только доказательство, которое он писал бы и в оговорке;
- **предупреждение не теряется.** Оно открыто, пока после него нет `acceptance` или
  `remark`, видно признаком `open_warnings` в карточке, строкой поиска и числом первого
  экрана — и задача с ним из поиска не пропадает, сколько бы ни прошло;
- **снять его может только реакция со стороны.** Подпись, закрывшая задачу, своё
  предупреждение не принимает; вернуть задачу замечанием может любой.

Закрывает задачи агент `claude` своим ключом, реагирует человек `owner` — так, как это
происходит в установке владельца.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType, open_warning
from app.domain.participants import ParticipantKind
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import participants as participants_service
from app.services import tasks as tasks_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor
from conftest import Connect, call, refuse

CHECKS = [
    "Зелёный прогон тестов",
    "Сквозной сценарий в Safari владельца",
    "Замер на живой установке",
]

CLOSING_SUMMARY = {
    "done": "Закрыта не целиком: проверки 2 и 3",
    "remaining": "nothing",
    "blockers": "nothing",
    "next_step": "no steps",
    "unmeasured": "Safari и живая установка — см. вердикты 2 и 3",
}

#: Последние вердикты прохода из проверки 2 задачи: 1 `passed`, 2 `partial`,
#: 3 `unverifiable`.
MIXED_VERDICTS = [
    {"check_no": 1, "outcome": "passed", "evidence": "docker compose run --rm test: 900 passed"},
    {"check_no": 2, "outcome": "partial", "evidence": "Прогнан в Chromium, не в Safari"},
    {"check_no": 3, "outcome": "unverifiable", "evidence": "Установка недоступна; замер на деве"},
]

EXPECTED_CHECKS = [
    {"check_no": 2, "outcome": "partial"},
    {"check_no": 3, "outcome": "unverifiable"},
]


# --- Помощники ------------------------------------------------------------------------


@pytest.fixture
async def agent(db_session: AsyncSession) -> Participant:
    """Агент `claude`: он закрывает задачи. Человек `owner` — тот, кто на них реагирует."""
    return await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="claude"
    )


@pytest.fixture
async def agent_secret(db_session: AsyncSession, agent: Participant) -> str:
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, participant=agent, name="agent key"
    )
    return issued.secret


@pytest.fixture
def agent_actor(agent: Participant) -> Actor:
    return Actor(author=agent.author, participant=agent)


async def working(session: AsyncSession, actor: Actor, project: Project, title: str) -> Task:
    """Задача агента в `in_progress` с тремя проверками и сводкой этого захода."""
    task = await tasks_service.create_task(
        session,
        actor=actor,
        project=project,
        title=title,
        description="описание",
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=CHECKS,
        assignee=actor.author.signature,
    )
    await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.OPEN)
    await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.IN_PROGRESS)
    return task


async def close_mixed(session: AsyncSession, actor: Actor, task: Task) -> None:
    """Закрытие сценарием с вердиктами 1 `passed`, 2 `partial`, 3 `unverifiable`."""
    await tasks_service.close_task(
        session,
        task,
        actor=actor,
        summary=case_service.SummaryFiling(**CLOSING_SUMMARY),
        verdicts=[case_service.VerdictFiling(**item) for item in MIXED_VERDICTS],
    )


async def entries(client: AsyncClient, key: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/tasks/{key}/entries", params={"limit": 200})
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


async def features(client: AsyncClient, key: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/tasks/{key}")
    assert response.status_code == 200, response.text
    return dict(response.json()["data"]["features"])


async def found(client: AsyncClient, query: str) -> list[str]:
    response = await client.get("/api/v1/tasks", params={"query": query})
    assert response.status_code == 200, response.text
    return [item["key"] for item in response.json()["data"]]


async def file_acceptance(client: AsyncClient, key: str) -> Any:
    return await client.post(
        f"/api/v1/tasks/{key}/entries",
        json={"type": "acceptance", "title": "Принято: Safari посмотрю сам"},
    )


# --- Проверка 1: исходы и обязательное доказательство ---------------------------------


@pytest.mark.parametrize("outcome", ["partial", "unverifiable"])
async def test_rest_verdict_not_in_full_needs_evidence(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
    outcome: str,
) -> None:
    """REST: `partial`/`unverifiable` с доказательством подшиваются, без него — отказ."""
    task = await working(db_session, task_actor, project, "Исход по REST")

    filed = await auth_client.post(
        f"/api/v1/tasks/{task.key}/entries",
        json={
            "type": "verdict",
            "body": "Прогнан в Chromium",
            "payload": {"check_no": 2, "outcome": outcome},
        },
    )
    empty = await auth_client.post(
        f"/api/v1/tasks/{task.key}/entries",
        json={"type": "verdict", "body": "", "payload": {"check_no": 2, "outcome": outcome}},
    )
    closing = await auth_client.post(
        f"/api/v1/tasks/{task.key}/close",
        json={
            "summary": CLOSING_SUMMARY,
            "verdicts": [{"check_no": 1, "outcome": outcome, "evidence": "  "}],
        },
    )

    assert filed.status_code == 201, filed.text
    assert filed.json()["data"]["payload"] == {"check_no": 2, "outcome": outcome}
    for refused in (empty, closing):
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "entry_fields_invalid"
        assert {"field": "evidence", "reason": "required", "required_for": outcome} in error[
            "details"
        ]["fields"]


@pytest.mark.parametrize("outcome", ["partial", "unverifiable"])
async def test_mcp_verdict_not_in_full_needs_evidence(
    mcp_session: Connect,
    agent_secret: str,
    db_session: AsyncSession,
    agent_actor: Actor,
    project: Project,
    outcome: str,
) -> None:
    """MCP: тот же исход и тот же отказ — второго контракта нет."""
    task = await working(db_session, agent_actor, project, "Исход по MCP")

    async with mcp_session(agent_secret) as session:
        filed = await call(
            session,
            "add_verdict",
            key=task.key,
            check_no=3,
            outcome=outcome,
            evidence="Установка недоступна",
        )
        failure = await refuse(
            session, "add_verdict", key=task.key, check_no=3, outcome=outcome, evidence=""
        )

    assert filed["title"] == f"Verdict on check 3: {outcome}"
    assert "entry_fields_invalid" in failure
    assert '"field": "evidence"' in failure


# --- Проверка 2: закрытие подшивает предупреждение ------------------------------------


async def test_mcp_closing_with_partial_and_unverifiable_files_a_warning(
    mcp_session: Connect,
    agent_secret: str,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    agent_actor: Actor,
    project: Project,
) -> None:
    """Записи → вердикты → `warning` → сводка → `status_changed`, одним действием."""
    task = await working(db_session, agent_actor, project, "Закрытие не целиком")

    async with mcp_session(agent_secret) as session:
        closed = await call(
            session,
            "close_task",
            key=task.key,
            summary=CLOSING_SUMMARY,
            verdicts=MIXED_VERDICTS,
        )
        package = await call(session, "get_task", key=task.key)
        listed = await call(session, "search_tasks", query="open_warnings: > 0")

    assert closed["status"] == "done"
    case = await entries(auth_client, task.key)
    tail = case[-6:]
    assert [entry["type"] for entry in tail] == [
        "verdict",
        "verdict",
        "verdict",
        "warning",
        "summary",
        "status_changed",
    ]
    assert len({entry["action_id"] for entry in tail}) == 1
    warning = tail[3]
    assert warning["payload"] == {"checks": EXPECTED_CHECKS}
    assert warning["title"] == "Closed not in full: check 2 partial, check 3 unverifiable"
    assert warning["author"]["signature"] == "claude"
    assert [item["title"] for item in closed["entries"]][3] == warning["title"]

    assert package["task"]["status"] == "done"
    assert package["features"]["open_warnings"] == 1
    heading = next(item for item in package["index"] if item["type"] == "warning")
    assert heading["facts"] == {"type": "warning", "partial": [2], "unverifiable": [3]}
    assert [item["key"] for item in listed["items"]] == [task.key]
    listed_features = listed["items"][0]["features"]
    assert listed_features["open_warnings"] == package["features"]["open_warnings"]


async def test_rest_closing_files_the_same_warning(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """REST `POST /tasks/{key}/close` — та же подшивка и тот же признак, что у MCP."""
    task = await working(db_session, task_actor, project, "Закрытие по REST")

    closed = await auth_client.post(
        f"/api/v1/tasks/{task.key}/close",
        json={"summary": CLOSING_SUMMARY, "verdicts": MIXED_VERDICTS},
    )

    assert closed.status_code == 200, closed.text
    assert closed.json()["data"]["status"] == "done"
    case = await entries(auth_client, task.key)
    assert [entry["type"] for entry in case[-3:]] == ["warning", "summary", "status_changed"]
    assert case[-3]["payload"] == {"checks": EXPECTED_CHECKS}
    assert (await features(auth_client, task.key))["open_warnings"] == 1
    assert await found(auth_client, "open_warnings: > 0") == [task.key]
    by_parameter = await auth_client.get("/api/v1/tasks", params={"open_warnings": 1})
    assert [item["key"] for item in by_parameter.json()["data"]] == [task.key]


async def test_warning_counts_verdicts_filed_earlier_in_the_pass(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Предупреждение считается по делу, а не по составу вызова, как и условие выхода."""
    task = await working(db_session, task_actor, project, "Вердикт по ходу работы")
    await case_service.add_verdict(
        db_session, task, actor=task_actor, check_no=2, outcome="partial", evidence="половина"
    )

    closed = await auth_client.post(
        f"/api/v1/tasks/{task.key}/close",
        json={
            "summary": CLOSING_SUMMARY,
            "verdicts": [
                {"check_no": 1, "outcome": "passed", "evidence": "зелёный"},
                {"check_no": 3, "outcome": "passed", "evidence": "замер"},
            ],
        },
    )

    assert closed.status_code == 200, closed.text
    warning = next(
        item for item in await entries(auth_client, task.key) if item["type"] == "warning"
    )
    assert warning["payload"] == {"checks": [{"check_no": 2, "outcome": "partial"}]}


# --- Проверка 3: все `passed` — без предупреждения; `failed` — отказ ------------------


async def test_closing_with_passed_only_files_no_warning(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    task = await working(db_session, task_actor, project, "Всё прошло")

    closed = await auth_client.post(
        f"/api/v1/tasks/{task.key}/close",
        json={
            "summary": CLOSING_SUMMARY,
            "verdicts": [
                {"check_no": no, "outcome": "passed", "evidence": "да"} for no in (1, 2, 3)
            ],
        },
    )

    assert closed.status_code == 200, closed.text
    case = await entries(auth_client, task.key)
    assert "warning" not in {entry["type"] for entry in case}
    assert (await features(auth_client, task.key))["open_warnings"] == 0
    assert await found(auth_client, "open_warnings: > 0") == []


async def test_failed_still_refuses_closing_and_files_nothing(
    mcp_session: Connect,
    agent_secret: str,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    agent_actor: Actor,
    project: Project,
) -> None:
    """`failed` не закрывает и рядом с `partial`: отказ не оставляет ни записи."""
    task = await working(db_session, agent_actor, project, "Провал")
    # Отказ откатывает транзакцию теста, и объект задачи после него не читается: ключ
    # берётся заранее.
    key = task.key
    before = await entries(auth_client, key)

    async with mcp_session(agent_secret) as session:
        failure = await refuse(
            session,
            "close_task",
            key=key,
            summary=CLOSING_SUMMARY,
            verdicts=[*MIXED_VERDICTS[:2], {"check_no": 3, "outcome": "failed", "evidence": "нет"}],
        )

    assert "checks_not_passed" in failure
    assert '"reason": "failed"' in failure
    after = await entries(auth_client, key)
    assert len(after) == len(before)
    assert (await auth_client.get(f"/api/v1/tasks/{key}")).json()["data"]["task"][
        "status"
    ] == "in_progress"


# --- Проверка 4: реакция снимает предупреждение ---------------------------------------


async def test_rest_acceptance_by_another_participant_clears_the_warning(
    auth_client: AsyncClient, db_session: AsyncSession, agent_actor: Actor, project: Project
) -> None:
    task = await working(db_session, agent_actor, project, "Примут")
    await close_mixed(db_session, agent_actor, task)
    bootstrap_before = await auth_client.get("/api/v1/bootstrap")

    accepted = await file_acceptance(auth_client, task.key)

    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["data"]["type"] == "acceptance"
    assert accepted.json()["data"]["author"]["signature"] == "owner"
    assert (await features(auth_client, task.key))["open_warnings"] == 0
    assert await found(auth_client, "open_warnings: > 0") == []
    assert bootstrap_before.json()["data"]["open_warnings"] == 1
    assert (await auth_client.get("/api/v1/bootstrap")).json()["data"]["open_warnings"] == 0


async def test_rest_acceptance_without_open_warning_is_refused(
    auth_client: AsyncClient, db_session: AsyncSession, agent_actor: Actor, project: Project
) -> None:
    """Нечего принимать: ни предупреждения, ни открытого — после принятия."""
    never = await working(db_session, agent_actor, project, "Без предупреждения")
    accepted_once = await working(db_session, agent_actor, project, "Уже принято")
    await close_mixed(db_session, agent_actor, accepted_once)
    first = await file_acceptance(auth_client, accepted_once.key)
    before = len(await entries(auth_client, never.key))

    refused = await file_acceptance(auth_client, never.key)
    again = await file_acceptance(auth_client, accepted_once.key)

    assert first.status_code == 201, first.text
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "warning_not_open"
    assert refused.json()["error"]["details"] == {"key": never.key}
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "warning_not_open"
    assert again.json()["error"]["details"]["reaction_no"] == first.json()["data"]["no"]
    assert len(await entries(auth_client, never.key)) == before


async def test_mcp_acceptance_by_the_closer_is_refused(
    mcp_session: Connect,
    agent_secret: str,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    agent_actor: Actor,
    project: Project,
) -> None:
    """Исполнитель своё предупреждение не снимает: контроль остаётся за стороной."""
    task = await working(db_session, agent_actor, project, "Принимает закрывший")
    await close_mixed(db_session, agent_actor, task)
    key = task.key
    before = len(await entries(auth_client, key))

    async with mcp_session(agent_secret) as session:
        failure = await refuse(
            session,
            "add_entry",
            key=key,
            type="acceptance",
            title="Принимаю сам",
        )

    assert "acceptance_by_closer" in failure
    assert len(await entries(auth_client, key)) == before
    assert (await features(auth_client, key))["open_warnings"] == 1


async def test_mcp_acceptance_by_another_participant_clears_the_warning(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    agent_actor: Actor,
    project: Project,
) -> None:
    """MCP: `add_entry` с `acceptance` от человека снимает предупреждение."""
    task = await working(db_session, agent_actor, project, "Примут по MCP")
    await close_mixed(db_session, agent_actor, task)

    async with mcp_session(task_secret) as session:
        filed = await call(
            session, "add_entry", key=task.key, type="acceptance", title="Принято владельцем"
        )
        package = await call(session, "get_task", key=task.key)
        listed = await call(session, "search_tasks", query="open_warnings: > 0")
        refused = await refuse(
            session, "add_entry", key=task.key, type="acceptance", title="Ещё раз"
        )

    assert filed["title"] is None
    assert package["features"]["open_warnings"] == 0
    assert listed["items"] == []
    assert "warning_not_open" in refused


async def test_remark_after_the_warning_returns_the_task(
    auth_client: AsyncClient, db_session: AsyncSession, agent_actor: Actor, project: Project
) -> None:
    """Вернуть — замечанием: предупреждение снято, замечание ждёт разбора."""
    task = await working(db_session, agent_actor, project, "Вернут")
    await close_mixed(db_session, agent_actor, task)

    returned = await auth_client.post(
        f"/api/v1/tasks/{task.key}/entries",
        json={"type": "remark", "title": "Проверка 2 не принята: нужен Safari"},
    )

    assert returned.status_code == 201, returned.text
    after = await features(auth_client, task.key)
    assert after["open_warnings"] == 0
    assert after["open_remarks"] == 1
    assert await found(auth_client, "open_warnings: > 0") == []


async def test_remark_before_closing_does_not_clear_the_warning(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    agent_actor: Actor,
    main_actor: Actor,
    project: Project,
) -> None:
    """Реакция — только то, что подшито **после** предупреждения."""
    task = await working(db_session, agent_actor, project, "Замечание по ходу")
    await case_service.add_entry(
        db_session, task, actor=main_actor, type=EntryType.REMARK, title="По ходу работы"
    )
    await close_mixed(db_session, agent_actor, task)

    assert (await features(auth_client, task.key))["open_warnings"] == 1
    assert await found(auth_client, "open_warnings: > 0") == [task.key]


async def test_card_and_search_agree_on_open_warnings(
    db_session: AsyncSession, agent_actor: Actor, main_actor: Actor, project: Project
) -> None:
    """Питоновская форма (`open_warning` по описи) и подзапрос поиска — одно определение."""
    open_one = await working(db_session, agent_actor, project, "Открыто")
    accepted = await working(db_session, agent_actor, project, "Принято")
    returned = await working(db_session, agent_actor, project, "Возвращено")
    plain = await working(db_session, agent_actor, project, "Без предупреждения")
    for task in (open_one, accepted, returned):
        await close_mixed(db_session, agent_actor, task)
    await case_service.add_entry(
        db_session, accepted, actor=main_actor, type=EntryType.ACCEPTANCE, title="Принято"
    )
    await case_service.add_entry(
        db_session, returned, actor=main_actor, type=EntryType.REMARK, title="Вернуть"
    )

    expected = {open_one.key: 1, accepted.key: 0, returned.key: 0, plain.key: 0}
    for task in (open_one, accepted, returned, plain):
        package = await tasks_service.read_task_package(db_session, task.key, actor=main_actor)
        assert package.features.open_warnings == expected[task.key], task.key
        assert (open_warning(package.index) is not None) == bool(expected[task.key])
    count = await case_service.count_open_warnings(db_session)
    assert count == 1
