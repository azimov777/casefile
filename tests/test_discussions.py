"""Обсуждения (TRK-669, решение проекта `TRK#51`): сущность, дело с итогом, привязка
задач, ожидание и закрытие, REST.

Обзорная проверка 1 задачи называет правила, на каждое здесь свой тест: вход в работу
при вопросе без ответа в привязанном обсуждении — `task_has_open_blocking_questions`, после
ответа — принят; закрытие и отмена задачи при незакрытом обсуждении —
`task_has_open_discussions`; закрытие обсуждения при вопросе без ответа —
`discussion_has_open_questions`; любая запись и привязка в закрытом — `discussion_closed`;
итог с пустой частью — `entry_fields_invalid`; «чей ход» — все три значения.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discussion import Discussion
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import EntryRepository
from app.domain.authors import label_author
from app.domain.case import (
    AttachmentFacts,
    DiscussionEntryRef,
    DiscussionRef,
    EntryType,
    parse_ref,
)
from app.domain.discussions import (
    DiscussionOrder,
    DiscussionStatus,
    DiscussionTurn,
    parse_discussion_address,
)
from app.domain.errors import (
    DiscussionClosedError,
    DiscussionHasOpenQuestionsError,
    DiscussionNotFoundError,
    DiscussionTaskExistsError,
    DiscussionTaskNotFoundError,
    EntryFieldsInvalidError,
    InvalidDiscussionAddressError,
    ProjectArchivedError,
    ProjectNotFoundError,
    TaskClosedError,
    TaskHasOpenBlockingQuestionsError,
    TaskHasOpenDiscussionsError,
)
from app.domain.fields import FieldProblem
from app.domain.tasks import TaskStatus
from app.services import case as case_service
from app.services import discussions as service
from app.services import journal as journal_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from conftest import make_task

#: Агент обсуждений: временный, подписанный меткой, — род `agent`, в отличие от владельца.
AGENT = Actor(author=label_author("discussion_bot"))


async def _task(
    session: AsyncSession, actor: Actor, project: Project, title: str, *, to: TaskStatus
) -> Task:
    """Задача проекта в нужном статусе, исполнитель — владелец (`owner`), как у фикстуры;
    область — `core` проекта (`make_task`: новой задаче она обязательна, TRK-677)."""
    task = await make_task(
        session,
        actor=actor,
        project=project,
        title=title,
        description="описание",
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
        assignee="owner",
    )
    if to is not TaskStatus.BACKLOG:
        await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.OPEN)
    if to is TaskStatus.IN_PROGRESS:
        await tasks_service.transition_task(session, task, actor=actor, to=TaskStatus.IN_PROGRESS)
    return task


async def _asked(
    session: AsyncSession, project: Project, *, tasks: list[Task] | None = None
) -> Discussion:
    """Обсуждение, заведённое агентом вопросом владельцу: запись №1 — `created`, №2 —
    вопрос."""
    return await service.create_discussion(
        session,
        actor=AGENT,
        project=project,
        title="Хранить ли дела отменённых задач вечно?",
        opening=EntryType.QUESTION,
        body="Концепция говорит «записи постоянны».",
        addressees=["owner"],
        tasks=tasks or [],
    )


async def _answer(
    session: AsyncSession, discussion: Discussion, actor: Actor, question_no: int = 2
) -> Any:
    return await case_service.append_discussion_entry(
        session,
        discussion,
        actor=actor,
        type=EntryType.ANSWER,
        body="Вечно",
        payload={"question_no": question_no},
    )


async def _close(session: AsyncSession, discussion: Discussion) -> Any:
    return await service.close_discussion(
        session,
        discussion,
        actor=AGENT,
        decided="Храним вечно",
        superseded="ничего",
        open="ничего",
    )


async def _entries(session: AsyncSession, discussion: Discussion) -> list[Any]:
    page = await case_service.list_discussion_entries(session, discussion, actor=AGENT, limit=200)
    return list(page.items)


async def _turn(session: AsyncSession, discussion: Discussion) -> DiscussionTurn | None:
    return (await service.read_discussion(session, discussion, actor=AGENT)).turn


# --- Адрес и карточка -------------------------------------------------------------------


def test_the_address_reads_softly_by_case_and_strictly_by_form() -> None:
    """`trk~7` — тот же адрес, что `TRK~7`; `TRK~07`, `TRK~0` и `TRK-7` — не адреса."""
    address = parse_discussion_address(" trk~7 ")
    assert (address.project_key, address.number, str(address)) == ("TRK", 7, "TRK~7")
    for wrong in ("TRK~07", "TRK~0", "TRK-7", "TRK~", "~7", "TRK~7#1"):
        with pytest.raises(InvalidDiscussionAddressError):
            parse_discussion_address(wrong)


def test_a_reference_names_a_discussion_and_its_entry() -> None:
    """`TRK~7` и `TRK~7#3` — ссылки трекера; URL с тильдой в пути — по-прежнему URL."""
    assert parse_ref("trk~7") == DiscussionRef(project_key="TRK", number=7)
    assert parse_ref("TRK~7#3") == DiscussionEntryRef(project_key="TRK", number=7, no=3)
    assert parse_ref("https://example.com/~user#3") is None
    with pytest.raises(FieldProblem):
        parse_ref("TRK~7#0")


async def test_a_discussion_is_numbered_inside_its_project_and_read_by_its_address(
    db_session: AsyncSession, project: Project
) -> None:
    """Номер — внутри проекта, адрес — `TRK~N`; первая запись — `created`, вторая — вопрос с
    заголовком обсуждения и `blocking: true`, которого никто не присылал."""
    first = await _asked(db_session, project)
    second = await service.create_discussion(
        db_session,
        actor=AGENT,
        project=project,
        title="  Второй вопрос  ",
        opening=EntryType.NOTE,
    )

    assert (first.address, second.address) == ("TRK~1", "TRK~2")
    assert second.title == "Второй вопрос"
    assert (await service.get_discussion(db_session, "trk~2")).id == second.id
    with pytest.raises(DiscussionNotFoundError):
        await service.get_discussion(db_session, "TRK~9")
    with pytest.raises(ProjectNotFoundError):
        await service.get_discussion(db_session, "NOPE~1")
    with pytest.raises(InvalidDiscussionAddressError):
        await service.get_discussion(db_session, "TRK-1")

    created, question = await _entries(db_session, first)
    assert (created.type, created.no, created.title) == (EntryType.CREATED, 1, "Discussion created")
    assert (question.type, question.no, question.title) == (EntryType.QUESTION, 2, first.title)
    assert question.payload == {"addressees": ["owner"], "blocking": True}
    assert (created.discussion_id, created.task_id, created.project_id) == (first.id, None, None)


async def test_a_title_on_two_lines_is_refused_as_an_entry_title(
    db_session: AsyncSession, project: Project
) -> None:
    """Название обсуждения — заголовок первой записи: та же форма и тот же отказ."""
    with pytest.raises(EntryFieldsInvalidError) as error:
        await service.create_discussion(
            db_session,
            actor=AGENT,
            project=project,
            title="line one\nline two",
            opening=EntryType.NOTE,
        )
    assert [item["field"] for item in error.value.details["fields"]] == ["title"]

    with pytest.raises(EntryFieldsInvalidError) as summary:
        await service.create_discussion(
            db_session, actor=AGENT, project=project, title="сводкой", opening=EntryType.SUMMARY
        )
    assert summary.value.details["fields"][0]["field"] == "type"


# --- Ожидание и закрытие задачи -----------------------------------------------------


async def test_a_question_in_an_attached_discussion_holds_the_way_into_work(
    db_session: AsyncSession, task_actor: Actor, project: Project, task: Task
) -> None:
    """Проверка 1: вопрос без ответа в привязанном обсуждении — вход в работу отклонён,
    адрес вопроса `TRK~1#2` в `details.questions`; ответ — вход принят, без перехода.

    Заведение вопросом привязывает задачу тем же действием: `attached` в делах обеих
    сторон с одним `action_id`. Признаки карточки и строки поиска считают вопрос
    обсуждения одинаково."""
    await tasks_service.transition_task(db_session, task, actor=task_actor, to=TaskStatus.OPEN)
    discussion = await _asked(db_session, project, tasks=[task])

    in_discussion = [
        e for e in await _entries(db_session, discussion) if e.type is EntryType.ATTACHED
    ]
    in_task = (await EntryRepository(db_session).headings(task.id))[-1]
    assert len(in_discussion) == 1
    assert in_discussion[0].payload == {"task": task.key, "discussion": "TRK~1"}
    assert in_discussion[0].title == f"Task attached: {task.key}"
    assert in_task.type is EntryType.ATTACHED
    assert in_task.title == "Attached to discussion TRK~1"
    assert in_task.facts == AttachmentFacts(
        type=EntryType.ATTACHED, task_key=task.key, discussion="TRK~1"
    )
    assert in_task.action_id == in_discussion[0].action_id

    package = await tasks_service.read_task_package(db_session, task.key, actor=task_actor)
    assert (package.features.open_questions, package.features.open_blocking_questions) == (1, 1)
    found = await search_service.search_tasks(
        db_session, actor=task_actor, query=f"key: {task.key} and open_blocking_questions: 1"
    )
    assert [row.task.key for row in found.page.items] == [task.key]
    assert found.page.items[0].features == package.features

    with pytest.raises(TaskHasOpenBlockingQuestionsError) as error:
        await tasks_service.transition_task(
            db_session, task, actor=task_actor, to=TaskStatus.IN_PROGRESS
        )
    assert error.value.details["questions"] == ["TRK~1#2"]

    await _answer(db_session, discussion, task_actor)
    assert task.status is TaskStatus.OPEN, "ответ статус не меняет"
    await tasks_service.transition_task(
        db_session, task, actor=task_actor, to=TaskStatus.IN_PROGRESS
    )
    assert task.status is TaskStatus.IN_PROGRESS


async def test_an_open_discussion_keeps_the_task_from_closing_and_cancelling(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Проверка 1: `close_task` и отмена при незакрытом обсуждении —
    `task_has_open_discussions` с адресом; после закрытия обсуждения — закрытие принято."""
    closing = await _task(db_session, task_actor, project, "закрыть", to=TaskStatus.IN_PROGRESS)
    cancelling = await _task(db_session, task_actor, project, "отменить", to=TaskStatus.OPEN)
    discussion = await service.create_discussion(
        db_session,
        actor=AGENT,
        project=project,
        title="Как закрывать?",
        opening=EntryType.NOTE,
        tasks=[closing, cancelling],
    )

    with pytest.raises(TaskHasOpenDiscussionsError) as cancel:
        await tasks_service.transition_task(
            db_session, cancelling, actor=task_actor, to=TaskStatus.CANCELLED, reason="не нужна"
        )
    assert cancel.value.details["discussions"] == ["TRK~1"]

    with pytest.raises(TaskHasOpenDiscussionsError) as close:
        await tasks_service.close_task(
            db_session,
            closing,
            actor=task_actor,
            summary=case_service.SummaryFiling(
                done="сделано",
                remaining="ничего",
                blockers="ничего",
                next_step="нет",
                unmeasured="ничего",
            ),
            verdicts=[case_service.VerdictFiling(check_no=1, outcome="passed", evidence="ок")],
        )
    assert close.value.details["discussions"] == ["TRK~1"]
    assert closing.status is TaskStatus.IN_PROGRESS

    await _close(db_session, discussion)
    await tasks_service.close_task(
        db_session,
        closing,
        actor=task_actor,
        summary=case_service.SummaryFiling(
            done="сделано",
            remaining="ничего",
            blockers="ничего",
            next_step="нет",
            unmeasured="ничего",
        ),
        verdicts=[case_service.VerdictFiling(check_no=1, outcome="passed", evidence="ок")],
    )
    assert closing.status is TaskStatus.DONE
    await tasks_service.transition_task(
        db_session, cancelling, actor=task_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )
    assert cancelling.status is TaskStatus.CANCELLED


# --- Закрытие обсуждения ----------------------------------------------------------------


async def test_closing_with_an_unanswered_question_is_refused(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Проверка 1: вопрос без ответа — `discussion_has_open_questions`, адрес вопроса в
    `details`; снятый вопрос закрыт ответом и закрытию не мешает. Закрытие подшивает итог
    и `closed` одним действием и ставит `closed_at`."""
    discussion = await _asked(db_session, project)

    with pytest.raises(DiscussionHasOpenQuestionsError) as error:
        await _close(db_session, discussion)
    assert error.value.details == {"key": "TRK~1", "questions": ["TRK~1#2"]}
    assert discussion.status is DiscussionStatus.OPEN

    await case_service.append_discussion_entry(
        db_session,
        discussion,
        actor=AGENT,
        type=EntryType.ANSWER,
        body="Вопрос устарел",
        payload={"question_no": 2, "outcome": "withdrawn"},
    )
    closure = await _close(db_session, discussion)

    conclusion, closed = closure.entries
    assert (conclusion.type, conclusion.title) == (EntryType.CONCLUSION, "Храним вечно")
    assert conclusion.payload == {
        "decided": "Храним вечно",
        "superseded": "ничего",
        "open": "ничего",
    }
    assert (closed.type, closed.payload) == (EntryType.CLOSED, {"conclusion_no": conclusion.no})
    assert conclusion.action_id == closed.action_id
    assert discussion.status is DiscussionStatus.CLOSED
    assert discussion.closed_at == closed.created_at


async def test_a_conclusion_with_an_empty_part_is_refused(
    db_session: AsyncSession, project: Project
) -> None:
    """Проверка 1: итог с пустой частью — `entry_fields_invalid` с именами частей, и при
    закрытии, и подшивкой; «ничего» — законное значение."""
    discussion = await service.create_discussion(
        db_session, actor=AGENT, project=project, title="Итог?", opening=EntryType.NOTE
    )

    with pytest.raises(EntryFieldsInvalidError) as closing:
        await service.close_discussion(
            db_session, discussion, actor=AGENT, decided="", superseded="ничего", open="  "
        )
    assert {(item["field"], item["reason"]) for item in closing.value.details["fields"]} == {
        ("decided", "required"),
        ("open", "required"),
    }
    assert discussion.status is DiscussionStatus.OPEN

    with pytest.raises(EntryFieldsInvalidError) as filing:
        await case_service.append_discussion_entry(
            db_session,
            discussion,
            actor=AGENT,
            type=EntryType.CONCLUSION,
            payload={"decided": "да", "superseded": "ничего"},
        )
    assert [item["field"] for item in filing.value.details["fields"]] == ["open"]

    filed = await case_service.add_conclusion(
        db_session, discussion, actor=AGENT, decided="да", superseded="ничего", open="ничего"
    )
    assert filed.type is EntryType.CONCLUSION


async def test_a_closed_discussion_is_frozen(
    db_session: AsyncSession, task_actor: Actor, project: Project, task: Task
) -> None:
    """Проверка 1: в закрытое — ни записи, ни привязки, ни отвязки, ни второго закрытия."""
    attached = await _task(db_session, task_actor, project, "привязанная", to=TaskStatus.OPEN)
    discussion = await service.create_discussion(
        db_session,
        actor=AGENT,
        project=project,
        title="Закрыть?",
        opening=EntryType.NOTE,
        tasks=[attached],
    )
    await _close(db_session, discussion)

    with pytest.raises(DiscussionClosedError) as error:
        await case_service.append_discussion_entry(
            db_session, discussion, actor=task_actor, type=EntryType.NOTE, title="ещё"
        )
    assert error.value.details == {"key": "TRK~1"}
    with pytest.raises(DiscussionClosedError):
        await _answer(db_session, discussion, task_actor, question_no=1)
    with pytest.raises(DiscussionClosedError):
        await service.attach_task(db_session, discussion, task, actor=task_actor)
    with pytest.raises(DiscussionClosedError):
        await service.detach_task(db_session, discussion, attached, actor=task_actor)
    with pytest.raises(DiscussionClosedError):
        await _close(db_session, discussion)
    assert [entry.type for entry in await _entries(db_session, discussion)][-2:] == [
        EntryType.CONCLUSION,
        EntryType.CLOSED,
    ]


# --- Чей ход ----------------------------------------------------------------------------


async def test_whose_turn_takes_all_three_values(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Проверка 1: `human` — есть вопрос без ответа; `agent` — после последнего итога ответ
    или запись человека; иначе и у закрытого — `null`. Список отбирает по тому же признаку."""
    discussion = await service.create_discussion(
        db_session, actor=AGENT, project=project, title="Чей ход?", opening=EntryType.NOTE
    )
    assert await _turn(db_session, discussion) is None, "записка агента хода никому не даёт"

    question = await case_service.append_discussion_entry(
        db_session,
        discussion,
        actor=AGENT,
        type=EntryType.QUESTION,
        title="Решаем?",
        payload={"addressees": ["owner"]},
    )
    assert await _turn(db_session, discussion) is DiscussionTurn.HUMAN

    await _answer(db_session, discussion, task_actor, question_no=question.no)
    assert await _turn(db_session, discussion) is DiscussionTurn.AGENT

    await case_service.add_conclusion(
        db_session, discussion, actor=AGENT, decided="да", superseded="ничего", open="ничего"
    )
    assert await _turn(db_session, discussion) is None, "итог отвечает на всё, что было до него"

    await case_service.append_discussion_entry(
        db_session, discussion, actor=task_actor, type=EntryType.NOTE, title="Добавлю ещё вот что"
    )
    assert await _turn(db_session, discussion) is DiscussionTurn.AGENT

    for turn, expected in ((DiscussionTurn.AGENT, ["TRK~1"]), (DiscussionTurn.HUMAN, [])):
        page = await service.list_discussions(db_session, actor=AGENT, turn=turn)
        assert [row.discussion.address for row in page.items] == expected

    await _close(db_session, discussion)
    assert await _turn(db_session, discussion) is None
    detail = await service.read_discussion(db_session, discussion, actor=AGENT)
    assert (detail.open_questions, detail.conclusion is not None) == (0, True)


# --- Привязка ---------------------------------------------------------------------------


async def test_attaching_follows_the_rules_of_a_dependency(
    db_session: AsyncSession, task_actor: Actor, project: Project, task: Task
) -> None:
    """Закрытую задачу не привязать (`task_closed`), повтор — `discussion_task_exists`,
    отвязка непривязанной — `discussion_task_not_found`; отвязка пишет `detached` в оба
    дела и отпускает задачу."""
    discussion = await _asked(db_session, project)
    cancelled = await _task(db_session, task_actor, project, "отменённая", to=TaskStatus.OPEN)
    await tasks_service.transition_task(
        db_session, cancelled, actor=task_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )

    with pytest.raises(TaskClosedError):
        await service.attach_task(db_session, discussion, cancelled, actor=task_actor)
    with pytest.raises(DiscussionTaskNotFoundError):
        await service.detach_task(db_session, discussion, task, actor=task_actor)

    attachment = await service.attach_task(db_session, discussion, task, actor=task_actor)
    assert (attachment.task.key, attachment.discussion_id) == (task.key, discussion.id)
    with pytest.raises(DiscussionTaskExistsError):
        await service.attach_task(db_session, discussion, task, actor=task_actor)
    package = await tasks_service.read_task_package(db_session, task.key, actor=task_actor)
    assert package.features.open_blocking_questions == 1

    await service.detach_task(db_session, discussion, task, actor=task_actor)
    detail = await service.read_discussion(db_session, discussion, actor=task_actor)
    assert detail.attachments == []
    last = (await EntryRepository(db_session).headings(task.id))[-1]
    assert (last.type, last.title) == (EntryType.DETACHED, "Detached from discussion TRK~1")
    assert (await _entries(db_session, discussion))[-1].type is EntryType.DETACHED
    package = await tasks_service.read_task_package(db_session, task.key, actor=task_actor)
    assert package.features.open_blocking_questions == 0


# --- Дело обсуждения --------------------------------------------------------------------


async def test_the_discussion_case_takes_its_own_entry_types(
    db_session: AsyncSession, task_actor: Actor, project: Project, task: Task
) -> None:
    """В деле обсуждения — вопрос, ответ, заметка и итог; `blocking` не принимается; итог в
    деле задачи и сводка в деле обсуждения — `not_allowed`; ответ — на вопрос этого
    обсуждения."""
    discussion = await _asked(db_session, project)

    def reasons(error: pytest.ExceptionInfo[EntryFieldsInvalidError]) -> set[tuple[str, str]]:
        return {(item["field"], item["reason"]) for item in error.value.details["fields"]}

    with pytest.raises(EntryFieldsInvalidError) as summary:
        await case_service.append_discussion_entry(
            db_session, discussion, actor=AGENT, type=EntryType.SUMMARY, payload={}
        )
    assert ("type", "not_allowed") in reasons(summary)

    with pytest.raises(EntryFieldsInvalidError) as blocking:
        await case_service.append_discussion_entry(
            db_session,
            discussion,
            actor=AGENT,
            type=EntryType.QUESTION,
            title="ещё",
            payload={"addressees": ["owner"], "blocking": False},
        )
    assert reasons(blocking) == {("blocking", "not_allowed")}

    with pytest.raises(EntryFieldsInvalidError) as conclusion:
        await case_service.append_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.CONCLUSION,
            payload={"decided": "да", "superseded": "нет", "open": "нет"},
        )
    assert ("type", "not_allowed") in reasons(conclusion)

    with pytest.raises(EntryFieldsInvalidError) as created:
        await _answer(db_session, discussion, task_actor, question_no=1)
    assert reasons(created) == {("question_no", "not_a_question")}
    with pytest.raises(EntryFieldsInvalidError) as missing:
        await _answer(db_session, discussion, task_actor, question_no=99)
    assert reasons(missing) == {("question_no", "unknown_entry")}

    answer = await _answer(db_session, discussion, task_actor)
    assert answer.title == "Answer to TRK~1#2"


async def test_references_to_a_discussion_are_checked(
    db_session: AsyncSession, task_actor: Actor, project: Project, task: Task
) -> None:
    """`TRK~1` и `TRK~1#2` принимаются в `refs` любого дела и хранятся канонически;
    несуществующие — `unknown_discussion`, `unknown_entry`, `unknown_project`."""
    await _asked(db_session, project)

    filed = await case_service.add_entry(
        db_session,
        task,
        actor=task_actor,
        type=EntryType.NOTE,
        title="ссылки",
        refs=["trk~1", "TRK~1#2"],
    )
    assert filed.refs == ["TRK~1", "TRK~1#2"]

    with pytest.raises(EntryFieldsInvalidError) as error:
        await case_service.add_entry(
            db_session,
            task,
            actor=task_actor,
            type=EntryType.NOTE,
            title="ссылки",
            refs=["TRK~9", "TRK~1#99", "NOPE~1"],
        )
    assert [(item["reason"], item["ref"]) for item in error.value.details["fields"]] == [
        ("unknown_discussion", "TRK~9"),
        ("unknown_entry", "TRK~1#99"),
        ("unknown_project", "NOPE~1"),
    ]


# --- Список, лента, архив -----------------------------------------------------------------


async def test_the_list_filters_by_status_task_project_and_order(
    db_session: AsyncSession, main_actor: Actor, task_actor: Actor, project: Project, task: Task
) -> None:
    """Отбор по статусу, задаче и проекту, порядок от старых и от свежих; обсуждения
    архивного проекта — только с названным проектом."""
    first = await _asked(db_session, project, tasks=[task])
    second = await service.create_discussion(
        db_session, actor=AGENT, project=project, title="второе", opening=EntryType.NOTE
    )
    await _close(db_session, second)
    other = await projects_service.create_project(
        db_session, actor=main_actor, key="OPS", title="Соседний"
    )
    third = await service.create_discussion(
        db_session, actor=AGENT, project=other, title="третье", opening=EntryType.NOTE
    )

    async def addresses(**filters: Any) -> list[str]:
        page = await service.list_discussions(db_session, actor=AGENT, **filters)
        return [row.discussion.address for row in page.items]

    # Тест идёт одной транзакцией, и `now()` у всех трёх один: порядок между проектами
    # решает идентификатор, поэтому он сверяется внутри проекта, где его держит номер.
    assert sorted(await addresses()) == ["OPS~1", "TRK~1", "TRK~2"]
    assert await addresses(project=project) == ["TRK~1", "TRK~2"]
    assert await addresses(project=project, order=DiscussionOrder.NEWEST) == ["TRK~2", "TRK~1"]
    assert sorted(await addresses(status=DiscussionStatus.OPEN)) == ["OPS~1", "TRK~1"]
    assert await addresses(task=task) == ["TRK~1"]
    assert await addresses(project=other) == ["OPS~1"]
    rows = (await service.list_discussions(db_session, actor=AGENT, project=project)).items
    assert [(row.turn, row.open_questions) for row in rows] == [
        (DiscussionTurn.HUMAN, 1),
        (None, 0),
    ]

    page = await service.list_discussions(db_session, actor=AGENT, project=project, limit=1)
    following = await service.list_discussions(
        db_session, actor=AGENT, project=project, limit=1, cursor=page.next_cursor
    )
    assert [row.discussion.id for row in [*page.items, *following.items]] == [first.id, second.id]
    assert following.next_cursor is None

    await projects_service.archive_project(db_session, other, actor=main_actor, reason="пауза")
    assert await addresses() == ["TRK~1", "TRK~2"]
    assert await addresses(project=other) == ["OPS~1"]
    with pytest.raises(ProjectArchivedError):
        await case_service.append_discussion_entry(
            db_session, third, actor=AGENT, type=EntryType.NOTE, title="в архиве"
        )


async def test_the_journal_names_discussion_entries_and_follows_attached_tasks(
    db_session: AsyncSession, task_actor: Actor, project: Project, task: Task
) -> None:
    """Запись обсуждения — в ленте с его адресом; отбор по задаче берёт и дела обсуждений,
    к которым она привязана: ответ на вопрос ждут по задаче."""
    discussion = await _asked(db_session, project, tasks=[task])
    start = await EntryRepository(db_session).latest_seq()
    answer = await _answer(db_session, discussion, task_actor)

    by_task = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, task=task.key),
        after=start,
    )
    by_project = await journal_service.read_journal(
        db_session,
        actor=task_actor,
        journal_filter=await journal_service.resolve_filter(db_session, project="TRK"),
        after=start,
    )

    for page in (by_task, by_project):
        assert [
            (i.entry.id, i.task_key, i.project_key, i.area, i.discussion) for i in page.items
        ] == [(answer.id, None, None, None, "TRK~1")]


async def test_the_first_screen_counts_discussions_waiting_on_a_human(
    db_session: AsyncSession, task_actor: Actor, project: Project
) -> None:
    """Значок входящей: незакрытые обсуждения с ходом за человеком."""
    assert await service.count_waiting_on_humans(db_session) == 0
    discussion = await _asked(db_session, project)
    await service.create_discussion(
        db_session, actor=task_actor, project=project, title="записка", opening=EntryType.NOTE
    )
    assert await service.count_waiting_on_humans(db_session) == 1
    await _answer(db_session, discussion, task_actor)
    assert await service.count_waiting_on_humans(db_session) == 0


# --- REST -------------------------------------------------------------------------------


async def test_rest_creates_reads_lists_and_files_into_a_discussion(
    auth_client: AsyncClient, project: Project, task: Task
) -> None:
    """«Новое обсуждение» запиской с привязкой, экран обсуждения, список с отбором, формы
    «Заметка» и «Ответить», привязать и отвязать — то, что вызывает интерфейс."""
    created = await auth_client.post(
        "/api/v1/discussions",
        json={
            "project": "trk",
            "title": "Где хранить итог?",
            "body": "Контекст",
            "tasks": [task.key],
        },
        headers={"Idempotency-Key": "d15c0000-0000-4000-8000-000000000001"},
    )
    assert created.status_code == 201, created.text
    card = created.json()["data"]
    assert (card["address"], card["number"], card["status"], card["turn"]) == (
        "TRK~1",
        1,
        "open",
        "agent",  # записка человека — ход за агентом
    )
    assert [item["key"] for item in card["tasks"]] == [task.key]
    assert (card["conclusion"], card["open_questions"], card["closed_at"]) == (None, 0, None)

    read = await auth_client.get("/api/v1/discussions/trk~1")
    assert read.status_code == 200, read.text
    assert read.json()["data"]["title"] == "Где хранить итог?"

    listed = await auth_client.get(
        "/api/v1/discussions", params={"status": "open", "turn": "agent", "task": task.key}
    )
    assert listed.status_code == 200, listed.text
    assert [item["address"] for item in listed.json()["data"]] == ["TRK~1"]
    empty = await auth_client.get("/api/v1/discussions", params={"turn": "human"})
    assert empty.json()["data"] == []

    note = await auth_client.post(
        "/api/v1/discussions/TRK~1/entries", json={"type": "note", "title": "Заметка"}
    )
    assert note.status_code == 201, note.text
    assert (note.json()["data"]["discussion"], note.json()["data"]["task_key"]) == ("TRK~1", None)
    answer = await auth_client.post(
        "/api/v1/discussions/TRK~1/entries",
        json={"type": "answer", "payload": {"question_no": 2}, "body": "да"},
    )
    assert answer.status_code == 422, answer.text
    assert answer.json()["error"]["code"] == "entry_fields_invalid"
    question = await auth_client.post(
        "/api/v1/discussions/TRK~1/entries",
        json={"type": "question", "title": "Вопрос?", "payload": {"addressees": ["owner"]}},
    )
    assert question.status_code == 422, "вопрос в REST не подшивают: вопросы задаёт агент"

    entries = await auth_client.get("/api/v1/discussions/TRK~1/entries")
    assert entries.status_code == 200, entries.text
    assert [(item["type"], item["discussion"]) for item in entries.json()["data"]] == [
        ("created", "TRK~1"),
        ("note", "TRK~1"),
        ("attached", "TRK~1"),
        ("note", "TRK~1"),
    ]

    again = await auth_client.post("/api/v1/discussions/TRK~1/tasks", json={"task": task.key})
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "discussion_task_exists"
    detached = await auth_client.delete(f"/api/v1/discussions/TRK~1/tasks/{task.key}")
    assert detached.status_code == 204, detached.text
    missing = await auth_client.delete(f"/api/v1/discussions/TRK~1/tasks/{task.key}")
    assert missing.json()["error"]["code"] == "discussion_task_not_found"
    attached = await auth_client.post("/api/v1/discussions/TRK~1/tasks", json={"task": task.key})
    assert attached.status_code == 201, attached.text
    assert (attached.json()["data"]["key"], attached.json()["data"]["status"]) == (
        task.key,
        "backlog",
    )


async def test_rest_names_its_refusals(
    db_session: AsyncSession, auth_client: AsyncClient, project: Project, task: Task
) -> None:
    """Адрес не по форме — `422`, неизвестный — `404`; запись в закрытое — `409
    discussion_closed`; первый экран считает обсуждения, ждущие человека."""
    bad = await auth_client.get("/api/v1/discussions/TRK-1")
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "invalid_discussion_address")
    unknown = await auth_client.get("/api/v1/discussions/TRK~9")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "discussion_not_found")

    discussion = await _asked(db_session, project)
    first_screen = await auth_client.get("/api/v1/bootstrap")
    assert first_screen.json()["data"]["open_discussions"] == 1

    await _answer(db_session, discussion, AGENT)
    await _close(db_session, discussion)
    closed = await auth_client.post(
        "/api/v1/discussions/TRK~1/entries", json={"type": "note", "title": "поздно"}
    )
    assert (closed.status_code, closed.json()["error"]["code"]) == (409, "discussion_closed")
    detail = (await auth_client.get("/api/v1/discussions/TRK~1")).json()["data"]
    assert detail["status"] == "closed"
    assert detail["conclusion"]["payload"]["decided"] == "Храним вечно"
    assert detail["conclusion"]["discussion"] == "TRK~1"
