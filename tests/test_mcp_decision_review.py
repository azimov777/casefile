"""Проверка решений человеком (TRK-755), слой MCP (задача TRK-757).

Агент читает статусы `rejected` и `removed` как статусы решения без преемника, ссылка на такое
решение отклоняется отказом `decision_not_in_force`, а `review_state` и записи `decision_review`
в ответах MCP нет: проверку делает человек, и инструмента проверки у агента нет.

Обзорные проверки задачи, которые здесь измеряются:

- 1: `get_project(key="DEMO")` без отклонённого и удалённого решений демо и с подтверждённым;
  `read_project_entries(in_force=false)` отдаёт отклонённое со `status: rejected` и без
  `superseded_by`; `review_state` в ответах нет;
- 2: `add_project_entry(supersedes=[<отклонённое>])` и `update_task(decisions=[…])` — отказ
  `decision_not_in_force`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.demo import DEMO_PROJECT_KEY, seed_demo
from conftest import Connect, call, refuse

CONFIRMED = "Журнал записей только дополняется: запись не правится и не стирается"
REJECTED = "Лента отдаёт записи страницами по двести"
REMOVED = "Демо-данные пересеваются при каждом запуске"
REPLACED = "Лента отдаёт записи страницами по сто"


def _no(ref: str) -> int:
    return int(ref.rsplit("#", 1)[1])


async def test_get_project_leaves_out_withdrawn_decisions_and_read_returns_their_status(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession
) -> None:
    """Проверка 1: опись действующих решений демо несёт подтверждённое и не несёт отклонённого
    и удалённого; чтение с `in_force=false` отдаёт отклонённое и удалённое со статусом и без
    преемника, заменённое — с преемником; `review_state` и `decision_review` MCP не отдаёт."""
    await seed_demo(db_session)

    async with mcp_session(task_secret) as session:
        card = await call(session, "get_project", key=DEMO_PROJECT_KEY)
        out_of_force = await call(
            session, "read_project_entries", key=DEMO_PROJECT_KEY, in_force=False
        )
        everything = await call(session, "read_project_entries", key=DEMO_PROJECT_KEY, limit=200)

    titles = {line["title"] for line in card["decisions"]}
    assert CONFIRMED in titles
    assert not {REJECTED, REMOVED, REPLACED} & titles

    by_title = {item["title"]: item for item in out_of_force["items"]}
    assert set(by_title) >= {REJECTED, REMOVED, REPLACED}
    assert CONFIRMED not in by_title
    for title, status in ((REJECTED, "rejected"), (REMOVED, "removed")):
        assert by_title[title]["status"] == status
        assert by_title[title]["superseded_by"] is None
    assert by_title[REPLACED]["status"] == "superseded"
    assert by_title[REPLACED]["superseded_by"] == by_title[REJECTED]["no"]

    for item in [*out_of_force["items"], *everything["items"]]:
        assert "review_state" not in item
        assert "review_entry" not in item
    for line in card["decisions"]:
        assert set(line) == {"ref", "title"}


async def test_a_withdrawn_decision_cannot_be_superseded_or_cited(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession
) -> None:
    """Проверка 2: `add_project_entry(supersedes=[<отклонённое>])` и
    `update_task(changes={"decisions": [<отклонённое>]})` — отказ `decision_not_in_force`;
    то же для удалённого."""
    await seed_demo(db_session)

    async with mcp_session(task_secret) as session:
        listed = await call(session, "read_project_entries", key=DEMO_PROJECT_KEY, in_force=False)
        withdrawn = {
            item["status"]: item["no"]
            for item in listed["items"]
            if item["status"] in ("rejected", "removed")
        }
        assert set(withdrawn) == {"rejected", "removed"}
        task = await call(
            session,
            "create_task",
            project=DEMO_PROJECT_KEY,
            area=(await call(session, "get_project", key=DEMO_PROJECT_KEY))["areas"][0]["address"],
            title="Задача по снятому решению",
            description="Проверка ссылки",
        )

        for status, no in withdrawn.items():
            replaced = await refuse(
                session,
                "add_project_entry",
                key=DEMO_PROJECT_KEY,
                type="decision",
                title=f"Замена {status}",
                supersedes=[no],
            )
            assert "decision_not_in_force" in replaced
            assert status in replaced
            cited = await refuse(
                session,
                "update_task",
                key=task["key"],
                changes={"decisions": [f"{DEMO_PROJECT_KEY}#{no}"]},
            )
            assert "decision_not_in_force" in cited
            assert status in cited


async def test_the_agent_has_no_tool_to_review_a_decision(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession
) -> None:
    """Инструмента проверки нет, и `decision_review` не принимается как тип записи."""
    await seed_demo(db_session)
    async with mcp_session(task_secret) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert not {name for name in names if "review" in name}
        refused = await refuse(
            session,
            "add_project_entry",
            key=DEMO_PROJECT_KEY,
            type="decision_review",
            title="Decision TRK#1 confirmed",
        )
    assert "decision_review" in refused or "type" in refused
