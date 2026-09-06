"""Эндпоинт `GET /api/v1/tasks`: обзорные проверки задачи 25 через HTTP.

Тот же отбор проверен на сценарии; здесь важно другое — что параметры запроса доезжают
до него без потерь, ошибка приходит в единой оболочке с позицией, а выбор полей
действительно сокращает ответ.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import TaskSearchRead
from app.api.schemas.tasks import TaskFeaturesRead, TaskRead
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.links import LinkKind
from app.domain.search import FEATURES_FIELD, SELECTABLE_FIELDS
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import links as links_service
from app.services import tasks as tasks_service
from app.services.auth import Actor

CANDIDATES = "queue: TRK and status: open and blocked: false and open_blocking_questions: 0"


async def make(session: AsyncSession, actor: Actor, queue: Queue, title: str, **rest: Any) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        queue=queue,
        title=title,
        description=rest.pop("description", "описание"),
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
        **rest,
    )


async def listed(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    """Данные страницы. Оболочка проверяется здесь же: она одна на весь API."""
    response = await client.get("/api/v1/tasks", params=params)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert set(body["meta"]) == {"next_cursor", "has_more"}
    return body["data"]


async def listed_keys(client: AsyncClient, **params: Any) -> list[str]:
    return [item["key"] for item in await listed(client, **params)]


@pytest.fixture
async def board(db_session: AsyncSession, task_actor: Actor, queue: Queue) -> dict[str, Task]:
    """Обычная открытая задача, заблокированная и открытая с блокирующим вопросом."""
    plain = await make(db_session, task_actor, queue, "обычная", tags=["backend", "ui"])
    plain = (
        await tasks_service.transition_task(db_session, plain, actor=task_actor, to=TaskStatus.OPEN)
    ).task

    blocked = await make(db_session, task_actor, queue, "заблокированная")
    blocker = await make(db_session, task_actor, queue, "блокер")
    await links_service.add_link(
        db_session, blocked, blocker, actor=task_actor, kind=LinkKind.BLOCKED_BY
    )
    blocked = (
        await tasks_service.transition_task(
            db_session, blocked, actor=task_actor, to=TaskStatus.OPEN
        )
    ).task

    asking = await make(db_session, task_actor, queue, "вопрос без ответа")
    asking = (
        await tasks_service.transition_task(
            db_session, asking, actor=task_actor, to=TaskStatus.OPEN
        )
    ).task
    await case_service.ask(
        db_session,
        asking,
        actor=task_actor,
        addressees=["owner"],
        title="Каким способом чинить?",
        blocking=True,
    )
    return {"plain": plain, "blocked": blocked, "blocker": blocker, "asking": asking}


# --- Обзорные проверки -------------------------------------------------------------------


async def test_the_candidates_query_returns_only_what_can_be_taken(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Проверка 1: запрос назначателя одной строкой."""
    assert await listed_keys(auth_client, query=CANDIDATES) == [board["plain"].key]


async def test_the_structured_filter_returns_the_same_list_in_the_same_order(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Проверка 2: те же условия параметрами дают тот же список в том же порядке."""
    by_query = await listed_keys(auth_client, query=CANDIDATES)
    by_filter = await listed_keys(
        auth_client,
        queue="TRK",
        status="open",
        blocked="false",
        open_blocking_questions=0,
    )

    assert by_query == by_filter == [board["plain"].key]


async def test_a_typo_in_a_value_answers_with_the_position_and_the_allowed_values(
    auth_client: AsyncClient,
) -> None:
    """Проверка 3: `status: opne` — `422` с позицией и перечнем значений."""
    response = await auth_client.get("/api/v1/tasks", params={"query": "status: opne"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "search_value_invalid"
    assert error["details"]["position"] == 8
    assert "open" in error["details"]["allowed"]


async def test_an_insertion_between_pages_neither_duplicates_nor_loses_tasks(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Проверка 4: страницы устойчивы к вставке — курсор задан значением, а не смещением."""
    before = [await make(db_session, task_actor, queue, f"задача {number}") for number in range(6)]

    first = await auth_client.get("/api/v1/tasks", params={"limit": 3})
    assert first.status_code == 200
    await make(db_session, task_actor, queue, "вставленная посреди обхода")
    second = await auth_client.get(
        "/api/v1/tasks", params={"limit": 3, "cursor": first.json()["meta"]["next_cursor"]}
    )
    assert second.status_code == 200

    seen = [item["key"] for item in first.json()["data"] + second.json()["data"]]
    assert seen == [task.key for task in before]
    assert len(seen) == len(set(seen))


async def test_selected_fields_shrink_the_answer_to_exactly_what_was_asked(
    auth_client: AsyncClient, task: Task
) -> None:
    """Проверка 5: `fields=title,status` отдаёт только `key`, `title` и `status`.

    Непрошенные поля не приезжают ни как `null`, ни как значение по умолчанию: иначе
    экономии контекста, ради которой параметр и заведён, не было бы.
    """
    items = await listed(auth_client, fields="title,status")

    assert items == [{"key": task.key, "title": task.title, "status": task.status.value}]


async def test_an_unknown_field_answers_with_the_list_of_allowed_ones(
    auth_client: AsyncClient,
) -> None:
    """Проверка 6: `deadline: today` — `422` с перечнем полей отбора."""
    response = await auth_client.get("/api/v1/tasks", params={"query": "deadline: today"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "search_field_unknown"
    assert error["details"]["field"] == "deadline"
    assert "open_blocking_questions" in error["details"]["allowed"]


async def test_a_tag_is_found_among_several(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Проверка 7: метка находится в задаче с несколькими метками."""
    assert await listed_keys(auth_client, tags="backend") == [board["plain"].key]
    assert await listed_keys(auth_client, query="tags: ui") == [board["plain"].key]


# --- Прочее ------------------------------------------------------------------------------


async def test_the_list_without_parameters_returns_every_task(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Запрос без условий — законный: это «все задачи» по ключу."""
    found = await listed_keys(auth_client)

    assert found == sorted(task.key for task in board.values())


async def test_a_repeated_parameter_accepts_any_of_the_values(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Значения одного параметра складываются по `or`, параметры между собой — по `and`."""
    found = await listed_keys(auth_client, status=["open", "backlog"], queue="TRK")

    assert set(found) == {task.key for task in board.values()}


async def test_the_empty_marker_travels_through_a_structural_parameter(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """`?assignee=empty()` разбирается той же грамматикой, что и значение языка."""
    await make(db_session, task_actor, queue, "назначенная", assignee="release_bot")
    nobody = await make(db_session, task_actor, queue, "ничья")

    assert await listed_keys(auth_client, assignee="empty()") == [nobody.key]


async def test_sorting_is_explicit_in_direction(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    for number in range(3):
        await make(db_session, task_actor, queue, f"задача {number}")

    ascending = await listed_keys(auth_client, sort="key")
    descending = await listed_keys(auth_client, sort="-key")

    assert descending == list(reversed(ascending))


async def test_an_unknown_sort_key_answers_with_the_allowed_ones(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get("/api/v1/tasks", params={"sort": "created_at"})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["allowed"] == [
        "key",
        "last_entry_at",
        "priority",
        "updated_at",
    ]


async def test_a_broken_cursor_is_a_named_error_and_not_a_five_hundred(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get("/api/v1/tasks", params={"cursor": "не-курсор"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_the_search_answer_carries_the_same_fields_as_the_task_card() -> None:
    """Два представления одной задачи в одном API — то, чего проект не допускает.

    Поле, добавленное в карточку и забытое здесь, приезжало бы из списка и из чтения
    по-разному, и фронтенд узнал бы об этом на своей стороне.

    Строка списка шире карточки ровно на `features`: в чтении признаки лежат рядом с
    карточкой, в пакете преемника (`TaskPackageRead.features`), и объект у них один и тот
    же — `TaskFeaturesRead`. Второго представления признаков от этого не появляется.
    """
    assert set(TaskSearchRead.model_fields) == set(TaskRead.model_fields) | {FEATURES_FIELD}
    assert TaskSearchRead.model_fields[FEATURES_FIELD].annotation == TaskFeaturesRead | None


async def test_every_row_carries_the_features_of_its_own_card(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Проверка 1 задачи 32: признаки строки списка равны признакам карточки.

    Считаны они разными путями — подзапросом по каждой строке и чистой функцией над
    прочитанным делом, — и сойтись обязаны на каждой задаче. Пока проверка зелёная, две
    формы одного определения не разъехались.
    """
    rows = {item["key"]: item["features"] for item in await listed(auth_client, query="queue: TRK")}

    assert set(rows) == {task.key for task in board.values()}
    for key, features in rows.items():
        assert set(features) == {
            "blocked",
            "open_questions",
            "open_blocking_questions",
            "open_remarks",
            "last_summary_at",
            "last_entry_at",
        }
        card = await auth_client.get(f"/api/v1/tasks/{key}")
        assert card.status_code == 200, card.text
        assert features == card.json()["data"]["features"]

    # Признак, всегда отвечающий одно и то же, совпал бы с карточкой и ничего не значил:
    # в расстановке есть и заблокированная задача, и задача с блокирующим вопросом.
    assert rows[board["blocked"].key]["blocked"] is True
    assert rows[board["plain"].key]["blocked"] is False
    assert rows[board["asking"].key]["open_blocking_questions"] == 1


async def test_the_features_are_picked_as_a_whole_and_a_single_one_is_refused(
    auth_client: AsyncClient, task: Task
) -> None:
    """Проверка 2 задачи 32: `features` выбирается именем, а `blocked` в `fields` — нет.

    `blocked` остаётся именем **условия отбора**: разреши его ещё и в `fields`, и одно
    слово значило бы в запросе два разных, а список допустимых значений в отказе перестал
    бы отвечать на вопрос «что писать».
    """
    items = await listed(auth_client, fields="title,features")

    assert items == [
        {
            "key": task.key,
            "title": task.title,
            "features": {
                "blocked": False,
                "open_questions": 0,
                "open_blocking_questions": 0,
                "open_remarks": 0,
                "last_summary_at": None,
                "last_entry_at": None,
            },
        }
    ]

    response = await auth_client.get("/api/v1/tasks", params={"fields": "blocked"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "search_field_unknown"
    assert error["details"] == {
        "field": "blocked",
        "reason": "not_selectable",
        "allowed": sorted(SELECTABLE_FIELDS),
    }


async def test_a_narrow_field_set_leaves_the_features_out_entirely(
    auth_client: AsyncClient, task: Task
) -> None:
    """Признаков нет в ответе, если их не просили: `null` соврал бы, а подзапросы стоят.

    У задачи признаки есть всегда, поэтому `"features": null` в строке читалось бы как
    «признаков нет», а не «их не считали». Ответ вместо этого поля не содержит вовсе — и
    четыре подзапроса на строку в базе не выполняются.
    """
    items = await listed(auth_client, fields="title")

    assert items == [{"key": task.key, "title": task.title}]
