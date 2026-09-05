"""Сквозные сценарии: полный цикл задачи и ожидание ответа.

Отдельно от тестов на слои, и не ради покрытия — оно у слоёв уже есть. Здесь
проверяется то, чего не видит ни один тест на отдельный вызов: **последовательность**.
Цикл задачи это десяток вызовов в определённом порядке, каждый из которых по отдельности
работает, а вместе они обязаны оставить в деле связную историю. Пропущенная служебная
запись, переставленный переход, потерянный автор — всё это видно только на описи
целиком.

## Почему два одинаковых цикла

Главное требование проекта — бизнес-логика не дублируется между REST и MCP
(`CONVENTIONS.md`). Проверяется оно не чтением кода, а тем, что два интерфейса,
пройдя один и тот же цикл, оставляют **одну и ту же опись**. Разойдись они на одном
типе записи — и агент с человеком стали бы видеть разные истории одной задачи.

## Ловушка тестов MCP

Отклонённый вызов откатывает транзакцию теста и устаревает объекты ORM, прочитанные до
него (`tests/conftest.py`, фикстура `mcp_sessions`). Поэтому ключи задач здесь
запоминаются строкой **до** вызова, а не читаются из объекта после.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.domain.case import EntryType
from app.services import case as case_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from conftest import Connect, call

#: Опись задачи, прошедшей полный цикл. Порядок — часть проверки: преемник читает дело
#: сверху вниз, и переставленные страницы означают другую историю.
FULL_CYCLE_INDEX = [
    EntryType.CREATED,
    EntryType.STATUS_CHANGED,  # backlog → open
    EntryType.STATUS_CHANGED,  # open → in_progress
    EntryType.DECISION,
    EntryType.ATTEMPT,
    EntryType.SUMMARY,
    EntryType.VERDICT,
    EntryType.STATUS_CHANGED,  # in_progress → done
]

#: Разделы задачи цикла. Одна проверка — один вердикт: `in_progress → done` требует
#: положительного последнего вердикта по **каждой** проверке.
SECTIONS: dict[str, Any] = {
    "goal": "Ключи не сгорают на отклонённых запросах",
    "context": "Номер выдаёт `queues.next_task_number`",
    "constraints": "Счётчик очереди не переписывать",
    "output": "Тест на несгоревший номер",
    "checks": ["Создание задачи без названия не тратит номер"],
}

SUMMARY: dict[str, str] = {
    "done": "Причина найдена, вызов перенесён",
    "remaining": "Ничего",
    "blockers": "Нет",
    "next_step": "Закрыть задачу",
}


# --- Полный цикл через REST -----------------------------------------------------------


async def test_a_task_goes_the_whole_way_through_rest(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 6: создать, открыть, взять, подшить, свести, проверить, закрыть.

    Каждый шаг — отдельный запрос, как его сделал бы интерфейс или назначатель. Ответ
    каждого проверяется на месте: цикл, упавший на седьмом шаге, должен назвать седьмой
    шаг, а не оставить непонятную опись в конце.
    """
    created = await auth_client.post(
        "/api/v1/tasks",
        json={
            "queue": queue.key,
            "title": "Ключ задачи сгорает на отклонённом запросе",
            "description": "Номер выдаётся до валидации тела",
            **SECTIONS,
        },
    )
    assert created.status_code == 201, created.text
    key = created.json()["data"]["key"]
    assert key.startswith(f"{queue.key}-")

    for target in ("open", "in_progress"):
        moved = await auth_client.post(f"/api/v1/tasks/{key}/transition", json={"to": target})
        assert moved.status_code == 200, moved.text
        assert moved.json()["data"]["status"] == target

    for entry in (
        {"type": "decision", "title": "Номер выдаётся последним шагом", "body": "Дыры допустимы"},
        {"type": "attempt", "title": "Возврат номера при откате не работает", "body": "Гонка"},
    ):
        appended = await auth_client.post(f"/api/v1/tasks/{key}/entries", json=entry)
        assert appended.status_code == 201, appended.text

    summarized = await auth_client.post(
        f"/api/v1/tasks/{key}/entries", json={"type": "summary", "payload": SUMMARY}
    )
    assert summarized.status_code == 201, summarized.text
    # Заголовок сводки не принимается, а выводится из `next_step`: это и есть то, что
    # преемник видит в описи, не читая тела.
    assert summarized.json()["data"]["title"] == SUMMARY["next_step"]

    # Закрыть без вердикта нельзя — проверка стоит здесь, а не в тесте на переходы,
    # потому что в цикле её легко обойти порядком вызовов и не заметить.
    too_early = await auth_client.post(f"/api/v1/tasks/{key}/transition", json={"to": "done"})
    assert too_early.status_code == 409, too_early.text
    assert too_early.json()["error"]["code"] == "checks_not_passed"

    verdict = await auth_client.post(
        f"/api/v1/tasks/{key}/entries",
        json={
            "type": "verdict",
            "body": "Создание без названия отвечает 422, номер не потрачен",
            "payload": {"check_no": 1, "outcome": "passed"},
        },
    )
    assert verdict.status_code == 201, verdict.text

    closed = await auth_client.post(f"/api/v1/tasks/{key}/transition", json={"to": "done"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["data"]["status"] == "done"

    package = (await auth_client.get(f"/api/v1/tasks/{key}")).json()["data"]

    assert [item["type"] for item in package["index"]] == [item.value for item in FULL_CYCLE_INDEX]
    assert package["transitions"] == [], "закрытая задача никуда не переводится"
    assert package["summary"]["payload"] == SUMMARY
    assert package["features"] == {
        "blocked": False,
        "open_questions": 0,
        "open_blocking_questions": 0,
        "last_summary_at": package["summary"]["created_at"],
    }


# --- Тот же цикл через MCP ------------------------------------------------------------


async def test_a_task_goes_the_whole_way_through_mcp(
    mcp_session: Connect, task_secret: str, queue: Queue
) -> None:
    """Обзорная проверка 7: те же шаги инструментами дают ту же опись.

    Ключ очереди запоминается строкой до подключения: сессия MCP коммитит на входе, и
    обращение к полю ORM-объекта после этого ушло бы в базу вне async-контекста.
    """
    queue_key = queue.key

    async with mcp_session(task_secret) as session:
        created = await call(
            session,
            "create_task",
            queue=queue_key,
            title="Ключ задачи сгорает на отклонённом запросе",
            description="Номер выдаётся до валидации тела",
            sections=SECTIONS,
        )
        key = created["key"]
        assert created["status"] == "backlog"

        for target in ("open", "in_progress"):
            moved = await call(session, "transition", key=key, to=target)
            assert moved["status"] == target

        await call(
            session,
            "add_entry",
            key=key,
            type="decision",
            title="Номер выдаётся последним шагом",
            body="Дыры допустимы",
        )
        await call(
            session,
            "add_entry",
            key=key,
            type="attempt",
            title="Возврат номера при откате не работает",
            body="Гонка",
        )
        summarized = await call(session, "add_summary", key=key, **SUMMARY)
        assert summarized["title"] == SUMMARY["next_step"]

        await call(
            session,
            "add_verdict",
            key=key,
            check_no=1,
            outcome="passed",
            evidence="Создание без названия отвечает 422, номер не потрачен",
        )
        closed = await call(session, "transition", key=key, to="done")
        assert closed["status"] == "done"

        package = await call(session, "get_task", key=key)

    assert [item["type"] for item in package["index"]] == [item.value for item in FULL_CYCLE_INDEX]
    assert package["transitions"] == []
    assert package["summary"]["payload"] == SUMMARY


# --- Ожидание ответа на блокирующий вопрос --------------------------------------------

#: Запрос кандидатов назначателя — тот самый, что в `CONCEPT.md`, 4.3.
CANDIDATES = "status: open and blocked: false and open_blocking_questions: 0"


async def test_a_blocking_question_takes_the_task_out_of_the_candidates(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    task_actor: Actor,
    owner: Participant,
    queue: Queue,
) -> None:
    """Обзорная проверка 8: сценарий ожидания из `CONCEPT.md`, 4.6.

    Статуса «жду» в трекере нет: агент задаёт блокирующий вопрос, пишет сводку и
    возвращает задачу в `open`. Назначатель её не берёт, пока вопрос открыт, — не
    потому, что трекер ему запретил, а потому, что его же запрос кандидатов её не
    показывает. После ответа задача возвращается в выдачу сама: признак считается по
    делу, а не хранится флагом.
    """
    task = await tasks_service.create_task(
        db_session,
        actor=task_actor,
        queue=queue,
        title="Удалять ли дела отменённых задач",
        description="Решение принимает владелец, не агент",
        **SECTIONS,
    )
    key = task.key
    await tasks_service.transition_task(db_session, task, actor=task_actor, to="open")
    await tasks_service.transition_task(db_session, task, actor=task_actor, to="in_progress")

    async def candidates() -> list[str]:
        response = await auth_client.get("/api/v1/tasks", params={"query": CANDIDATES})
        assert response.status_code == 200, response.text
        return [item["key"] for item in response.json()["data"]]

    asked = await auth_client.post(
        f"/api/v1/tasks/{key}/entries",
        json={
            "type": "question",
            "title": "Сколько храним дела отменённых задач?",
            "payload": {"addressees": [owner.name], "blocking": True},
        },
    )
    assert asked.status_code == 201, asked.text
    question_no = asked.json()["data"]["no"]

    await auth_client.post(
        f"/api/v1/tasks/{key}/entries", json={"type": "summary", "payload": SUMMARY}
    )
    parked = await auth_client.post(
        f"/api/v1/tasks/{key}/transition",
        json={"to": "open", "reason": "Задан блокирующий вопрос, ждать в работе нечего"},
    )
    assert parked.status_code == 200, parked.text
    assert parked.json()["data"]["status"] == "open"

    assert key not in await candidates(), "задача под блокирующим вопросом ушла в работу"

    inbox = await auth_client.get("/api/v1/questions")
    assert [item["no"] for item in inbox.json()["data"]] == [question_no]

    before = await case_service.list_entries(db_session, task, actor=task_actor, limit=100)
    last_seq = before.items[-1].seq

    answered = await auth_client.post(
        f"/api/v1/tasks/{key}/entries",
        json={
            "type": "answer",
            "body": "Храним вечно: записи постоянны, это решение концепции",
            "payload": {"question_no": question_no},
        },
    )
    assert answered.status_code == 201, answered.text

    assert key in await candidates(), "ответ не вернул задачу в кандидаты"
    assert (await auth_client.get("/api/v1/questions")).json()["data"] == []

    # Лента отдаёт ответ по фильтру типа: именно так назначатель узнаёт, что пора
    # пересчитывать кандидатов, не читая всё подряд.
    feed = await auth_client.get("/api/v1/journal", params={"after": last_seq, "types": ["answer"]})
    assert feed.status_code == 200, feed.text
    entries = feed.json()["data"]
    assert [item["type"] for item in entries] == ["answer"]
    assert entries[0]["task_key"] == key
    assert entries[0]["payload"]["question_no"] == question_no
