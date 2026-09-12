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
from app.domain.tasks import TaskPriority, TaskStatus
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
    assert set(body["meta"]) == {"next_cursor", "has_more", "total"}
    return body["data"]


async def listed_keys(client: AsyncClient, **params: Any) -> list[str]:
    return [item["key"] for item in await listed(client, **params)]


@pytest.fixture
async def board(db_session: AsyncSession, task_actor: Actor, queue: Queue) -> dict[str, Task]:
    """Обычная открытая задача, заблокированная и открытая с блокирующим вопросом."""
    plain = await make(db_session, task_actor, queue, "обычная")
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
    # Список допустимого — единственное, что человек и агент увидят об этом наборе:
    # поле, не попавшее сюда, для них не существует.
    assert "parent" in error["details"]["allowed"]


async def test_a_removed_search_field_answers_with_the_list_without_it(
    auth_client: AsyncClient,
) -> None:
    """Отбор по снятому полю отказывает так же, как по выдуманному, и это важно.

    `tags: release` — запрос, который агент напишет по памяти. Ответ обязан сказать не
    только «нет такого поля», но и какие есть: иначе снятие механики читается как поломка
    поиска, и следующий ход — вопрос владельцу вместо чтения списка.
    """
    response = await auth_client.get("/api/v1/tasks", params={"query": "tags: release"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "search_field_unknown"
    assert error["details"]["field"] == "tags"
    assert "tags" not in error["details"]["allowed"]
    assert {"assignee", "priority", "status", "text"} <= set(error["details"]["allowed"])


async def test_a_structured_value_with_a_space_reaches_the_search(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Обзорная проверка 1 TRK-21 на уровне маршрута: два слова — выдача, а не 422.

    Отдельно от сценарного теста намеренно: значение проходит ещё и через разбор
    параметров запроса FastAPI, и «работает в сервисе, отказывает в маршруте» — ровно
    тот случай, который человек в интерфейсе и видел.
    """
    response = await auth_client.get("/api/v1/tasks", params={"text": "обычная задача"})

    assert response.status_code == 200, response.text


# --- Неизвестный параметр -----------------------------------------------------------------


async def test_a_typo_in_a_filter_name_is_refused_and_does_not_cancel_the_filter(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Обзорная проверка 4: `?stauts=open` отвечает отказом, а не выдачей целиком.

    До правки FastAPI незнакомый параметр игнорировал: запрос отвечал `200` и отдавал все
    задачи установки, а ответ выглядел как «под условие подошло всё» (`TRK-22`). Отказ
    называет и присланное имя, и список допустимых — по нему опечатка чинится с первой
    попытки, без похода в схему.
    """
    del board
    response = await auth_client.get("/api/v1/tasks", params={"stauts": "open"})

    assert response.status_code == 422, response.text
    problem = response.json()["error"]
    assert problem["code"] == "validation_error"
    assert [item["loc"] for item in problem["details"]["errors"]] == [["query", "stauts"]]
    assert problem["details"]["errors"][0]["type"] == "extra_forbidden"
    assert "status" in problem["details"]["allowed"]


async def test_every_declared_parameter_still_passes(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Закрытая дверь не задела законных: все параметры отбора вместе отвечают выдачей.

    Перечислены именно все, включая повторяющиеся и служебные (`query`, `sort`, `fields`,
    `limit`, `cursor`): сторож сверяет имена с деревом зависимостей маршрута, и параметр,
    приехавший из вложенного `Depends()`, легко оказался бы вне этого дерева.
    """
    everything: dict[str, Any] = {
        "key": [board["plain"].key],
        "queue": ["TRK"],
        "parent": ["empty()"],
        "status": ["open", "backlog"],
        "assignee": ["empty()"],
        "priority": ["normal"],
        "blocked": "false",
        "open_questions": 0,
        "open_blocking_questions": 0,
        "open_remarks": 0,
        "remarks_in_work": 0,
        "text": "задача",
        "query": "queue: TRK",
        "sort": ["-updated_at", "key"],
        "fields": ["key", "status"],
        "limit": 10,
        "offset": 0,
    }
    response = await auth_client.get("/api/v1/tasks", params=everything)
    assert response.status_code == 200, response.text

    # `cursor` отдельным запросом: под отбор выше подходит меньше страницы, следующей
    # страницы у него нет, и курсор пришлось бы выдумывать. Он берётся у настоящей
    # страницы — курсор несёт в себе ключи сортировки, и чужой отверг бы сам обход.
    first = await auth_client.get("/api/v1/tasks", params={"limit": 1})
    assert first.status_code == 200, first.text
    paged = await auth_client.get(
        "/api/v1/tasks",
        params={"limit": 1, "cursor": first.json()["meta"]["next_cursor"]},
    )

    assert paged.status_code == 200, paged.text


async def test_the_guard_covers_the_whole_api_and_not_the_task_list_alone(
    auth_client: AsyncClient, task: Task
) -> None:
    """Правило общее: сторож объявлен на роутере `/api/v1`, а не на одном маршруте.

    Маршрут дела берётся вторым входом намеренно — у него свои параметры, и молчаливое
    игнорирование опечатки в них стоило бы ровно столько же, сколько в отборе задач.
    """
    response = await auth_client.get(
        f"/api/v1/tasks/{task.key}/entries", params={"typez": "summary"}
    )

    assert response.status_code == 422, response.text
    problem = response.json()["error"]
    assert [item["loc"] for item in problem["details"]["errors"]] == [["query", "typez"]]
    assert "types" in problem["details"]["allowed"]


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


async def test_several_named_tasks_are_listed_by_key(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Ключ задачи — такой же параметр отбора, как остальные, и на обоих входах один.

    Ради этого поле и появилось: ведущий несколько дел спрашивает про них одним
    запросом, а не тянет очередь по статусу и не отбирает глазами.
    """
    first = board["plain"].key
    second = board["asking"].key

    by_parameter = await listed_keys(auth_client, key=[first, second])
    by_query = await listed_keys(auth_client, query=f"key: in {first}, {second}")

    assert by_parameter == sorted([first, second])
    assert by_query == by_parameter


async def test_an_unknown_key_in_the_filter_is_refused_and_named(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Пустая страница на опечатку читалась бы как ответ «по этим задачам ничего»."""
    del board
    response = await auth_client.get("/api/v1/tasks", params={"key": ["TRK-9999"]})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "search_value_invalid"
    assert error["details"]["field"] == "key"
    assert error["details"]["reason"] == "task_not_found"


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


# --- Страницами: общее число выдачи и адрес страницы --------------------------------------


async def test_the_total_counts_the_selection_and_not_the_page(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Из `meta.total` и `limit` собирается «страница 1 из 3, всего 7».

    Число считается по отбору, а не по странице: строк в ответе три, задач — семь, и
    без второго числа интерфейсу неоткуда узнать, сколько страниц он рисует.
    """
    for number in range(7):
        await make(db_session, task_actor, queue, f"задача {number}")

    response = await auth_client.get("/api/v1/tasks", params={"limit": 3})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 3
    assert body["meta"]["total"] == 7
    assert body["meta"]["has_more"] is True


async def test_the_total_follows_the_filter(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Число — это длина **отобранной** выдачи, а не всех задач установки."""
    response = await auth_client.get("/api/v1/tasks", params={"status": "open"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["total"] == len(body["data"]) == 3
    assert {item["key"] for item in body["data"]} == {
        board["plain"].key,
        board["blocked"].key,
        board["asking"].key,
    }


async def test_an_empty_selection_counts_zero_and_not_null(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """У посчитанной пустой выдачи стоит `0`: `null` означал бы «не считали»."""
    del board
    response = await auth_client.get("/api/v1/tasks", params={"text": "такой задачи нет"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == []
    assert body["meta"] == {"next_cursor": None, "has_more": False, "total": 0}


async def test_the_offset_addresses_the_same_page_the_cursor_leads_to(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 1: страница по адресу — та же, что и по курсору.

    Оба адреса ведут в одно место, пока между запросами ничего не менялось: смещение
    отличается не результатом, а тем, что не требует пройти предыдущие страницы.
    """
    for number in range(7):
        await make(db_session, task_actor, queue, f"задача {number}")

    first = await auth_client.get("/api/v1/tasks", params={"limit": 3})
    assert first.status_code == 200, first.text
    by_cursor = await auth_client.get(
        "/api/v1/tasks", params={"limit": 3, "cursor": first.json()["meta"]["next_cursor"]}
    )
    by_offset = await auth_client.get("/api/v1/tasks", params={"limit": 3, "offset": 3})

    assert by_cursor.status_code == by_offset.status_code == 200, by_offset.text
    assert by_offset.json()["data"] == by_cursor.json()["data"]
    assert by_offset.json()["meta"]["total"] == 7


async def test_the_pages_of_any_order_are_addressable_and_counted_the_same(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 4: и число, и адрес работают при любом `sort`, а не при умолчании.

    Порядок берётся тот же, что и у обхода курсором, поэтому проверяется главное: третья
    страница по смещению — это ровно то, что даёт обход тем же порядком с начала.
    """
    for number in range(7):
        await make(
            db_session,
            task_actor,
            queue,
            f"задача {number}",
            priority=TaskPriority.HIGH if number % 2 else TaskPriority.LOW,
        )

    for order in (None, "-updated_at", "priority", "key"):
        params: dict[str, Any] = {"limit": 2}
        if order is not None:
            params["sort"] = order

        whole = await auth_client.get("/api/v1/tasks", params={**params, "limit": 100})
        third = await auth_client.get("/api/v1/tasks", params={**params, "offset": 4})

        assert whole.status_code == third.status_code == 200, third.text
        assert whole.json()["meta"]["total"] == third.json()["meta"]["total"] == 7, order
        expected = [item["key"] for item in whole.json()["data"][4:6]]
        assert [item["key"] for item in third.json()["data"]] == expected, order


async def test_a_page_beyond_the_end_is_empty_and_still_knows_the_total(
    auth_client: AsyncClient, board: dict[str, Task]
) -> None:
    """Смещение за концом выдачи — законный запрос, а не отказ.

    Страницы с таким номером нет: отбор мог сузиться между двумя нажатиями, и ссылка на
    седьмую страницу пережила выдачу, в которой их две. Ответ говорит об этом честно —
    строк нет, `has_more` ложен, а `total` на месте, и по нему интерфейс поймёт, куда
    вернуться.
    """
    del board
    response = await auth_client.get("/api/v1/tasks", params={"limit": 2, "offset": 100})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == []
    assert body["meta"] == {"next_cursor": None, "has_more": False, "total": 4}


async def test_an_insertion_shifts_the_page_addressed_by_offset(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Цена смещения, записанная тестом: вставка между запросами сдвигает границу.

    Порядок убывающий, поэтому новая задача встаёт **перед** прочитанной страницей и
    двигает всю выдачу на строку: страница по смещению показывает задачу, которую
    человек уже видел. Курсор в том же месте отдаёт продолжение без повторов — он
    адресует позицию в порядке, а не номер строки. Обе выдачи законны, и разница между
    ними — то, за что платит выбор смещения (`docs/notes/api.md`).
    """
    made = [await make(db_session, task_actor, queue, f"задача {number}") for number in range(6)]

    first = await auth_client.get("/api/v1/tasks", params={"limit": 3, "sort": "-key"})
    assert first.status_code == 200, first.text
    seen = [item["key"] for item in first.json()["data"]]
    await make(db_session, task_actor, queue, "вставленная посреди обхода")

    by_offset = await auth_client.get(
        "/api/v1/tasks", params={"limit": 3, "sort": "-key", "offset": 3}
    )
    by_cursor = await auth_client.get(
        "/api/v1/tasks",
        params={"limit": 3, "sort": "-key", "cursor": first.json()["meta"]["next_cursor"]},
    )

    assert seen == [task.key for task in reversed(made[3:])]
    assert by_offset.json()["data"][0]["key"] == seen[-1]
    assert [item["key"] for item in by_cursor.json()["data"]] == [
        task.key for task in reversed(made[:3])
    ]
    assert by_offset.json()["meta"]["total"] == by_cursor.json()["meta"]["total"] == 7


async def test_a_cursor_and_an_offset_together_are_refused(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Два адреса одной страницы в одном запросе — отказ, а не выбор за клиента."""
    for number in range(4):
        await make(db_session, task_actor, queue, f"задача {number}")
    first = await auth_client.get("/api/v1/tasks", params={"limit": 2})

    response = await auth_client.get(
        "/api/v1/tasks",
        params={"limit": 2, "offset": 2, "cursor": first.json()["meta"]["next_cursor"]},
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "cursor_with_offset"
    assert error["details"]["offset"] == 2


async def test_a_negative_offset_is_refused_by_the_parameter(auth_client: AsyncClient) -> None:
    """Границу смещения объявляет параметр запроса — как и границу размера страницы."""
    response = await auth_client.get("/api/v1/tasks", params={"offset": -1})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_the_answer_without_the_new_parameters_is_the_former_one(
    auth_client: AsyncClient, db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 3: прежний вызов отвечает прежним, а `total` только дописан.

    Страница, её порядок, курсор и `has_more` — те же, что и до задачи; из нового в
    ответе одно поле `meta`, и старый клиент, читающий два прежних, ничего не заметил.
    """
    made = [await make(db_session, task_actor, queue, f"задача {number}") for number in range(4)]

    response = await auth_client.get("/api/v1/tasks", params={"limit": 2, "fields": "key"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == [{"key": made[0].key}, {"key": made[1].key}]
    assert body["meta"]["has_more"] is True
    assert body["meta"]["next_cursor"] is not None
    assert body["meta"]["total"] == 4

    tail = await auth_client.get(
        "/api/v1/tasks",
        params={"limit": 2, "fields": "key", "cursor": body["meta"]["next_cursor"]},
    )

    assert tail.json()["data"] == [{"key": made[2].key}, {"key": made[3].key}]
    assert tail.json()["meta"]["has_more"] is False
