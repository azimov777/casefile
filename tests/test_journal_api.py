"""Лента журнала через HTTP: хвост по номеру, фильтры, страницы, отказы.

Обзорные проверки задачи 26, кроме тех, которым нужны настоящие параллельные
транзакции: ожидание, гонка и поток живут в `test_journal_wait.py` и
`test_journal_stream.py`.

Сквозной номер `seq` выдаёт база и не откатывает: последовательность общая на весь
прогон, и в откатившейся транзакции номера всё равно сгорают. Поэтому здесь нигде нет
ожидаемых чисел — только «больше, чем было» и «в том же порядке». Тест, написанный на
абсолютных номерах, проходил бы поодиночке и падал в наборе.
"""

from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.journal import MAX_WAIT_SECONDS
from app.services import case as case_service
from app.services import tasks as tasks_service
from app.services.auth import Actor

JOURNAL = "/api/v1/journal"


@dataclass(frozen=True, slots=True)
class Written:
    """Что тест подшил и с какой позиции его хвост начинается."""

    start: int
    other_task: Task
    question: Entry
    answer: Entry
    note: Entry
    other_question: Entry


@pytest.fixture
async def written(
    db_session: AsyncSession,
    task_actor: Actor,
    queue: Queue,
    task: Task,
    owner: Participant,
) -> Written:
    """Пять записей в двух задачах: хватает и на фильтры, и на две страницы.

    Позиция `start` — номер записи `created` первой задачи: всё, что подшито тестом,
    лежит строго после неё, а всё, что до, — чужое из общей последовательности.
    """
    created = await case_service.read_entry(db_session, task, 1, actor=task_actor)
    other_task = await tasks_service.create_task(
        db_session,
        actor=task_actor,
        queue=queue,
        title="Вторая задача очереди",
        description="Нужна, чтобы фильтр по задаче было чем провалить",
    )
    question = await case_service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=[owner.name],
        title="Ключи выдавать до или после валидации?",
        blocking=True,
    )
    answer = await case_service.answer(
        db_session, task, actor=task_actor, question_no=question.no, body="После"
    )
    note = await case_service.add_entry(
        db_session,
        task,
        actor=task_actor,
        type=EntryType.NOTE,
        title="Заметка на полях",
    )
    other_question = await case_service.ask(
        db_session,
        other_task,
        actor=task_actor,
        addressees=[owner.name],
        title="Вопрос другой задачи",
        blocking=False,
    )
    other_answer = await case_service.answer(
        db_session, other_task, actor=task_actor, question_no=other_question.no
    )
    assert other_answer.seq > note.seq
    return Written(
        start=created.seq,
        other_task=other_task,
        question=question,
        answer=answer,
        note=note,
        other_question=other_question,
    )


# --- Хвост по номеру ------------------------------------------------------------------


async def test_the_tail_holds_only_entries_after_the_given_number(
    auth_client: AsyncClient,
    written: Written,
) -> None:
    """Обзорная проверка 1: `after=N` отдаёт только `seq > N`, по возрастанию."""
    response = await auth_client.get(JOURNAL, params={"after": written.start})

    assert response.status_code == 200, response.text
    seqs = [item["seq"] for item in response.json()["data"]]
    assert seqs == sorted(seqs)
    assert min(seqs) > written.start
    assert written.question.seq in seqs


async def test_the_page_size_is_respected_and_has_more_is_honest(
    auth_client: AsyncClient,
    written: Written,
) -> None:
    """Обзорная проверка 1: `limit` соблюдается, `meta.has_more` верен.

    Курсор проверяется здесь же: страница, продолженная им, не повторяет и не теряет
    записей — а это и есть единственный способ прочитать ленту целиком.
    """
    first = await auth_client.get(JOURNAL, params={"after": written.start, "limit": 2})
    payload = first.json()

    assert len(payload["data"]) == 2
    assert payload["meta"]["has_more"] is True
    assert payload["meta"]["next_cursor"] is not None

    second = await auth_client.get(
        JOURNAL, params={"cursor": payload["meta"]["next_cursor"], "limit": 200}
    )
    tail = second.json()
    seqs = [item["seq"] for item in payload["data"]] + [item["seq"] for item in tail["data"]]

    assert seqs == sorted(set(seqs))
    assert tail["meta"]["has_more"] is False
    assert tail["meta"]["next_cursor"] is None


async def test_the_end_of_the_journal_is_an_empty_collection(
    auth_client: AsyncClient,
    written: Written,
) -> None:
    """«Ничего не случилось» — это `data: []`, а не пустое тело и не ошибка."""
    response = await auth_client.get(JOURNAL, params={"after": written.other_question.seq + 100})

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "meta": {"next_cursor": None, "has_more": False, "total": None},
    }


async def test_every_entry_carries_the_key_of_its_task(
    auth_client: AsyncClient,
    written: Written,
    task: Task,
) -> None:
    """Кадр ленты нечем адресовать без ключа: у записи есть только `task_id`."""
    response = await auth_client.get(JOURNAL, params={"after": written.start})
    keys = {item["task_key"] for item in response.json()["data"]}

    assert keys == {task.key, written.other_task.key}


# --- Фильтры ------------------------------------------------------------------------


async def test_the_type_and_task_filters_narrow_together(
    auth_client: AsyncClient,
    written: Written,
    task: Task,
) -> None:
    """Обзорная проверка 4: `types=answer&task=TRK-1` пропускает чужое и лишнее."""
    response = await auth_client.get(
        JOURNAL,
        params={"after": written.start, "types": ["answer"], "task": task.key},
    )
    data = response.json()["data"]

    assert [item["seq"] for item in data] == [written.answer.seq]
    assert data[0]["type"] == "answer"
    assert data[0]["task_key"] == task.key


async def test_the_queue_filter_keeps_the_whole_queue(
    auth_client: AsyncClient,
    written: Written,
    queue: Queue,
) -> None:
    """Фильтр по очереди берёт записи всех её задач: у записи очереди нет, она у задачи."""
    response = await auth_client.get(
        JOURNAL, params={"after": written.start, "queue": queue.key.lower()}
    )
    seqs = [item["seq"] for item in response.json()["data"]]

    assert written.question.seq in seqs
    assert written.other_question.seq in seqs


async def test_several_types_are_joined_by_or(
    auth_client: AsyncClient,
    written: Written,
) -> None:
    response = await auth_client.get(
        JOURNAL, params={"after": written.start, "types": ["question", "note"]}
    )
    types = {item["type"] for item in response.json()["data"]}

    assert types == {"question", "note"}


async def test_an_unknown_task_is_refused_rather_than_answered_with_an_empty_tail(
    auth_client: AsyncClient,
) -> None:
    """Пустая лента на опечатку в ключе неотличима от «ничего не происходит».

    Ждущий на такой ленте висел бы до таймаута, считая установку спящей, и чинил бы не
    то. Поэтому несуществующий ключ — отказ.
    """
    response = await auth_client.get(JOURNAL, params={"task": "TRK-9999"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"


# --- Границы ожидания -----------------------------------------------------------------


async def test_a_wait_above_the_ceiling_is_refused_with_the_ceiling_in_details(
    auth_client: AsyncClient,
) -> None:
    """Обзорная проверка 3: `wait=600` — это `422`, и потолок виден в `details`."""
    response = await auth_client.get(JOURNAL, params={"wait": 600})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    ceilings = [
        item["ctx"]["le"] for item in error["details"]["errors"] if item.get("ctx", {}).get("le")
    ]
    assert MAX_WAIT_SECONDS in ceilings, error["details"]


async def test_a_zero_wait_answers_right_away(
    auth_client: AsyncClient,
    written: Written,
) -> None:
    """Значение по умолчанию — не ждать: лента прежде всего читается хвостом."""
    response = await auth_client.get(JOURNAL, params={"after": written.start, "wait": 0})

    assert response.status_code == 200
    assert response.json()["data"]


# --- Поток: то, что видно без чтения потока -------------------------------------------


async def test_a_malformed_last_event_id_is_refused_before_the_stream_starts(
    auth_client: AsyncClient,
) -> None:
    """Отказ после первого отданного байта клиент увидел бы как обрыв без объяснения."""
    response = await auth_client.get(f"{JOURNAL}/stream", headers={"Last-Event-ID": "seventeen"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_journal_cursor"
