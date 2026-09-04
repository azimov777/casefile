"""Первый экран: `GET /api/v1/bootstrap`.

Эндпоинт ничего не считает сам — он складывает три существующих сценария. Поэтому
проверяется не арифметика, а то, ради чего он заведён: один запрос отдаёт всё, чем
интерфейс рисует первый кадр, и ничего сверх этого.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.authors import ACTOR_LABEL_HEADER
from app.services import case as case_service
from app.services.auth import Actor

#: Поля первого экрана. Список закрытый: «ничего сверх этого» — это ограничение задачи,
#: и поле, добавленное мимо него, обязано уронить тест, а не тихо уехать во фронтенд.
BOOTSTRAP_FIELDS = ["open_questions", "participant", "queues"]


async def test_bootstrap_answers_with_the_participant_queues_and_question_count(
    auth_client: AsyncClient,
    owner: Participant,
    queue: Queue,
) -> None:
    """Обзорная проверка 4: один запрос отдаёт всё, чем рисуется первый кадр."""
    response = await auth_client.get("/api/v1/bootstrap")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert sorted(data) == BOOTSTRAP_FIELDS
    assert data["participant"]["name"] == owner.name
    assert data["participant"]["kind"] == owner.kind.value
    assert [item["key"] for item in data["queues"]] == [queue.key]
    assert data["open_questions"] == 0


async def test_bootstrap_counts_only_open_questions_addressed_to_the_participant(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    task_actor: Actor,
    owner: Participant,
    task: Task,
) -> None:
    """Счётчик — то же число, что показывает «входящая», и он падает после ответа.

    Проверяются оба перехода сразу: вопрос без ответа считается, отвеченный — нет.
    Иначе счётчик, который просто считает все вопросы задачи, прошёл бы половину теста.
    """
    question = await case_service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=[owner.name],
        title="Какой ключ канонический?",
        blocking=True,
    )

    asked = await auth_client.get("/api/v1/bootstrap")
    assert asked.json()["data"]["open_questions"] == 1

    await case_service.answer(
        db_session, task, actor=task_actor, question_no=question.no, body="Верхний регистр"
    )
    answered = await auth_client.get("/api/v1/bootstrap")

    assert answered.json()["data"]["open_questions"] == 0


async def test_bootstrap_of_a_shared_token_has_no_participant(
    client: AsyncClient,
    db_session: AsyncSession,
    task_actor: Actor,
    owner: Participant,
    task: Task,
    shared_secret: str,
) -> None:
    """У общего агентского токена участника нет, и вопросов ему прийти не может.

    Ноль здесь — не умолчание и не пустой список вместо отказа: адресовать временного
    агента запрещено концепцией (3.6), поэтому число вопросов к нему равно нулю по
    определению. Очереди при этом отдаются те же самые: они не зависят от того, кто
    спрашивает.
    """
    await case_service.ask(
        db_session,
        task,
        actor=task_actor,
        addressees=[owner.name],
        title="Вопрос владельцу",
        blocking=False,
    )
    client.headers["Authorization"] = f"Bearer {shared_secret}"
    client.headers[ACTOR_LABEL_HEADER] = "nightly_agent"

    response = await client.get("/api/v1/bootstrap")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["participant"] is None
    assert data["open_questions"] == 0
    assert [item["key"] for item in data["queues"]] == [task.queue.key]
