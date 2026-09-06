"""Факты в описи дела: по ним запись называют строкой, не читая тела.

Главное здесь — не «поле есть», а два свойства, ради которых оно заведено: по описи
можно построить строку на своём языке, не разбирая собранный трекером английский
заголовок, и опись при этом остаётся дешёвой — её размер не зависит от длины разделов
задачи, как бы их ни правили.
"""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.links import LinkKind
from app.domain.tasks import MAX_CHECK_LENGTH, MAX_TEXT_LENGTH, TaskStatus
from app.services import case as case_service
from app.services import links as links_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from app.services.tasks import TaskChanges

pytestmark = pytest.mark.anyio

#: Сколько байт на строку описи считается дешёвым. Проверяется не ради красоты числа:
#: опись входит в каждый пакет задачи, и строка, выросшая в разы, означает, что в неё
#: просочилось что-то свободное по длине.
MAX_HEADING_BYTES = 450


async def make(session: AsyncSession, actor: Actor, queue: Queue, title: str) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        queue=queue,
        title=title,
        description="description",
        goal="goal",
        context="context",
        constraints="constraints",
        output="output",
        checks=["check"],
    )


async def index_of(session: AsyncSession, actor: Actor, task: Task) -> list[Any]:
    """Опись так, как её видит пакет задачи."""
    package = await tasks_service.read_task_package(session, task.key, actor=actor)
    return list(package.index)


def facts_of(index: list[Any], entry_type: EntryType) -> Any:
    """Факты первой записи этого типа. Отсутствие записи — ошибка расстановки теста."""
    for heading in index:
        if heading.type == entry_type:
            return heading.facts
    raise AssertionError(f"в описи нет записи типа {entry_type.value}")


# --- Что попадает в факты по каждому типу ---------------------------------------------


async def test_a_status_move_carries_both_ends_and_whether_a_reason_was_given(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    task = await make(db_session, task_actor, queue, "status moves")
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason=None
    )
    await tasks_service.transition_task(
        db_session,
        task,
        actor=task_actor,
        to=TaskStatus.BACKLOG,
        reason="reason given",
    )

    moves = [
        heading.facts
        for heading in await index_of(db_session, task_actor, task)
        if heading.type is EntryType.STATUS_CHANGED
    ]

    assert [(move.from_status, move.to_status) for move in moves] == [
        (TaskStatus.BACKLOG, TaskStatus.OPEN),
        (TaskStatus.OPEN, TaskStatus.BACKLOG),
    ]
    # Причина — свободный текст: в описи от неё остаётся только «была или нет».
    assert [move.has_reason for move in moves] == [False, True]


async def test_a_link_carries_its_kind_and_the_other_key(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    task = await make(db_session, task_actor, queue, "link side")
    other = await make(db_session, task_actor, queue, "other side")

    await links_service.add_link(
        db_session, task, other, actor=task_actor, kind=LinkKind.BLOCKED_BY
    )
    await links_service.remove_link(
        db_session, task, other, actor=task_actor, kind=LinkKind.BLOCKED_BY
    )

    index = await index_of(db_session, task_actor, task)
    added = facts_of(index, EntryType.LINK_ADDED)
    removed = facts_of(index, EntryType.LINK_REMOVED)

    assert (added.link_kind, added.other_key) == (LinkKind.BLOCKED_BY, other.key)
    assert (removed.link_kind, removed.other_key) == (LinkKind.BLOCKED_BY, other.key)


async def test_an_assignee_change_carries_both_names(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    task = await make(db_session, task_actor, queue, "assignee case")

    await tasks_service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(assignee="owner")
    )

    facts = facts_of(await index_of(db_session, task_actor, task), EntryType.ASSIGNEE_CHANGED)
    # Имена участников ограничены по длине, поэтому видны прямо в описи.
    assert (facts.assignee_from, facts.assignee_to) == (None, "owner")


async def test_a_section_change_carries_the_field_name_and_nothing_else(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    task = await make(db_session, task_actor, queue, "section edit")
    long_text = "ы" * (MAX_TEXT_LENGTH - 1)

    await tasks_service.update_task(
        db_session, task, actor=task_actor, changes=TaskChanges(goal=long_text)
    )

    facts = facts_of(await index_of(db_session, task_actor, task), EntryType.SECTION_CHANGED)
    assert facts.field is not None and facts.field.value == "goal"
    # Значения раздела в описи нет и быть не может: он бывает длиннее самой задачи.
    assert "ы" not in json.dumps(_as_json(facts), ensure_ascii=False)


# --- Записи, у которых заголовок тоже строит трекер ------------------------------------


async def test_a_question_an_answer_and_a_verdict_are_nameable_from_the_index(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Проверка 5: по описи называется и то, чему заголовок выводит трекер."""
    task = await make(db_session, task_actor, queue, "question case")
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason=None
    )
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.IN_PROGRESS, reason=None
    )

    question = await case_service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=["owner"],
        title="a question to answer",
        blocking=True,
    )
    await case_service.answer(
        db_session, task, actor=task_actor, question_no=question.no, body="yes"
    )
    await case_service.add_verdict(
        db_session, task, actor=task_actor, check_no=1, outcome="passed", evidence="green run"
    )

    index = await index_of(db_session, task_actor, task)
    asked = facts_of(index, EntryType.QUESTION)
    answered = facts_of(index, EntryType.ANSWER)
    verdict = facts_of(index, EntryType.VERDICT)

    assert (asked.addressees, asked.blocking) == (("owner",), True)
    assert answered.question_no == question.no
    assert (verdict.check_no, verdict.outcome.value) == (1, "passed")


async def test_entries_written_by_their_author_carry_no_facts(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """У записи агента заголовок пишет автор: называть строку нечем и незачем."""
    task = await make(db_session, task_actor, queue, "note case")
    await case_service.add_entry(
        db_session,
        task,
        actor=task_actor,
        type=EntryType.NOTE,
        title="note",
        body="MARKER-BODY",
    )

    facts = facts_of(await index_of(db_session, task_actor, task), EntryType.NOTE)
    assert set(_as_json(facts).values()) == {None}


# --- Чего в описи нет ------------------------------------------------------------------


async def test_the_index_holds_no_free_text_of_any_kind(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Проверка 4: ни тела, ни разделов, ни причины перехода, ни списка проверок."""
    task = await make(db_session, task_actor, queue, "all at once")
    await tasks_service.update_task(
        db_session,
        task,
        actor=task_actor,
        changes=TaskChanges(goal="MARKER-GOAL", checks=["MARKER-CHECK"]),
    )
    await tasks_service.transition_task(
        db_session,
        task,
        actor=task_actor,
        to=TaskStatus.OPEN,
        reason="MARKER-REASON",
    )
    await case_service.add_entry(
        db_session,
        task,
        actor=task_actor,
        type=EntryType.FINDING,
        title="finding",
        body="MARKER-BODY",
    )

    index = await index_of(db_session, task_actor, task)
    written = json.dumps([_as_json(heading.facts) for heading in index], ensure_ascii=False)

    for marker in ("MARKER-GOAL", "MARKER-CHECK", "MARKER-REASON", "MARKER-BODY"):
        assert marker not in written, f"в фактах описи оказалось свободное содержимое: {marker}"


async def test_the_index_does_not_grow_with_the_length_of_the_sections(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Проверка 3: главная. Правки разделов близ потолка длины не утяжеляют опись."""
    long_text = "ы" * (MAX_TEXT_LENGTH - 1)
    long_checks = ["я" * (MAX_CHECK_LENGTH - 1) for _ in range(10)]

    heavy = await make(db_session, task_actor, queue, "heavy edits")
    light = await make(db_session, task_actor, queue, "light edits")

    for field, value in (
        ("goal", long_text),
        ("context", long_text),
        ("constraints", long_text),
        ("output", long_text),
        ("description", long_text),
    ):
        await tasks_service.update_task(
            db_session, heavy, actor=task_actor, changes=TaskChanges(**{field: value})
        )
        await tasks_service.update_task(
            db_session, light, actor=task_actor, changes=TaskChanges(**{field: "short"})
        )

    # Список проверок правится дважды: он не текст, а список, и весит иначе.
    for value in (long_checks, [*long_checks, "one more"]):
        await tasks_service.update_task(
            db_session, heavy, actor=task_actor, changes=TaskChanges(checks=value)
        )
    for value in (["one"], ["one", "two"]):
        await tasks_service.update_task(
            db_session, light, actor=task_actor, changes=TaskChanges(checks=value)
        )

    heavy_index = await index_of(db_session, task_actor, heavy)
    light_index = await index_of(db_session, task_actor, light)
    assert len(heavy_index) == len(light_index), "расстановка должна дать равные описи"

    heavy_size = _index_bytes(heavy_index)
    light_size = _index_bytes(light_index)

    # Разница между описями — только в заголовках, которые собрал трекер, и в ключах
    # задач. Тексты разделов не дают ни байта: их там нет.
    # Сами факты тоже не зависят от длины разделов: они и есть то место, куда текст
    # разделов мог бы просочиться, и меряются отдельно от заголовков.
    assert _facts_bytes(heavy_index) == _facts_bytes(light_index), (
        "факты подорожали от длины разделов"
    )
    assert heavy_size < light_size * 1.1, (
        f"опись подорожала от длины разделов: {heavy_size} против {light_size}"
    )
    assert heavy_size / len(heavy_index) < MAX_HEADING_BYTES, (
        f"строка описи стала дороже {MAX_HEADING_BYTES} байт: {heavy_size / len(heavy_index):.0f}"
    )


# --- Цена пакета -----------------------------------------------------------------------


async def test_the_package_still_costs_the_same_number_of_queries(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Проверка 6: факты вырезаются в том же запросе, что и опись.

    Число запросов сравнивается не с числом из головы, а само с собой: пакет задачи
    с тремя записями и пакет с шестьюдесятью обязаны стоить одинаково. Запрос на строку
    описи виден только так — ни по ответу, ни по времени его не заметить.
    """
    small = await make(db_session, task_actor, queue, "small case")
    big = await make(db_session, task_actor, queue, "big case")
    for index in range(60):
        await case_service.add_entry(
            db_session, big, actor=task_actor, type=EntryType.NOTE, title=f"note {index}"
        )

    small_queries = await _count_selects(db_session, task_actor, small)
    big_queries = await _count_selects(db_session, task_actor, big)

    assert small_queries == big_queries, (
        f"пакет большого дела стоил дороже: {big_queries} против {small_queries}"
    )


async def test_the_rest_answer_carries_the_facts(auth_client: AsyncClient, queue: Queue) -> None:
    """Тот же состав приходит и в HTTP-ответе, а не только в домене."""
    created = await auth_client.post(
        "/api/v1/tasks",
        json={
            "queue": queue.key,
            "title": "facts in the answer",
            "description": "description",
            # Разделы заполнены: без них переход в `open` отвечает
            # `task_sections_incomplete`, а нам нужен сам переход.
            "goal": "goal",
            "context": "context",
            "constraints": "constraints",
            "output": "output",
            "checks": ["check"],
        },
    )
    assert created.status_code == 201, created.text
    key = created.json()["data"]["key"]

    moved = await auth_client.post(f"/api/v1/tasks/{key}/transition", json={"to": "open"})
    assert moved.status_code == 200, moved.text

    package = await auth_client.get(f"/api/v1/tasks/{key}")
    assert package.status_code == 200, package.text

    headings = package.json()["data"]["index"]
    move = next(item for item in headings if item["type"] == "status_changed")
    assert move["facts"]["from_status"] == "backlog"
    assert move["facts"]["to_status"] == "open"
    assert move["facts"]["has_reason"] is False


# --- Вспомогательное -------------------------------------------------------------------


def _as_json(facts: Any) -> dict[str, Any]:
    """Факты словарём: у домена это `dataclass` со `slots`, и `__dict__` у него нет."""
    return {
        name: getattr(facts, name)
        for name in (
            "from_status",
            "to_status",
            "has_reason",
            "field",
            "link_kind",
            "other_key",
            "assignee_from",
            "assignee_to",
            "addressees",
            "blocking",
            "question_no",
            "check_no",
            "outcome",
        )
    }


def _index_bytes(index: list[Any]) -> int:
    """Сколько весит опись, если её отдать клиенту.

    Считается так же, как её сериализует схема: незаполненные части едут в ответе
    как `null` — ради типизированного клиента, см. `docs/notes/api.md`.
    """
    return len(
        json.dumps(
            [
                {
                    "no": heading.no,
                    "type": heading.type.value,
                    "title": heading.title,
                    "facts": {
                        name: (value.value if hasattr(value, "value") else value)
                        for name, value in _as_json(heading.facts).items()
                    },
                }
                for heading in index
            ],
            ensure_ascii=False,
        ).encode()
    )


def _facts_bytes(index: list[Any]) -> int:
    """Сколько в описи весят сами факты — без номеров, типов и заголовков."""
    return len(
        json.dumps(
            [
                {
                    name: (value.value if hasattr(value, "value") else value)
                    for name, value in _as_json(heading.facts).items()
                }
                for heading in index
            ],
            ensure_ascii=False,
        ).encode()
    )


async def _count_selects(session: AsyncSession, actor: Actor, task: Task) -> int:
    statements: list[str] = []
    connection = await session.connection()

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(connection.sync_connection.engine, "before_cursor_execute", record)
    try:
        await tasks_service.read_task_package(session, task.key, actor=actor)
    finally:
        event.remove(connection.sync_connection.engine, "before_cursor_execute", record)

    return len([item for item in statements if item.lstrip().upper().startswith("SELECT")])
