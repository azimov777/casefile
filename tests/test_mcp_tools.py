"""Инструменты MCP: рабочий цикл агента.

Вызовы идут через `MCPServer.call_tool`, а не напрямую в функцию: так проверяется и
схема аргументов (её агент видит первой), и то, что результат сворачивается в
структурированный ответ. Ошибка инструмента приезжает исключением `ToolError` — по
проводу это `is_error: true` с тем же текстом.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.event import OutboxEvent
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.mcp import views
from app.services import comments as comments_service
from app.services import issues as issues_service
from app.services import notifications as notifications_service
from app.services.event_bus import EventEnvelope

type Call = Callable[..., Awaitable[dict[str, Any]]]
type MakeIssue = Callable[..., Awaitable[Issue]]


async def test_a_call_without_a_token_says_which_header_is_missing(mcp_server: Any) -> None:
    """Отсутствие заголовка — обычный `unauthorized` с подсказкой, а не сбой протокола."""
    with pytest.raises(ToolError) as failure:
        await mcp_server.call_tool("list_queues", {})

    assert "unauthorized" in str(failure.value)
    assert "Authorization: Bearer" in str(failure.value)


async def test_search_returns_the_brief_field_set_by_default(
    mcp_call: Call,
    queue: Queue,
    make_issue: MakeIssue,
) -> None:
    """Умолчание поиска — краткий набор: сто задач со всеми полями съели бы контекст."""
    await make_issue(summary="Первая задача")

    page = await mcp_call("search_issues", query="queue: TRK")

    assert page["has_more"] is False
    assert len(page["items"]) == 1
    assert set(page["items"][0]) == set(views.BRIEF_FIELDS)


async def test_search_can_ask_for_named_fields_and_for_everything(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """`fields` работает так же, как в REST, а звёздочка означает «задачу целиком»."""
    await make_issue()

    narrow = await mcp_call("search_issues", query="queue: TRK", fields=["summary"])
    whole = await mcp_call("search_issues", query="queue: TRK", fields=["*"])

    assert set(narrow["items"][0]) == {"key", "summary"}
    assert "description" in whole["items"][0]
    assert "values" in whole["items"][0]


async def test_a_broken_query_reports_the_character_position(mcp_call: Call) -> None:
    """Позиция и причина доносятся до агента целиком: по ним запрос чинится за раз."""
    with pytest.raises(ToolError) as failure:
        await mcp_call("search_issues", query="queue: TRK and")

    message = str(failure.value)
    assert "invalid_search_query" in message
    assert "position" in message


async def test_reading_an_issue_has_three_levels_of_detail(
    mcp_call: Call,
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
) -> None:
    """Кратко, полностью, с историей и обсуждением — три разных объёма ответа."""
    issue = await make_issue(description="Описание задачи")
    await comments_service.add_comment(db_session, issue, initiator=owner, body="Взял в работу")

    brief = await mcp_call("get_issue", issue=issue.key)
    full = await mcp_call("get_issue", issue=issue.key, detail="full")
    history = await mcp_call("get_issue", issue=issue.key, detail="history")

    assert set(brief) == set(views.BRIEF_FIELDS)
    assert full["description"] == "Описание задачи"
    assert "changelog" not in full
    assert [entry["event"] for entry in history["changelog"]["items"]] == [
        "issue.created",
        "comment.created",
    ]
    assert [item["body"] for item in history["comments"]["items"]] == ["Взял в работу"]


async def test_a_long_description_is_clipped_and_says_so(
    mcp_call: Call,
    make_issue: MakeIssue,
    settings: Any,
) -> None:
    """Молчаливая обрезка хуже отсутствия текста: агент принял бы обрывок за целое."""
    issue = await make_issue(description="я" * (settings.mcp_text_limit + 50))

    payload = await mcp_call("get_issue", issue=issue.key, detail="full")

    assert len(payload["description"]) == settings.mcp_text_limit
    assert payload["description_truncated"] is True
    assert payload["description_length"] == settings.mcp_text_limit + 50


async def test_creating_an_issue_takes_the_queue_defaults(mcp_call: Call, queue: Queue) -> None:
    """Ключ выдаёт очередь, тип и статус берутся из её настроек."""
    created = await mcp_call("create_issue", queue="TRK", summary="Завести MCP-сервер")

    assert created["key"] == "TRK-1"
    assert created["status"] == "open"
    assert created["author"] == "owner"


async def test_update_touches_only_the_fields_that_were_sent(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Правка названия не должна снимать исполнителя — ради этого и различают `null`."""
    issue = await make_issue()
    await mcp_call("assign_issue", issue=issue.key, assignee="owner")

    updated = await mcp_call("update_issue", issue=issue.key, changes={"summary": "Новое название"})

    assert updated["summary"] == "Новое название"
    assert updated["assignee"] == "owner"
    assert updated["changed_fields"] == ["summary"]


async def test_null_clears_the_assignee_and_is_told_apart_from_omission(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """`null` осмыслен ровно у полей, которые можно очистить."""
    issue = await make_issue()
    await mcp_call("assign_issue", issue=issue.key, assignee="owner")

    updated = await mcp_call("update_issue", issue=issue.key, changes={"assignee": None})

    assert updated["assignee"] is None


async def test_a_stale_version_is_a_conflict_and_not_a_silent_overwrite(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Версия — условие, а не поле: чужая правка обязана стать отказом."""
    issue = await make_issue()
    await mcp_call("update_issue", issue=issue.key, changes={"summary": "Первое"})

    with pytest.raises(ToolError) as failure:
        await mcp_call("update_issue", issue=issue.key, changes={"summary": "Второе"}, version=1)

    assert "version_conflict" in str(failure.value)


async def test_a_transition_is_picked_from_the_list_and_carries_the_version(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Смена статуса идёт переходом: список отдаёт и идентификатор, и версию задачи."""
    issue = await make_issue()

    available = await mcp_call("list_transitions", issue=issue.key)
    forward = next(item for item in available["transitions"] if item["to_status"] == "in_progress")
    moved = await mcp_call(
        "transition_issue",
        issue=issue.key,
        transition=forward["id"],
        version=available["version"],
    )

    assert moved["status"] == "in_progress"
    assert forward["is_available"] is True


async def test_closing_without_a_resolution_is_refused_with_its_reason(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Отказ процесса — работающий процесс, и причина должна дойти до агента.

    Закрывающий переход в процессе по умолчанию идёт из «в работе», поэтому задача
    сначала переводится туда: проверять надо отказ по резолюции, а не отсутствие ребра.
    """
    issue = await make_issue()
    available = await mcp_call("list_transitions", issue=issue.key)
    forward = next(item for item in available["transitions"] if item["to_status"] == "in_progress")
    await mcp_call("transition_issue", issue=issue.key, transition=forward["id"])
    available = await mcp_call("list_transitions", issue=issue.key)
    closing = next(item for item in available["transitions"] if item["requires_resolution"])

    with pytest.raises(ToolError) as failure:
        await mcp_call("transition_issue", issue=issue.key, transition=closing["id"])

    assert "issue_resolution_required" in str(failure.value)


async def test_a_comment_is_posted_as_the_actor_behind_the_token(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Комментарий пишется от имени актора токена, упоминания разбираются при сохранении."""
    issue = await make_issue()

    posted = await mcp_call("add_comment", issue=issue.key, body="Готово, @owner")
    feed = await mcp_call("list_comments", issue=issue.key)

    assert posted["author"] == "owner"
    assert posted["mentions"] == ["owner"]
    assert [item["id"] for item in feed["items"]] == [posted["id"]]


async def test_a_checklist_item_moves_by_naming_its_neighbour(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Место задаётся соседом; позиций наружу нет вовсе."""
    issue = await make_issue()
    first = await mcp_call("add_checklist_item", issue=issue.key, text="Первый")
    second = await mcp_call("add_checklist_item", issue=issue.key, text="Второй")

    moved = await mcp_call("move_checklist_item", issue=issue.key, item=second["id"], after=None)

    assert [item["id"] for item in moved["items"]] == [second["id"], first["id"]]
    assert "position" not in moved["items"][0]


async def test_a_checklist_item_can_be_checked_and_cleared(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Отметка о выполнении — свой инструмент: у неё своё событие."""
    issue = await make_issue()
    item = await mcp_call("add_checklist_item", issue=issue.key, text="Проверить")

    done = await mcp_call("check_checklist_item", issue=issue.key, item=item["id"])
    undone = await mcp_call("check_checklist_item", issue=issue.key, item=item["id"], is_done=False)

    assert done["is_done"] is True
    assert undone["is_done"] is False


async def test_a_link_is_named_the_way_the_asking_issue_sees_it(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Одна строка, два имени: `depends_on` у источника и `blocks` у цели."""
    first = await make_issue(summary="Зависимая")
    second = await make_issue(summary="Блокирующая")

    await mcp_call("link_issues", issue=first.key, link_type="depends_on", other=second.key)
    from_target = await mcp_call("list_links", issue=second.key)

    assert from_target["items"][0]["type"] == "blocks"
    assert from_target["items"][0]["issue"] == first.key


async def test_a_subtask_tree_marks_the_branches_it_could_not_fit(
    mcp_call: Call,
    make_issue: MakeIssue,
) -> None:
    """Обрезанное дерево обязано отличаться от полного."""
    parent = await make_issue(summary="Эпик работ")
    child = await make_issue(summary="Подзадача")
    grandchild = await make_issue(summary="Внучатая задача")
    await mcp_call("link_issues", issue=child.key, link_type="subtask_of", other=parent.key)
    await mcp_call("link_issues", issue=grandchild.key, link_type="subtask_of", other=child.key)

    tree = await mcp_call("get_issue_tree", issue=parent.key, depth=1)

    assert tree["children"][0]["key"] == child.key
    assert tree["children"][0]["has_more_children"] is True


async def test_queue_config_lists_what_an_issue_can_be_filled_with(
    mcp_call: Call,
    queue: Queue,
) -> None:
    """Один вызов вместо четырёх: типы, статусы, резолюции, поля и графы процессов."""
    config = await mcp_call("get_queue_config", queue="TRK")

    assert config["queue"]["key"] == "TRK"
    assert {"open", "in_progress", "closed"} <= {item["ref"] for item in config["statuses"]}
    assert config["workflows"]
    assert config["workflows"][0]["initial_status"] == "open"


async def test_the_project_issue_list_is_the_search_with_a_condition(
    mcp_call: Call,
    make_project: Callable[..., Awaitable[Any]],
    make_issue: MakeIssue,
) -> None:
    """Отдельного инструмента «задачи проекта» нет: это поиск со строкой `project:`."""
    project = await make_project()
    issue = await make_issue()
    await mcp_call("add_issues_to_project", project=project.key, issues=[issue.key])

    card = await mcp_call("get_project", project=project.key)
    found = await mcp_call("search_issues", query=f"project: {project.key}")

    assert card["progress"] == {"total": 1, "done": 0, "ratio": 0.0}
    assert [item["key"] for item in found["items"]] == [issue.key]


async def test_the_inbox_is_read_and_marked_by_the_same_actor(
    mcp_call: Call,
    db_session: AsyncSession,
    system_actor: Actor,
    owner: Actor,
    make_issue: MakeIssue,
) -> None:
    """Лента и отметка — одна очередь работы: прочитанное не приходит повторно."""
    issue = await make_issue()
    await comments_service.add_comment(
        db_session, issue, initiator=system_actor, body="@owner посмотри"
    )
    await _deliver_events(db_session)

    inbox = await mcp_call("list_notifications")
    marked = await mcp_call("mark_notifications_read")
    after = await mcp_call("list_notifications")

    assert inbox["items"], "инбокс владельца обязан получить упоминание"
    assert marked["marked"] == len(inbox["items"])
    assert after["items"] == []
    assert after["unread"] == 0


async def test_waiting_ends_by_timeout_with_an_empty_result(mcp_call: Call) -> None:
    """Пустой ответ по таймауту — не ошибка: агент отличает его по `timed_out`."""
    outcome = await mcp_call("wait_for_notifications", timeout=0.05)

    assert outcome["notifications"] == []
    assert outcome["timed_out"] is True
    assert outcome["waited"] >= 0


async def test_a_timeout_beyond_the_ceiling_is_rejected(mcp_call: Call, settings: Any) -> None:
    """Потолок ожидания — настройка установки, и выход за него не срезается молча."""
    with pytest.raises(ToolError) as failure:
        await mcp_call("wait_for_notifications", timeout=settings.notification_wait_max_timeout + 1)

    assert "invalid_wait_timeout" in str(failure.value)


async def _deliver_events(session: AsyncSession) -> None:
    """Раскладывает события outbox по инбоксам — то, что в контуре делает воркер.

    Конверт собирается из строки outbox, а не пишется руками: иначе тест проверял бы
    адресацию по выдуманной нагрузке. Тот же приём, что в `tests/test_notifications_service.py`.
    """
    statement = select(OutboxEvent).order_by(OutboxEvent.created_at, OutboxEvent.id)
    events = (await session.scalars(statement)).unique().all()
    for event in events:
        await notifications_service.dispatch_event(
            session,
            EventEnvelope(
                id=event.id,
                event_type=event.event_type,
                object_type=event.object_type,
                object_id=event.object_id,
                object_key=event.object_key,
                actor_key=event.actor_key,
                payload=dict(event.payload),
                created_at=event.created_at,
            ),
        )


async def test_a_macro_failure_comes_back_as_a_journal_entry(
    mcp_call: Call,
    db_session: AsyncSession,
    owner: Actor,
    make_issue: MakeIssue,
    enable_rule: Callable[..., Awaitable[Any]],
) -> None:
    """Ошибка внутри правила — результат, а не сбой вызова: журнал обязан сохраниться."""
    await enable_rule("prepare_release")
    issue = await make_issue()

    outcome = await mcp_call("run_macro", rule="prepare_release", issue=issue.key)

    assert outcome["rule"] == "prepare_release"
    assert outcome["issue"] == issue.key
    assert outcome["status"] in {"success", "skipped", "failed"}


async def test_moving_a_card_between_columns_reports_the_process_refusal(
    mcp_call: Call,
    make_board: Callable[..., Awaitable[Any]],
    resolve_status: Callable[[str], Awaitable[Any]],
    make_issue: MakeIssue,
    db_session: AsyncSession,
    owner: Actor,
) -> None:
    """Перенос карточки — переход воркфлоу, и он может законно отказать."""
    from app.services import boards as boards_service

    board = await make_board(
        columns=[
            boards_service.ColumnDraft(name="Открытые", statuses=[await resolve_status("open")]),
            boards_service.ColumnDraft(name="Готово", statuses=[await resolve_status("closed")]),
        ]
    )
    issue = await make_issue()
    done_column = board.columns[1]

    with pytest.raises(ToolError) as failure:
        await mcp_call(
            "move_card_to_column",
            board=str(board.id),
            column=str(done_column.id),
            issue=issue.key,
        )

    # Из «открыто» в «закрыто» ребра в процессе по умолчанию нет, и доска не имеет
    # права дожать смену статуса другим путём: причина уезжает агенту как есть.
    assert "transition_not_allowed" in str(failure.value)
    assert "transition_missing" in str(failure.value)


async def test_the_whole_cycle_of_an_agent_goes_through_the_tools(
    mcp_call: Call,
    db_session: AsyncSession,
    system_actor: Actor,
    queue: Queue,
) -> None:
    """Полный цикл: нашёл → прочитал → прокомментировал → сменил статус → узнал о чужом.

    Проверка ради сценария целиком, а не ради каждого шага по отдельности: именно так
    задача 16 описывает готовность, и разваливается такой цикл обычно на стыках.
    """
    created = await mcp_call("create_issue", queue="TRK", summary="Собрать релиз", assignee="owner")

    found = await mcp_call("search_issues", query="assignee: me() and status_category: != done")
    assert [item["key"] for item in found["items"]] == [created["key"]]

    read = await mcp_call("get_issue", issue=created["key"], detail="full")
    assert read["assignee"] == "owner"

    await mcp_call("add_comment", issue=created["key"], body="Начинаю")

    available = await mcp_call("list_transitions", issue=created["key"])
    forward = next(item for item in available["transitions"] if item["to_status"] == "in_progress")
    moved = await mcp_call(
        "transition_issue",
        issue=created["key"],
        transition=forward["id"],
        version=available["version"],
    )
    assert moved["status"] == "in_progress"

    # Чужое изменение: комментарий системного актора по задаче владельца.
    issue = await issues_service.get_issue_by_key(db_session, created["key"])
    await comments_service.add_comment(
        db_session, issue, initiator=system_actor, body="Проверил, годится"
    )
    await _deliver_events(db_session)

    inbox = await mcp_call("list_notifications")
    assert [item["event_type"] for item in inbox["items"]] == ["comment.created"]
    assert inbox["items"][0]["issue"] == created["key"]
