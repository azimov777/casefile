"""Инструменты MCP через настоящий клиент SDK.

Каждый инструмент проверяется вызовом по протоколу, а не вызовом функции: половина того,
что может сломаться, живёт не в теле инструмента. Это разбор аргументов по схеме, разбор
заголовка с токеном, промежуточные слои и свёртка результата — и всё это в тесте на
функцию не попадает вовсе.

## Что здесь проверяется помимо самих действий

- **Состав `tools/list` зависит от набора токена.** Список — не безопасность (отказ всё
  равно случится при вызове), а контекст модели: недоступный инструмент в списке это
  прочитанное зря описание и повод попробовать то, что не получится.
- **Отказ приходит тем же кодом, что и в REST.** Он и приходит оттуда же — из единой
  точки прав, а не из своей проверки в слое MCP.
- **Пакет преемника совпадает с ответом REST поле в поле.** Агент и человек обязаны
  видеть одну и ту же задачу: расхождение разбиралось бы как «почему агент решил иначе,
  чем показывал интерфейс», и упиралось бы в два разных ответа на один вопрос.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.db.models.task import Task
from app.mcp.arguments import DEFAULT_SEARCH_FIELDS
from app.services import queues as queues_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from conftest import Connect, call, refuse, tool_text

#: Инструменты набора `task` — ровно те, что перечислены в `CONCEPT.md`, 5.2.
TASK_TOOLS = {
    "get_task",
    "read_entries",
    "search_tasks",
    "create_task",
    "update_task",
    "transition",
    "add_summary",
    "add_entry",
    "ask",
    "answer",
    "add_verdict",
    "link",
    "unlink",
    "get_queue",
    "list_queues",
    "list_participants",
    "wait_journal",
}

#: Что набор `main` добавляет сверху. Выпуска токенов среди них нет намеренно.
MAIN_TOOLS = {"create_queue", "update_queue", "register_participant", "update_participant"}

#: Следующий шаг из двух строк: заголовок сводки — только первая из них. Строки
#: собираются соединением, а не одним литералом с `\n`: escape внутри русского текста
#: читается хуже, чем список строк.
NEXT_STEP_LINES = ("Перенести вызов последним шагом", "вторая строка")

#: Аргументы, с которыми инструмент набора `main` доходит до проверки прав. Значения
#: намеренно осмысленные: отказ должен приходить из прав, а не из разбора аргументов.
MAIN_TOOL_CALLS: dict[str, dict[str, Any]] = {
    "create_queue": {"key": "OPS", "title": "Эксплуатация"},
    "update_queue": {"key": "TRK", "title": "Другое название"},
    "register_participant": {"kind": "agent", "name": "nightly_bot"},
    "update_participant": {"name": "owner", "description": "Другое описание"},
}


@pytest.fixture
async def open_task(db_session: AsyncSession, task_actor: Actor, task: Task) -> Task:
    """Задача `TRK-1`, переведённая в `open`: с неё начинается рабочий цикл агента."""
    await tasks_service.transition_task(db_session, task, actor=task_actor, to="open")
    return task


# --- Состав набора --------------------------------------------------------------------


async def test_a_task_token_sees_exactly_the_working_cycle(
    mcp_session: Connect, task_secret: str
) -> None:
    """Обзорная проверка 1: семнадцать инструментов рабочего цикла и ни одного лишнего."""
    async with mcp_session(task_secret) as session:
        listed = {tool.name for tool in (await session.list_tools()).tools}

    assert listed == TASK_TOOLS


async def test_a_main_token_sees_the_registries_too(mcp_session: Connect, main_secret: str) -> None:
    """Обзорная проверка 1: набор `main` добавляет четыре инструмента реестров."""
    async with mcp_session(main_secret) as session:
        listed = {tool.name for tool in (await session.list_tools()).tools}

    assert listed == TASK_TOOLS | MAIN_TOOLS


async def test_every_main_tool_refuses_a_task_token_with_the_rest_code(
    mcp_session: Connect,
    task_secret: str,
    queue: Queue,
) -> None:
    """Обзорная проверка 2: недоступный инструмент отвечает `permission_denied`.

    Проверяются все четыре, а не только `create_queue`: объявленный набор инструмента —
    это описание списка, и разойтись с настоящими правами ему не даёт именно этот тест.
    """
    del queue
    async with mcp_session(task_secret) as session:
        for name, arguments in MAIN_TOOL_CALLS.items():
            failure = await refuse(session, name, **arguments)
            assert "permission_denied" in failure, f"{name}: {failure}"
            assert "required_scope" in failure


async def test_an_unknown_token_is_refused_before_the_list_is_built(
    mcp_session: Connect,
) -> None:
    """Неизвестный токен получает отказ, а не пустой список.

    Пустой список неотличим от сервера без инструментов, и агент искал бы поломку не там.
    """
    async with mcp_session("trk_unknown") as session:
        with pytest.raises(Exception) as failure:
            await session.list_tools()

    assert "unauthorized" in str(failure.value)


# --- Чтение задачи --------------------------------------------------------------------


async def test_get_task_returns_the_same_package_as_rest(
    mcp_session: Connect,
    auth_client: AsyncClient,
    task_secret: str,
    open_task: Task,
) -> None:
    """Обзорная проверка 3: пакет преемника совпадает с ответом REST поле в поле."""
    async with mcp_session(task_secret) as session:
        await call(
            session,
            "add_summary",
            key=open_task.key,
            done="Прочитал дело",
            remaining="Починить выдачу номера",
            blockers="Ничего",
            next_step="Перенести вызов next_task_number в конец create_task",
        )
        from_mcp = await call(session, "get_task", key=open_task.key)

    response = await auth_client.get(f"/api/v1/tasks/{open_task.key}")
    assert response.status_code == 200, response.text

    assert from_mcp == response.json()["data"]


async def test_get_task_carries_the_index_and_the_allowed_transitions(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Вход в задачу: опись дела и переходы приезжают одним вызовом."""
    async with mcp_session(task_secret) as session:
        package = await call(session, "get_task", key=task.key)

    assert package["task"]["key"] == task.key
    assert [heading["type"] for heading in package["index"]] == ["created"]
    assert package["transitions"] == ["open", "cancelled"]
    assert package["features"] == {
        "blocked": False,
        "open_questions": 0,
        "open_blocking_questions": 0,
        "last_summary_at": None,
    }


async def test_read_entries_filters_the_case_the_same_way_rest_does(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Тела записей читаются точечно: по номерам, по типу, после номера."""
    async with mcp_session(task_secret) as session:
        await call(
            session,
            "add_entry",
            key=open_task.key,
            type="finding",
            title="Номер выдаётся до валидации",
            body="Вызов стоит первым в `create_task`",
        )
        by_type = await call(session, "read_entries", key=open_task.key, types=["finding"])
        after = await call(session, "read_entries", key=open_task.key, after_no=1)

    assert [item["title"] for item in by_type["items"]] == ["Номер выдаётся до валидации"]
    assert by_type["items"][0]["body"] == "Вызов стоит первым в `create_task`"
    assert [item["type"] for item in after["items"]] == ["status_changed", "finding"]
    assert by_type["next_cursor"] is None


# --- Отбор ----------------------------------------------------------------------------


async def test_search_tasks_asks_for_a_narrow_set_of_fields_by_default(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Полная задача с пятью разделами съела бы контекст ровно там, где агент выбирает."""
    async with mcp_session(task_secret) as session:
        found = await call(session, "search_tasks", queue=["TRK"])

    assert [item["key"] for item in found["items"]] == [task.key]
    assert set(found["items"][0]) == set(DEFAULT_SEARCH_FIELDS)


async def test_search_tasks_understands_the_query_language_and_the_arguments_alike(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Строка и аргументы — один путь исполнения, а не две похожие реализации."""
    async with mcp_session(task_secret) as session:
        by_query = await call(
            session,
            "search_tasks",
            query="queue: TRK and status: open and blocked: false and open_blocking_questions: 0",
        )
        by_arguments = await call(
            session,
            "search_tasks",
            queue=["TRK"],
            status=["open"],
            blocked=False,
            open_blocking_questions=0,
        )
        empty_assignee = await call(session, "search_tasks", assignee=["empty()"])

    assert by_query == by_arguments
    assert [item["key"] for item in by_query["items"]] == [open_task.key]
    assert open_task.key in [item["key"] for item in empty_assignee["items"]]


async def test_search_tasks_returns_the_same_rows_as_rest(
    mcp_session: Connect,
    auth_client: AsyncClient,
    task_secret: str,
    open_task: Task,
) -> None:
    """Проверка 3 задачи 32: строка выдачи MCP совпадает с REST поле в поле.

    Признаки в строке — самое лёгкое место разойтись: их сериализуют два разных слоя
    (`app/mcp/views.py` и `app/api/schemas/search.py`), а считает один запрос. Пока
    сравнение зелёное, агент и человек выбирают задачу по одним и тем же числам.
    """
    fields = ["title", "status", "features"]
    async with mcp_session(task_secret) as session:
        from_mcp = await call(session, "search_tasks", queue=["TRK"], fields=fields)

    response = await auth_client.get("/api/v1/tasks", params={"queue": "TRK", "fields": fields})
    assert response.status_code == 200, response.text

    assert from_mcp["items"] == response.json()["data"]
    assert from_mcp["items"][0]["features"] == {
        "blocked": False,
        "open_questions": 0,
        "open_blocking_questions": 0,
        "last_summary_at": None,
    }


async def test_search_tasks_clips_a_long_text_and_says_so(
    mcp_session: Connect,
    db_session: AsyncSession,
    task_actor: Actor,
    task: Task,
    task_secret: str,
) -> None:
    """Обрезка объявлена рядом со значением: полный текст — один вызов `get_task`."""
    long_goal = "ц" * 5000
    await tasks_service.update_task(
        db_session, task, actor=task_actor, changes=tasks_service.TaskChanges(goal=long_goal)
    )

    async with mcp_session(task_secret) as session:
        found = await call(session, "search_tasks", queue=["TRK"], fields=["goal"])
        whole = await call(session, "get_task", key=task.key)

    item = found["items"][0]
    assert len(item["goal"]) == 2000
    assert item["goal_truncated"] is True
    assert item["goal_length"] == 5000
    assert whole["task"]["goal"] == long_goal


# --- Изменение задачи -----------------------------------------------------------------


async def test_update_task_touches_only_what_was_passed(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Обзорная проверка 5: теги не трогают исполнителя, а `null` его снимает."""
    async with mcp_session(task_secret) as session:
        assigned = await call(
            session, "update_task", key=task.key, changes={"assignee": "release_bot"}
        )
        tagged = await call(session, "update_task", key=task.key, changes={"tags": ["x"]})
        cleared = await call(session, "update_task", key=task.key, changes={"assignee": None})

    assert assigned["assignee"] == "release_bot"
    assert tagged["assignee"] == "release_bot", "правка тегов сняла исполнителя"
    assert tagged["tags"] == ["x"]
    assert cleared["assignee"] is None
    assert cleared["tags"] == ["x"], "снятие исполнителя стёрло теги"


async def test_update_task_refuses_a_stale_version(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Устаревшая версия — отказ, а не тихая перезапись чужого изменения."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session, "update_task", key=task.key, changes={"tags": ["x"]}, version=99
        )

    assert "version_conflict" in failure


async def test_a_section_cannot_be_edited_outside_backlog(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Разделы неизменяемы от `open` и дальше: чтобы поправить, задача идёт в `backlog`."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session, "update_task", key=open_task.key, changes={"goal": "Другая цель"}
        )

    assert "task_field_locked" in failure


async def test_transition_walks_the_table_and_explains_a_refusal(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Выход из `in_progress` требует сводки — последняя защита от вежливого ухода."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        taken = await call(session, "transition", key=key, to="in_progress")
        failure = await refuse(session, "transition", key=key, to="review", reason="Готово")
        await call(
            session,
            "add_summary",
            key=key,
            done="Сделал",
            remaining="Ничего",
            blockers="Ничего",
            next_step="Проверить",
        )
        moved = await call(session, "transition", key=key, to="review")

    assert taken["status"] == "in_progress"
    assert "summary_required" in failure
    assert moved["status"] == "review"


async def test_a_step_back_without_a_reason_is_refused(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Шаг назад обязан объясниться: причина уезжает в дело записью `status_changed`."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        failure = await refuse(session, "transition", key=key, to="backlog")
        moved = await call(session, "transition", key=key, to="backlog", reason="Нужны уточнения")
        entries = await call(session, "read_entries", key=key, types=["status_changed"])

    assert "transition_reason_required" in failure
    assert moved["status"] == "backlog"
    assert entries["items"][-1]["payload"]["reason"] == "Нужны уточнения"


# --- Создание задачи ------------------------------------------------------------------


async def test_create_task_is_born_in_backlog_with_its_parent(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Декомпозиция одним вызовом: ребёнок рождается со ссылкой на родителя."""
    parent_key = task.key
    async with mcp_session(task_secret) as session:
        child = await call(
            session,
            "create_task",
            queue="trk",
            title="Выдать номера очередям",
            description="Счётчик номеров живёт в очереди",
            sections={
                "goal": "Номера не переиспользуются",
                "context": "Счётчик в `queues`",
                "constraints": "Схему не менять",
                "output": "Тест на счётчик",
                "checks": ["Два создания подряд дают разные номера"],
            },
            parent=parent_key,
        )
        package = await call(session, "get_task", key=child["key"])
        parent_package = await call(session, "get_task", key=parent_key)

    assert child["status"] == "backlog"
    assert child["queue"] == {"key": "TRK", "title": "Трекер"}
    # Вид связи называет роль **своей** задачи: у ребёнка это `child`, у родителя `parent`.
    assert [(item["kind"], item["other"]["key"]) for item in package["links"]] == [
        ("child", parent_key)
    ]
    assert [(item["kind"], item["other"]["key"]) for item in parent_package["links"]] == [
        ("parent", child["key"])
    ]


async def test_a_repeated_create_task_answers_with_the_first_task(
    mcp_session: Connect, task_secret: str, queue: Queue
) -> None:
    """Агент упал и повторил вызов: второй задачи не появляется, номер не тратится."""
    del queue
    key = str(uuid.uuid4())
    arguments: dict[str, Any] = {
        "queue": "TRK",
        "title": "Починить выдачу ключей",
        "description": "Ключ сгорает",
        "idempotency_key": key,
    }

    async with mcp_session(task_secret) as session:
        first = await call(session, "create_task", **arguments)
        again = await call(session, "create_task", **arguments)
        conflict = await refuse(session, "create_task", **{**arguments, "title": "Совсем другое"})
        found = await call(session, "search_tasks", queue=["TRK"])

    assert first == again
    assert "idempotency_key_reused" in conflict
    assert [item["key"] for item in found["items"]].count(first["key"]) == 1


# --- Дело -----------------------------------------------------------------------------


async def test_add_summary_names_the_empty_part(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Обзорная проверка 4: пустая часть сводки отвергается с именем поля.

    Именно с именем: по нему агент чинит вызов с первой попытки, а не подбором.
    """
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "add_summary",
            key=task.key,
            done="Сделал",
            remaining="Осталось",
            blockers="",
            next_step="Дальше",
        )

    assert "entry_fields_invalid" in failure
    assert '"field": "blockers"' in failure
    assert '"reason": "required"' in failure


async def test_a_summary_takes_its_title_from_the_next_step(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Заголовок сводки не принимается: опись и содержание не должны расходиться."""
    async with mcp_session(task_secret) as session:
        summary = await call(
            session,
            "add_summary",
            key=task.key,
            done="Разобрался",
            remaining="Дописать",
            blockers="Ничего",
            next_step="\n".join(NEXT_STEP_LINES),
        )

    assert summary["title"] == NEXT_STEP_LINES[0]
    assert summary["payload"]["blockers"] == "Ничего"


async def test_add_entry_refuses_a_service_type(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Служебную запись подшивает трекер: принять её снаружи значило бы подделать историю."""
    async with mcp_session(task_secret) as session:
        result = await session.call_tool(
            "add_entry", {"key": task.key, "type": "status_changed", "title": "Подделка"}
        )

    assert result.is_error, tool_text(result)


async def test_a_question_is_open_until_it_is_answered(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Вопрос — не отдельная сущность, а запись дела без ответа с её номером."""
    async with mcp_session(task_secret) as session:
        participants = await call(session, "list_participants")
        question = await call(
            session,
            "ask",
            key=task.key,
            addressees=["owner"],
            title="Какой ключ канонический?",
            blocking=True,
            body="Верхний или нижний регистр",
        )
        asked = await call(session, "get_task", key=task.key)
        await call(session, "answer", key=task.key, question_no=question["no"], body="Верхний")
        answered = await call(session, "get_task", key=task.key)

    assert [item["name"] for item in participants["items"]] == ["owner"]
    assert asked["features"]["open_blocking_questions"] == 1
    assert [item["no"] for item in asked["questions"]] == [question["no"]]
    assert answered["features"]["open_questions"] == 0
    assert answered["features"]["open_blocking_questions"] == 0
    assert answered["questions"] == []


async def test_asking_an_unknown_participant_is_refused(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Адресовать можно только участника реестра: временного агента адресовать нельзя."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "ask",
            key=task.key,
            addressees=["nobody"],
            title="Кому это?",
            blocking=False,
        )

    assert "unknown_participant" in failure


async def test_a_verdict_gates_the_move_to_done(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """`review → done` требует, чтобы последний вердикт по каждой проверке был `passed`."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        await call(session, "transition", key=key, to="in_progress")
        await call(
            session,
            "add_summary",
            key=key,
            done="Сделал",
            remaining="Ничего",
            blockers="Ничего",
            next_step="Проверить",
        )
        await call(session, "transition", key=key, to="review")
        failure = await refuse(session, "transition", key=key, to="done")
        await call(
            session,
            "add_verdict",
            key=key,
            check_no=1,
            outcome="passed",
            evidence="Прогон зелёный",
        )
        closed = await call(session, "transition", key=key, to="done")

    assert "checks_not_passed" in failure
    assert closed["status"] == "done"


# --- Связи ----------------------------------------------------------------------------


async def test_a_link_is_named_from_the_side_that_asks(
    mcp_session: Connect, task_secret: str, open_task: Task, queue: Queue
) -> None:
    """`blocks` у одной стороны — `blocked_by` у другой; строка при этом одна."""
    del queue
    key = open_task.key
    async with mcp_session(task_secret) as session:
        blocker = await call(
            session,
            "create_task",
            queue="TRK",
            title="Блокер",
            description="Пока не закрыт",
        )
        await call(session, "link", key=key, kind="blocked_by", other=blocker["key"])
        blocked = await call(session, "get_task", key=key)
        other_side = await call(session, "get_task", key=blocker["key"])
        refused = await refuse(session, "transition", key=key, to="in_progress")

        await call(session, "unlink", key=blocker["key"], kind="blocks", other=key)
        unlinked = await call(session, "get_task", key=key)

    assert [item["kind"] for item in blocked["links"]] == ["blocked_by"]
    assert [item["kind"] for item in other_side["links"]] == ["blocks"]
    assert blocked["features"]["blocked"] is True
    assert "task_blocked" in refused
    assert unlinked["links"] == []
    assert unlinked["features"]["blocked"] is False


async def test_a_link_to_itself_is_refused(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Связь задачи с самой собой не бывает ничем осмысленным."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(session, "link", key=task.key, kind="relates", other=task.key)

    assert "link_self_not_allowed" in failure


# --- Реестры --------------------------------------------------------------------------


async def test_get_queue_carries_the_context_shared_by_its_tasks(
    mcp_session: Connect, task_secret: str, queue: Queue
) -> None:
    """В карточке задачи только ключ и название: описание запрашивают отдельно."""
    async with mcp_session(task_secret) as session:
        read = await call(session, "get_queue", key="trk")

    assert read == {"key": queue.key, "title": queue.title, "description": queue.description}


async def test_list_queues_is_the_entry_point_when_no_key_is_known(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    main_actor: Actor,
    queue: Queue,
) -> None:
    """Агент без контекста репозитория находит очереди сам, а описание берёт у выбранной.

    Строка списка — ровно ключ и название: описание очереди бывает длинным, и в выдаче,
    где очередей много, оно стоило бы контекста больше, чем сам выбор.
    """
    del queue
    await queues_service.create_queue(
        db_session, actor=main_actor, key="UI", title="Интерфейс", description="Фронтенд"
    )

    async with mcp_session(task_secret) as session:
        listed = await call(session, "list_queues")
        first = await call(session, "list_queues", limit=1)
        second = await call(session, "list_queues", limit=1, cursor=first["next_cursor"])
        chosen = await call(session, "get_queue", key=first["items"][0]["key"])

    # Порядок страниц здесь не проверяется: очереди одного теста заведены в одной
    # транзакции, `created_at` у них общий, и пара `(created_at, id)` вырождается в
    # сортировку по случайным UUID (`docs/notes/testing.md`). Проверяется полнота
    # выдачи и то, что страницы не пересекаются.
    assert listed["next_cursor"] is None
    assert sorted(item["key"] for item in listed["items"]) == ["TRK", "UI"]
    assert all("description" not in item for item in listed["items"]), "описание в списке"
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None
    assert second["items"] != first["items"], "курсор повторил страницу"
    assert sorted(item["key"] for item in first["items"] + second["items"]) == ["TRK", "UI"]
    assert chosen["key"] == first["items"][0]["key"]
    assert chosen["description"], "описание отдаёт только get_queue"


async def test_the_main_scope_runs_the_registries(
    mcp_session: Connect, main_secret: str, queue: Queue
) -> None:
    """Очереди и участники заводятся из MCP; токены — нет, и не будут."""
    del queue
    async with mcp_session(main_secret) as session:
        created = await call(
            session, "create_queue", key="ops", title="Эксплуатация", description="Дежурства"
        )
        renamed = await call(session, "update_queue", key="OPS", title="Эксплуатация и дежурства")
        registered = await call(
            session,
            "register_participant",
            kind="agent",
            name="Release_Bot",
            description="Релизный бот",
        )
        described = await call(
            session, "update_participant", name="release_bot", description="Ведёт выкладки"
        )

    assert created["key"] == "OPS"
    assert renamed["title"] == "Эксплуатация и дежурства"
    assert renamed["description"] == "Дежурства", "правка названия стёрла описание"
    assert registered == {
        "kind": "agent",
        "name": "release_bot",
        "description": "Релизный бот",
    }
    assert described["description"] == "Ведёт выкладки"


async def test_a_shared_token_signs_its_entries_with_the_label(
    mcp_session: Connect, shared_secret: str, task: Task
) -> None:
    """Тот же заголовок, что и в REST: вторая схема представления проектом запрещена."""
    async with mcp_session(shared_secret, label="nightly_agent") as session:
        entry = await call(
            session,
            "add_entry",
            key=task.key,
            type="note",
            title="Ночной прогон прошёл",
        )

    assert entry["author"] == {"kind": "agent", "signature": "nightly_agent"}
