"""Сценарии дела: подшивка записей агента, проверки по базе, пакет преемника, вопросы.

Здесь то, чего нельзя проверить без базы: существование адресата и записи, на которую
ссылаются, открытость вопроса, отсчёт сводки и вердиктов от последнего входа в
`in_progress`.
Форма записи проверяется без базы — `tests/test_domain_case.py`.
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.authors import label_author
from app.domain.case import EntryType
from app.domain.errors import (
    ActorNotAddressableError,
    ChecksNotPassedError,
    EntryFieldsInvalidError,
    EntryNotFoundError,
    ParticipantNotFoundError,
    SummaryRequiredError,
)
from app.domain.participants import ParticipantKind
from app.domain.tasks import TaskStatus
from app.domain.tokens import TokenScope
from app.services import case as service
from app.services import participants as participants_service
from app.services import queues as queues_service
from app.services import tasks as tasks_service
from app.services.auth import Actor

SUMMARY = {
    "done": "Разобрался, где сгорает номер",
    "remaining": "Перенести выдачу номера",
    "blockers": "нет",
    "next_step": "Перенести вызов в конец create_task",
}


async def entries(session: AsyncSession, task: Task, **filters: Any) -> list[Entry]:
    page = await service.list_entries(session, task, actor=_reader(task), limit=200, **filters)
    return page.items


def _reader(task: Task) -> Actor:
    return Actor(author=task.created_by, scope=TokenScope.TASK)


async def take(session: AsyncSession, task: Task, actor: Actor) -> None:
    """Заводит задачу в работу: `backlog → open → in_progress`."""
    for status in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS):
        await tasks_service.transition_task(session, task, actor=actor, to=status)


async def ready(session: AsyncSession, actor: Actor, queue: Queue, *, checks: list[str]) -> Task:
    """Новая задача с этими проверками, в работе и с готовым выходом.

    Сводка и два перехода — не предмет здешних тестов, но без них до `done` не
    добраться: правило сводки проверяется выше своим тестом.
    """
    task = await tasks_service.create_task(
        session,
        actor=actor,
        queue=queue,
        title="Задача на закрытие",
        description="Есть",
        goal="Цель",
        context="Контекст",
        constraints="Ограничения",
        output="Выход",
        checks=checks,
    )
    await take(session, task, actor)
    await service.add_summary(session, task, actor=actor, **SUMMARY)
    return task


async def pass_all(session: AsyncSession, task: Task, actor: Actor) -> None:
    """Положительный вердикт по каждой проверке задачи."""
    for check_no in range(1, len(task.checks) + 1):
        await service.add_verdict(session, task, actor=actor, check_no=check_no, outcome="passed")


# --- Подшивка -------------------------------------------------------------------------


async def test_a_summary_lands_in_the_index_titled_by_what_was_done(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 1 на уровне сценария: в опись едет `done`, а не `next_step`."""
    entry = await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)

    assert entry.type is EntryType.SUMMARY
    assert entry.title == SUMMARY["done"]
    assert entry.title != SUMMARY["next_step"]
    assert entry.payload == SUMMARY
    assert entry.author.signature == "owner"

    index = await service.case_index(db_session, task, actor=task_actor)
    assert [(heading.no, heading.title) for heading in index] == [
        (1, "Task created"),
        (2, SUMMARY["done"]),
    ]


async def test_an_entry_is_filed_into_a_closed_task(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 11: `done` запрещает менять поля, но не дело."""
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.CANCELLED, reason="Задача снята"
    )

    entry = await service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Всё же пригодилось"
    )

    assert entry.type is EntryType.NOTE
    assert task.status is TaskStatus.CANCELLED


# --- Проверки, которым нужна база -----------------------------------------------------


async def test_an_unknown_addressee_is_named_in_the_details(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 4: адресовать можно только участника реестра."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        await service.ask(
            db_session,
            task,
            actor=task_actor,
            addressees=["owner", "ghost"],
            title="Чей вердикт нужен?",
            blocking=False,
        )

    assert error.value.details["fields"] == [
        {"field": "addressees", "reason": "unknown_participant", "name": "ghost"}
    ]


async def test_an_answer_points_at_a_question_of_the_same_task(
    db_session: AsyncSession, task: Task, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 5: чужая запись и запись не того типа отвергаются одинаково."""
    other = await tasks_service.create_task(
        db_session,
        actor=task_actor,
        queue=queue,
        title="Соседняя задача",
        description="Есть",
    )
    await service.ask(
        db_session, other, actor=task_actor, addressees=["owner"], title="Как быть?", blocking=False
    )

    # В соседней задаче вопрос — запись №2; в нашей запись №2 это сводка, а №99 нет вовсе.
    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)

    with pytest.raises(EntryFieldsInvalidError) as not_a_question:
        await service.answer(db_session, task, actor=task_actor, question_no=2, body="Да")
    assert not_a_question.value.details["fields"] == [
        {
            "field": "question_no",
            "reason": "not_a_question",
            "key": "TRK-1",
            "no": 2,
            "got": "summary",
        }
    ]

    with pytest.raises(EntryFieldsInvalidError) as missing:
        await service.answer(db_session, task, actor=task_actor, question_no=99, body="Да")
    assert missing.value.details["fields"][0]["reason"] == "unknown_entry"


async def test_a_reference_to_a_missing_entry_is_refused(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 10: ссылки внутрь трекера проверяются, адреса — нет."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        await service.add_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.FINDING,
            title="Нашёл",
            refs=["TRK-1#99", "https://example.com"],
        )

    assert error.value.details["fields"] == [
        {"field": "refs", "reason": "unknown_entry", "ref": "TRK-1#99"}
    ]

    entry = await service.add_entry(
        db_session,
        task,
        actor=task_actor,
        type=EntryType.FINDING,
        title="Нашёл",
        refs=["TRK-1#1", "https://example.com"],
    )
    assert entry.refs == ["TRK-1#1", "https://example.com"]


async def test_a_reference_to_a_missing_task_is_refused(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    with pytest.raises(EntryFieldsInvalidError) as error:
        await service.add_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.NOTE,
            title="Заметка",
            refs=["TRK-404"],
        )

    assert error.value.details["fields"] == [
        {"field": "refs", "reason": "unknown_task", "ref": "TRK-404"}
    ]


# --- Проверки перехода ----------------------------------------------------------------


async def test_leaving_in_progress_needs_a_summary_filed_after_the_last_entry(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорные проверки 2 и 3: старая сводка повторно взятую задачу не закрывает."""
    await take(db_session, task, task_actor)

    with pytest.raises(SummaryRequiredError) as error:
        await tasks_service.transition_task(
            db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason="Нужны уточнения"
        )
    assert error.value.code == "summary_required"

    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason="Нужны уточнения"
    )
    assert task.status is TaskStatus.OPEN

    # Задача взята снова: сводка первого захода уже не считается.
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.IN_PROGRESS
    )

    with pytest.raises(SummaryRequiredError):
        await tasks_service.transition_task(
            db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason="Снова уточнения"
        )

    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason="Снова уточнения"
    )
    assert task.status is TaskStatus.OPEN


async def test_closing_needs_the_last_verdict_of_every_check_to_be_passed(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 7: провал закрывается новым вердиктом, а не правкой старого."""
    task = await ready(db_session, task_actor, queue, checks=["первая", "вторая", "третья"])

    await pass_all(db_session, task, task_actor)
    await service.add_verdict(db_session, task, actor=task_actor, check_no=2, outcome="failed")

    with pytest.raises(ChecksNotPassedError) as error:
        await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.DONE)
    # В отказе только незасчитанная проверка и причина: пройденные в нём не упоминаются.
    assert error.value.details["checks"] == [{"check_no": 2, "reason": "failed"}]

    await service.add_verdict(
        db_session, task, actor=task_actor, check_no=2, outcome="passed", evidence="Прогон зелёный"
    )
    await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.DONE)
    assert task.status is TaskStatus.DONE


async def test_verdicts_of_the_previous_stint_do_not_close_the_new_one(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Обзорная проверка 3: возврат в `open` обнуляет зачёт вердиктов.

    Проверяется именно поведение границы: вердикты никуда не деваются из дела —
    перестаёт засчитываться то, что подшито до последнего входа в `in_progress`.
    """
    task = await ready(db_session, task_actor, queue, checks=["первая", "вторая"])
    await pass_all(db_session, task, task_actor)

    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.OPEN, reason="выход переделать"
    )
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.IN_PROGRESS
    )
    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)

    with pytest.raises(ChecksNotPassedError) as error:
        await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.DONE)
    assert error.value.details["checks"] == [
        {"check_no": 1, "reason": "no_verdict"},
        {"check_no": 2, "reason": "no_verdict"},
    ]
    assert len(await entries(db_session, task, types=[EntryType.VERDICT])) == 2, "история цела"

    await pass_all(db_session, task, task_actor)
    await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.DONE)
    assert task.status is TaskStatus.DONE


async def test_rewritten_checks_do_not_inherit_the_old_verdicts(
    db_session: AsyncSession, task_actor: Actor, queue: Queue
) -> None:
    """Задача 31, обзорная проверка 2: правка `checks` не оставляет старых `passed`.

    Номера проверок те же самые, а проверяют они другое: без границы вердикт по первой
    проверке молча закрыл бы переписанную первую проверку.
    """
    task = await ready(db_session, task_actor, queue, checks=["первая", "вторая"])
    await pass_all(db_session, task, task_actor)

    # Пять разделов правятся только в `backlog` (`CONCEPT.md`, 3.3), и задача идёт туда
    # шагом назад с причиной.
    for status in (TaskStatus.OPEN, TaskStatus.BACKLOG):
        await tasks_service.transition_task(
            db_session, task, actor=task_actor, to=status, reason="проверки сформулированы неверно"
        )
    await tasks_service.update_task(
        db_session,
        task,
        actor=task_actor,
        changes=tasks_service.TaskChanges(checks=["другая первая", "другая вторая"]),
    )
    await take(db_session, task, task_actor)
    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)

    with pytest.raises(ChecksNotPassedError) as error:
        await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.DONE)
    assert error.value.details["checks"] == [
        {"check_no": 1, "reason": "no_verdict"},
        {"check_no": 2, "reason": "no_verdict"},
    ]


# --- Пакет преемника ------------------------------------------------------------------


async def test_the_package_carries_the_last_summary_and_the_open_questions_in_full(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    """Обзорная проверка 8 на уровне сценария: сводка последняя, вопросы только открытые."""
    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)
    await service.add_summary(
        db_session, task, actor=task_actor, **{**SUMMARY, "next_step": "Последний шаг"}
    )
    answered = await service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=["owner"],
        title="Первый вопрос",
        blocking=True,
    )
    await service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=["owner"],
        title="Второй вопрос",
        blocking=False,
    )
    await service.answer(db_session, task, actor=task_actor, question_no=answered.no, body="Да")

    package = await tasks_service.read_task_package(db_session, "TRK-1", actor=task_actor)

    assert package.summary is not None
    assert package.summary.payload["next_step"] == "Последний шаг"
    assert [question.title for question in package.questions] == ["Второй вопрос"]
    assert package.features.open_questions == 1
    assert package.features.open_blocking_questions == 0
    assert package.features.last_summary_at == package.summary.created_at
    assert len(package.index) == 6


async def test_blocking_questions_are_counted_separately(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    await service.ask(
        db_session, task, actor=task_actor, addressees=["owner"], title="Ждёт", blocking=True
    )
    await service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=["owner"],
        title="Ждать не нужно",
        blocking=False,
    )

    package = await tasks_service.read_task_package(db_session, "TRK-1", actor=task_actor)

    assert package.features.open_questions == 2
    assert package.features.open_blocking_questions == 1


# --- Чтение записей -------------------------------------------------------------------


async def test_entries_are_filtered_by_number_type_and_position(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    await service.add_summary(db_session, task, actor=task_actor, **SUMMARY)
    await service.add_entry(
        db_session, task, actor=task_actor, type=EntryType.NOTE, title="Заметка"
    )
    await service.add_summary(
        db_session, task, actor=task_actor, **{**SUMMARY, "next_step": "Второй шаг"}
    )

    assert [entry.no for entry in await entries(db_session, task, types=[EntryType.SUMMARY])] == [
        2,
        4,
    ]
    assert [entry.no for entry in await entries(db_session, task, after_no=2)] == [3, 4]
    assert [entry.no for entry in await entries(db_session, task, nos=[1, 4])] == [1, 4]
    # Пустой список типов — это «ничего», а не «всё»: иначе отбор нуля типов клиентом
    # молча превратился бы в чтение всего дела.
    assert await entries(db_session, task, types=[]) == []


async def test_a_missing_entry_number_is_not_found(
    db_session: AsyncSession, task: Task, task_actor: Actor
) -> None:
    with pytest.raises(EntryNotFoundError) as error:
        await service.read_entry(db_session, task, 99, actor=task_actor)

    assert error.value.details == {"key": "TRK-1", "no": 99}


# --- Вопросы поперёк задач ------------------------------------------------------------


async def test_the_inbox_keeps_only_open_questions_of_the_addressee(
    db_session: AsyncSession, task: Task, task_actor: Actor, main_actor: Actor
) -> None:
    """Обзорная проверка 9 на уровне сценария."""
    reviewer = await participants_service.register_participant(
        db_session,
        actor=main_actor,
        kind=ParticipantKind.AGENT,
        name="reviewer",
        description="Проверяющий",
    )
    await service.ask(
        db_session, task, actor=task_actor, addressees=["owner"], title="Ждёт", blocking=True
    )
    await service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=["owner"],
        title="Ждать не нужно",
        blocking=False,
    )
    mine = await service.ask(
        db_session, task, actor=task_actor, addressees=["reviewer"], title="Чужой", blocking=True
    )

    page = await service.list_questions(db_session, actor=task_actor, blocking=True)
    assert [item.entry.title for item in page.items] == ["Ждёт"]
    assert [item.task_key for item in page.items] == ["TRK-1"]

    for_reviewer = await service.list_questions(
        db_session, actor=task_actor, addressee="Reviewer", blocking=True
    )
    assert [item.entry.title for item in for_reviewer.items] == ["Чужой"]
    assert reviewer.name == "reviewer"

    await service.answer(db_session, task, actor=task_actor, question_no=mine.no, body="Ответ")
    after = await service.list_questions(
        db_session, actor=task_actor, addressee="reviewer", blocking=True
    )
    assert after.items == []


async def test_the_inbox_of_a_temporary_agent_is_a_refusal_rather_than_an_empty_list(
    db_session: AsyncSession, task: Task
) -> None:
    """Адресовать временного агента нельзя, и пустой список соврал бы об этом."""
    temporary = Actor(author=label_author("nightly_agent"), scope=TokenScope.TASK)

    with pytest.raises(ActorNotAddressableError) as error:
        await service.list_questions(db_session, actor=temporary)

    assert error.value.code == "actor_not_addressable"
    assert error.value.details == {"signature": "nightly_agent"}


async def test_the_inbox_is_filtered_by_queue(
    db_session: AsyncSession, task: Task, task_actor: Actor, main_actor: Actor, queue: Queue
) -> None:
    other_queue = await queues_service.create_queue(
        db_session, actor=main_actor, key="OPS", title="Эксплуатация", description=""
    )
    other = await tasks_service.create_task(
        db_session,
        actor=task_actor,
        queue=other_queue,
        title="Задача в другой очереди",
        description="Есть",
    )
    await service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=["owner"],
        title="Вопрос в TRK",
        blocking=False,
    )
    await service.ask(
        db_session,
        other,
        actor=task_actor,
        addressees=["owner"],
        title="Вопрос в OPS",
        blocking=False,
    )

    page = await service.list_questions(db_session, actor=task_actor, queue=other_queue)

    assert [item.entry.title for item in page.items] == ["Вопрос в OPS"]
    assert [item.task_key for item in page.items] == ["OPS-1"]


async def test_the_addressee_filter_resolves_the_name_rather_than_matching_it_blindly(
    db_session: AsyncSession, task: Task, task_actor: Actor, owner: Participant
) -> None:
    """Опечатка в имени иначе дала бы пустую входящую, неотличимую от «вопросов нет»."""
    with pytest.raises(ParticipantNotFoundError):
        await service.list_questions(db_session, actor=task_actor, addressee="ghost")

    assert owner.name == "owner"
