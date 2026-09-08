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

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.idempotency import IdempotencyKey
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import InvalidSearchQueryError
from app.domain.query_language import QUERY_EXAMPLES, QUERY_WRONG_SHAPE, parse_query
from app.domain.search import Condition, Node, Operator, SearchFilter, searchable_names
from app.domain.tokens import TokenScope
from app.mcp.arguments import DEFAULT_SEARCH_FIELDS, QueryArg
from app.services import case as case_service
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
    "resolve",
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
    """Обзорная проверка 1: восемнадцать инструментов рабочего цикла и ни одного лишнего."""
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


# --- Лишний аргумент ------------------------------------------------------------------

#: Имя, которого нет и не будет ни у одного инструмента.
NOT_AN_ARGUMENT = "not_an_argument"


async def test_every_tool_refuses_an_argument_it_does_not_declare(
    mcp_session: Connect, main_secret: str
) -> None:
    """Обзорная проверка 2: лишний аргумент — отказ с его именем, у **каждого** инструмента.

    Список берётся из `tools/list`, а не перечисляется здесь: запрет объявлен один раз, на
    базовой модели аргументов (`app/mcp/toolset.py`), и инструмент, заведённый завтра,
    обязан попасть под проверку сам. Перечень имён в тесте отменил бы это свойство ровно
    в тот день, когда оно понадобится.

    Схема проверяется вместе с поведением: агент выбирает аргументы **до** вызова, и
    объявленный `additionalProperties: false` — единственное, из чего он узнаёт о запрете
    заранее.
    """
    async with mcp_session(main_secret) as session:
        listed = (await session.list_tools()).tools
        assert listed, "список инструментов пуст: проверять нечего"

        for tool in listed:
            assert tool.input_schema.get("additionalProperties") is False, (
                f"{tool.name}: схема не объявляет запрета лишнего"
            )
            failure = await refuse(session, tool.name, **{NOT_AN_ARGUMENT: "x"})
            assert NOT_AN_ARGUMENT in failure, f"{tool.name}: отказ не называет аргумент: {failure}"
            assert "extra_forbidden" in failure, f"{tool.name}: {failure}"


async def test_create_task_with_a_section_at_the_top_level_files_nothing(
    mcp_session: Connect, main_secret: str, queue: Queue
) -> None:
    """Тот самый случай: разделы присланы верхним уровнем вместо вложенного `sections`.

    Ловилось живьём (`TRK-22`): вызов отвечал успехом и заводил задачу с пятью **пустыми**
    разделами. Поэтому здесь проверяется не только текст отказа, но и то, что задачи не
    появилось: молчаливо заведённая пустая задача — и есть цена этой ошибки.
    """
    key = queue.key
    async with mcp_session(main_secret) as session:
        before = await call(session, "search_tasks", queue=[key], fields=["key"])

        failure = await refuse(
            session,
            "create_task",
            queue=key,
            title="Разделы верхним уровнем",
            description="Проверка отказа",
            goal="Цель, присланная мимо sections",
        )

        after = await call(session, "search_tasks", queue=[key], fields=["key"])

    assert "goal" in failure, failure
    assert "extra_forbidden" in failure, failure
    assert [item["key"] for item in after["items"]] == [item["key"] for item in before["items"]]


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


async def test_get_task_carries_the_index_and_the_transitions_of_the_table(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Вход в задачу: опись дела и переходы приезжают одним вызовом."""
    async with mcp_session(task_secret) as session:
        package = await call(session, "get_task", key=task.key)

    assert package["task"]["key"] == task.key
    assert [heading["type"] for heading in package["index"]] == ["created"]
    assert package["transitions"] == ["open", "waiting", "cancelled"]
    assert package["features"] == {
        "blocked": False,
        "open_questions": 0,
        "open_blocking_questions": 0,
        "open_remarks": 0,
        "last_summary_at": None,
        # В деле только служебная `created`: записей агента ещё нет, признак пуст.
        "last_entry_at": None,
    }


async def test_transitions_are_the_table_and_not_the_moves_that_would_pass_now(
    mcp_session: Connect, task_secret: str, open_task: Task, queue: Queue
) -> None:
    """`transitions` называет ходы по таблице; валидации считаются в момент перехода.

    Закрепляет семантику, а не текст: у заблокированной задачи `in_progress` в списке
    стоит, а сам ход отклоняется. Считать валидации при чтении отказались осознанно
    (`allowed_transitions` в `app/domain/tasks.py`) — это дорого и устаревает, пока агент
    думает. Вопрос «пустят ли» закрывает признак `blocked`.
    """
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
        package = await call(session, "get_task", key=key)
        refused = await refuse(session, "transition", key=key, to="in_progress")

    assert "in_progress" in package["transitions"]
    assert package["features"]["blocked"] is True
    assert "task_blocked" in refused


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
            open_remarks=0,
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
        "open_remarks": 0,
        "last_summary_at": None,
        # В деле только служебная `created`: записей агента ещё нет, признак пуст.
        "last_entry_at": None,
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
    """Обзорная проверка 5: теги не трогают исполнителя, а `null` его снимает.

    Состояние читается `get_task` после каждой правки, а не её ответом: изменяющий
    инструмент отвечает коротко (TRK-12), карточки в его ответе больше нет. Проверка от
    этого не ослабла — она смотрит на то же самое там, где оно теперь живёт, и по-прежнему
    ловит промежуточное состояние, а не только итог.
    """
    async with mcp_session(task_secret) as session:

        async def card() -> dict[str, Any]:
            return (await call(session, "get_task", key=task.key))["task"]

        assigned = await call(
            session, "update_task", key=task.key, changes={"assignee": "release_bot"}
        )
        after_assign = await card()
        raised = await call(session, "update_task", key=task.key, changes={"priority": "high"})
        after_raise = await card()
        cleared = await call(session, "update_task", key=task.key, changes={"assignee": None})
        after_clear = await card()

    # Каждая правка что-то подшила: пустой `entries` означал бы «прислано то, что уже
    # стоит», и тогда проверка ниже прошла бы по чужой причине.
    assert assigned["entries"] and raised["entries"] and cleared["entries"]
    assert after_assign["assignee"] == "release_bot"
    assert after_raise["assignee"] == "release_bot", "правка приоритета сняла исполнителя"
    assert after_raise["priority"] == "high"
    assert after_clear["assignee"] is None
    assert after_clear["priority"] == "high", "снятие исполнителя вернуло приоритет"


async def test_the_short_answer_carries_enough_for_the_next_move(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Обзорная проверка 3 TRK-12: версии из короткого ответа хватает на следующий ход.

    Это и есть граница урезания. Ответ изменяющего инструмента лишился карточки, но
    обязан оставить то, чего агент не мог знать заранее: новую версию, новый статус и
    номера подшитых записей. Версия проверяется делом, а не наличием поля: полученная
    из `transition`, она уходит в `update_task` следующим вызовом и не должна дать
    `version_conflict` — иначе экономия обернулась бы лишним `get_task` после каждого
    перехода, ровно тем, что задача убирала.
    """
    key = open_task.key
    async with mcp_session(task_secret) as session:
        moved = await call(session, "transition", key=key, to="in_progress")
        updated = await call(
            session, "update_task", key=key, changes={"priority": "high"}, version=moved["version"]
        )
        card = (await call(session, "get_task", key=key))["task"]

    assert moved["key"] == key
    assert moved["status"] == "in_progress"
    # Переход всегда что-то меняет, поэтому запись ровно одна — подшитая `status_changed`.
    assert len(moved["entries"]) == 1
    # Карточки в ответе больше нет: это и есть снятое поведение.
    assert set(moved) == {"key", "status", "version", "entries"}

    assert updated["version"] == moved["version"] + 1
    assert updated["entries"] == [moved["entries"][0] + 1]
    assert card["priority"] == "high"


async def test_an_update_that_changes_nothing_files_nothing(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Пустой `entries` — законный ответ, и по нему агент отличает «уже так было».

    Отдельного признака рядом нет намеренно (`app/mcp/views.py`, `mutation`): два способа
    узнать один факт разошлись бы при первой же правке. Значит пустой список обязан
    приходить именно тогда, когда версия не выросла, — это и проверяется.
    """
    async with mcp_session(task_secret) as session:
        first = await call(session, "update_task", key=task.key, changes={"priority": "high"})
        again = await call(session, "update_task", key=task.key, changes={"priority": "high"})

    assert first["entries"]
    assert again["entries"] == []
    assert again["version"] == first["version"], "версия выросла на правке, ничего не изменившей"


#: Раздел задачи, похожей на настоящую. Разделы боевых задач очереди `TRK` — это абзацы
#: по несколько сотен символов каждый, и именно они дают тот множитель, ради которого
#: задача затевалась. Задача из фикстуры их не имеет: её разделы в одну строку, и на ней
#: замер показал бы восьмикратную разницу вместо настоящей — то есть соврал бы в меньшую
#: сторону про боевой случай.
REALISTIC_SECTION = (
    "Ответы собираются в `app/mcp/views.py`; сами инструменты — `app/mcp/tools/tasks.py` "
    "и `app/mcp/tools/links.py`. Там же в шапке уже записано правило, которое эта задача "
    "продолжает: справочные представления короче реестровых, потому что агенту нужен "
    "контекст, не строка таблицы. Пакет преемника остаётся полным: это вход в задачу."
)

#: Потолок короткого ответа. Он не зависит от карточки вовсе: четыре поля, из которых
#: растёт только список номеров записей, и то на единицы байт. Число с запасом.
SHORT_ANSWER_CEILING = 256


async def test_the_short_answer_is_an_order_of_magnitude_smaller(
    mcp_session: Connect, task_secret: str, queue: Queue, db_session: AsyncSession, task: Task
) -> None:
    """Обзорная проверка 2 TRK-12: ответ перехода короче прежнего больше чем в десять раз.

    Меряется тем же текстом, который уезжает в контекст агента: `tool_text` — это ровно
    то, что он получает. Прежний ответ восстанавливается не по памяти: он был
    `views.task`, а это в точности раздел `task` пакета преемника, и его отдаёт тот же
    `get_task` тем же сериализатором. Обе величины сняты с одной задачи в один момент.

    Проверяются два разных утверждения, и второе важнее первого:

    - десятикратность — на задаче с разделами такой длины, какая бывает у настоящих;
    - **независимость** короткого ответа от карточки — на любой. Это и есть снятое
      свойство: раньше цена перехода росла вместе с задачей, теперь она постоянна, и
      никакая правка разделов её не поднимет.

    Дело набивается двадцатью записями, как требует проверка. На размер ответа они не
    влияют и не влияли: он от длины дела не зависел никогда (`TRK-12#5`).
    """
    actor = Actor(author=task.created_by, scope=TokenScope.TASK)
    big = await tasks_service.create_task(
        db_session,
        actor=actor,
        queue=queue,
        title="Разделы длиной, будто из боевой очереди",
        description=REALISTIC_SECTION,
        goal=REALISTIC_SECTION,
        context=REALISTIC_SECTION,
        constraints=REALISTIC_SECTION,
        output=REALISTIC_SECTION,
        checks=[REALISTIC_SECTION, REALISTIC_SECTION],
    )
    await tasks_service.transition_task(db_session, big, actor=actor, to="open")
    for number in range(20):
        await case_service.add_entry(
            db_session, big, actor=actor, type=EntryType.NOTE, title=f"Запись {number}"
        )
    await db_session.commit()

    async with mcp_session(task_secret) as session:
        package = await call(session, "get_task", key=big.key)
        assert len(package["index"]) >= 20, "проверка требует описи не меньше двадцати записей"
        moved = await session.call_tool("transition", {"key": big.key, "to": "in_progress"})
        # Задача из фикстуры: карточка на порядок меньше, ответ обязан быть тем же.
        small = await session.call_tool("transition", {"key": task.key, "to": "open"})

    before = len(json.dumps(package["task"], ensure_ascii=False, default=str))
    after = len(tool_text(moved))

    assert after * 10 < before, f"было {before} Б, стало {after} Б — меньше десяти раз"
    assert after < SHORT_ANSWER_CEILING
    assert len(tool_text(small)) < SHORT_ANSWER_CEILING, (
        "короткий ответ вырос вслед за длиной карточки"
    )


async def test_update_task_refuses_a_stale_version(
    mcp_session: Connect, task_secret: str, task: Task
) -> None:
    """Устаревшая версия — отказ, а не тихая перезапись чужого изменения."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session, "update_task", key=task.key, changes={"priority": "high"}, version=99
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
        failure = await refuse(session, "transition", key=key, to="open", reason="Нужны уточнения")
        await call(
            session,
            "add_summary",
            key=key,
            done="Сделал",
            remaining="Ничего",
            blockers="Ничего",
            next_step="Проверить",
        )
        moved = await call(session, "transition", key=key, to="open", reason="Нужны уточнения")
        forbidden = await refuse(session, "transition", key=key, to="review")

    assert taken["status"] == "in_progress"
    assert "summary_required" in failure
    assert moved["status"] == "open"
    # Статуса `review` нет вовсе: аргумент не проходит разбор, и отказ перечисляет
    # допустимые значения — по ним видно, какой ход вообще существует.
    assert all(
        f"'{status}'" in forbidden
        for status in ("backlog", "open", "in_progress", "done", "cancelled")
    )


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

    # Ответ короткий, и карточки в нём нет: всё, что в ней было бы, вызывающий прислал
    # сам. Остаётся то, чего он знать не мог, — ключ выдал трекер.
    assert set(child) == {"key", "status", "version", "entries"}
    assert child["status"] == "backlog"
    assert child["version"] == 1

    # Обзорная проверка 3: записей у этого вызова две — заведение и связь, — и короткий
    # ответ называет обе. Назвать одну значило бы соврать про то, чем вызов кончился.
    assert child["entries"] == [1, 2]
    assert [item["no"] for item in package["index"]] == child["entries"]
    assert [item["type"] for item in package["index"]] == ["created", "link_added"]

    # Обзорная проверка 2: ключ из короткого ответа сразу адресует задачу — `get_task`
    # выше вызван именно им, без промежуточного поиска.
    assert package["task"]["key"] == child["key"]

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
    # Ответ короткий уже здесь: повтор отдаёт ровно то, что ушло в первый раз.
    assert set(first) == {"key", "status", "version", "entries"}


async def test_a_repeat_of_a_call_made_before_the_answer_shrank_replays_the_old_answer(
    mcp_session: Connect, task_secret: str, db_session: AsyncSession, queue: Queue
) -> None:
    """Обзорная проверка 4: сохранённый ответ старой формы повтор не роняет.

    Ключи идемпотентности живут сутки (`app/domain/idempotency.py`, `KEY_TTL`), поэтому
    после правки в таблице сутки лежат ответы обеих форм. Повтор обязан отдать **тот
    самый** ответ, который ушёл в первый раз, а не собрать новый: у выпуска токена в
    ответе секрет, которого второй раз взять неоткуда, и правило одно на все операции.

    Значит на повтор вызова, сделанного до правки, придёт карточка целиком — и это
    правильно. Агент, начавший вызов вчера, получит то, что ожидал; новых длинных
    ответов при этом не появляется, а старые кончатся сами.
    """
    del queue
    key = str(uuid.uuid4())
    arguments: dict[str, Any] = {
        "queue": "TRK",
        "title": "Починить выдачу ключей",
        "description": "Ключ сгорает",
        "idempotency_key": key,
    }

    async with mcp_session(task_secret) as session:
        short = await call(session, "create_task", **arguments)

    # Подменяем сохранённый ответ на форму, в которой его записал бы вчерашний вызов.
    old_form = {"key": short["key"], "status": "backlog", "title": "Починить выдачу ключей"}
    await db_session.execute(
        update(IdempotencyKey).where(IdempotencyKey.key == key).values(response=old_form)
    )
    await db_session.flush()

    async with mcp_session(task_secret) as session:
        again = await call(session, "create_task", **arguments)
        found = await call(session, "search_tasks", queue=["TRK"])

    assert again == old_form, "повтор обязан отдать сохранённое, не пересобирая ответ"
    assert [item["key"] for item in found["items"]].count(short["key"]) == 1


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
    mcp_session: Connect, task_secret: str, queue: Queue
) -> None:
    """`in_progress → done` требует по каждой проверке последний вердикт `passed`.

    Отказ обязан объяснять, **почему** проверка не засчитана: пройденная в нём не
    упоминается вовсе, непройденная приходит с причиной — `no_verdict` или `failed`.
    """
    del queue
    async with mcp_session(task_secret) as session:
        task = await call(
            session,
            "create_task",
            queue="TRK",
            title="Задача из двух проверок",
            description="Проверки закрываются вердиктами",
            sections={
                "goal": "Цель",
                "context": "Контекст",
                "constraints": "Ограничения",
                "output": "Выход",
                "checks": ["первая", "вторая"],
            },
        )
        key = task["key"]
        await call(session, "transition", key=key, to="open")
        await call(session, "transition", key=key, to="in_progress")
        await call(
            session,
            "add_summary",
            key=key,
            done="Сделал",
            remaining="Прогнать проверки",
            blockers="Ничего",
            next_step="Подшить вердикты",
        )
        await call(
            session,
            "add_verdict",
            key=key,
            check_no=1,
            outcome="passed",
            evidence="Прогон зелёный",
        )
        without_verdict = await refuse(session, "transition", key=key, to="done")
        await call(
            session,
            "add_verdict",
            key=key,
            check_no=2,
            outcome="failed",
            evidence="Прогон красный",
        )
        failed = await refuse(session, "transition", key=key, to="done")
        await call(
            session,
            "add_verdict",
            key=key,
            check_no=2,
            outcome="passed",
            evidence="Прогон зелёный",
        )
        closed = await call(session, "transition", key=key, to="done")

    assert "checks_not_passed" in without_verdict
    assert '"checks": [{"check_no": 2, "reason": "no_verdict"}]' in without_verdict
    assert '"check_no": 1' not in without_verdict
    assert '"checks": [{"check_no": 2, "reason": "failed"}]' in failed
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


async def test_a_closed_task_carries_its_continuation_but_takes_no_blocker(
    mcp_session: Connect, task_secret: str, task: Task, queue: Queue
) -> None:
    """Главная проверка TRK-10 в MCP: продолжение видно из `get_task` закрытой задачи.

    Ключ и статус продолжения лежат в связях пакета — `read_entries` для родословной не
    нужен. `blocked_by` при этом по-прежнему отклоняется: закрытую задачу не делают
    заблокированной задним числом.
    """
    del queue
    key = task.key
    async with mcp_session(task_secret) as session:
        await call(session, "transition", key=key, to="cancelled", reason="вышло не то")
        continuation = await call(
            session,
            "create_task",
            queue="TRK",
            title="Продолжение",
            description="Выросло из отменённой",
        )
        await call(session, "link", key=continuation["key"], kind="relates", other=key)
        closed_package = await call(session, "get_task", key=key)
        grown_package = await call(session, "get_task", key=continuation["key"])
        refused = await refuse(
            session, "link", key=continuation["key"], kind="blocked_by", other=key
        )

    assert closed_package["task"]["status"] == "cancelled"
    assert [
        (item["kind"], item["other"]["key"], item["other"]["status"])
        for item in closed_package["links"]
    ] == [("relates", continuation["key"], "backlog")]
    assert [(item["kind"], item["other"]["key"]) for item in grown_package["links"]] == [
        ("relates", key)
    ]
    assert "task_closed" in refused


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


# --- Описание поиска: примеры оттуда обязаны работать ---------------------------------


def _query_description() -> str:
    """Описание поля `query`, как его увидит модель, — из самого объявления аргумента."""
    return str(QueryArg.__metadata__[0].description)


def test_every_query_example_of_the_tool_description_parses() -> None:
    """Обзорная проверка 3: примеры описания — рабочие запросы, а не иллюстрации.

    Примеры и описание не две копии, а одна: описание собрано из `QUERY_EXAMPLES`.
    Поэтому тест берёт список у домена и требует двух вещей сразу — что каждый пример
    разбирается и что он дошёл до текста, который прочтёт модель. Разойтись им негде.

    Разбирать текст описания обратно — регуляркой по строкам списка — было бы хуже, чем
    бесполезно: проверка зависела бы от вёрстки абзаца, а не от того, что в нём сказано,
    и молча перестала бы что-либо проверять от смены дефиса на звёздочку.
    """
    described = _query_description()

    assert len(QUERY_EXAMPLES) >= 3, "описание обязано показывать язык примерами, не одними словами"
    for example in QUERY_EXAMPLES:
        assert parse_query(example).root is not None, example
        assert f"`{example}`" in described, f"пример {example} не дошёл до описания"

    # Хотя бы один показывает оператор в его настоящем месте — после двоеточия. Ищется
    # он по разбору, а не по виду строки: у разобранного условия оператор — поле.
    assert any(
        condition.operator is not Operator.EQ
        for example in QUERY_EXAMPLES
        for condition in _conditions_of(parse_query(example))
    )


def _conditions_of(parsed: SearchFilter) -> list[Condition]:
    """Все условия разобранного запроса, вглубь по группам."""

    def walk(node: Node | None) -> list[Condition]:
        if node is None:
            return []
        if isinstance(node, Condition):
            return [node]
        return [item for child in node.nodes for item in walk(child)]

    return walk(parsed.root)


async def test_every_search_field_is_reachable_from_the_tool_itself(
    mcp_session: Connect, task_secret: str
) -> None:
    """Поле отбора названо там, где агент его ищет: в описании языка и в аргументах.

    Поле, о котором сказано только в исходниках, для агента не существует: он выбирает
    из того, что перечислено в описании инструмента. Проверка идёт по `searchable_names`,
    поэтому следующее поле само потребует себе места, а не будет забыто молча.

    Аргументов при этом меньше, чем полей: вычисляемые признаки со сравнением
    (`open_questions: > 0`) структурным параметром не выражаются — у них точное число.
    Здесь проверяется то, что выражается: поля-значения обязаны быть и там, и там.
    """
    described = _query_description()
    async with mcp_session(task_secret) as session:
        listed = {tool.name: tool for tool in (await session.list_tools()).tools}
    arguments = set(listed["search_tasks"].input_schema["properties"])

    for name in searchable_names():
        assert f"`{name}`" in described, f"поле {name} не названо в описании языка"

    for name in ("queue", "parent", "status", "assignee", "priority", "text"):
        assert name in arguments, f"поле {name} не выражается структурным параметром"


def test_the_description_names_the_wrong_shape_and_it_is_really_wrong() -> None:
    """Ошибочная форма названа в описании прямо — и остаётся ошибочной в разборе.

    Названа она потому, что её приносят из SQL раз за разом. А проверяется потому, что
    описание, объявившее ошибкой то, что на самом деле работает, — хуже молчания.
    """
    description = _query_description()

    assert QUERY_WRONG_SHAPE in description
    with pytest.raises(InvalidSearchQueryError):
        parse_query(QUERY_WRONG_SHAPE)
