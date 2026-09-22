"""Первый экран: `GET /api/v1/bootstrap`.

Эндпоинт ничего не считает сам — он складывает три существующих сценария. Поэтому
проверяется не арифметика, а то, ради чего он заведён: один запрос отдаёт всё, чем
интерфейс рисует первый кадр, и ничего сверх этого.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.authors import ACTOR_LABEL_HEADER
from app.domain.tokens import TokenScope, hash_token
from app.services import bootstrap as bootstrap_service
from app.services import case as case_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR, Actor

#: Поля первого экрана. Список закрытый: «ничего сверх этого» — это ограничение задачи,
#: и поле, добавленное мимо него, обязано уронить тест, а не тихо уехать во фронтенд.
#: `token` вошёл сюда с доводом, почему это первый кадр (`TRK-65#12`); адрес MCP — нет,
#: он живёт в `GET /api/v1/installation`.
BOOTSTRAP_FIELDS = ["account", "open_questions", "participant", "queues", "token"]

#: Поля токена в первом кадре: чем узнать его в списке и что он открывает. Имя, автор
#: выпуска и последнее использование сюда не входят — их отдаёт список по тому же `id`.
TOKEN_FIELDS = ["id", "scope"]


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
    # Учётная запись владельца — администратор: по флагу интерфейс показывает управление
    # людьми (`CONCEPT.md`, 5.4).
    assert data["account"]["email"] == "owner@localhost"
    assert data["account"]["participant"] == owner.name
    assert data["account"]["is_admin"] is True
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
    assert data["account"] is None
    assert data["open_questions"] == 0
    assert [item["key"] for item in data["queues"]] == [task.queue.key]


async def test_bootstrap_names_the_token_of_the_request_not_of_the_participant(
    client: AsyncClient,
    db_session: AsyncSession,
    owner: Participant,
) -> None:
    """Обзорная проверка 1: именной токен `task` и именной `main` — каждый собой.

    Участник у обоих один и тот же, поэтому ни набор, ни идентификатор из участника не
    выводятся: их отдаёт токен, стоящий в заголовке. Ответ, не различающий два токена
    одного участника, провалил бы одну из двух пар. Идентификатор — тот же, что в списке
    токенов: по нему интерфейс узнаёт там свой ключ.
    """
    issued = {
        scope: await tokens_service.issue_token(
            db_session, actor=TRACKER_ACTOR, participant=owner, scope=scope, name=scope.value
        )
        for scope in (TokenScope.TASK, TokenScope.MAIN)
    }

    for scope, token in issued.items():
        response = await client.get(
            "/api/v1/bootstrap", headers={"Authorization": f"Bearer {token.secret}"}
        )

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["participant"]["name"] == owner.name
        assert sorted(data["token"]) == TOKEN_FIELDS
        assert data["token"] == {"id": str(token.token.id), "scope": scope.value}
        assert "trk_" not in response.text
        assert hash_token(token.secret) not in response.text

    listed = await client.get(
        "/api/v1/tokens",
        params={"limit": 200},
        headers={"Authorization": f"Bearer {issued[TokenScope.MAIN].secret}"},
    )
    rows = {row["id"]: row for row in listed.json()["data"]}
    for scope, token in issued.items():
        assert rows[str(token.token.id)]["scope"] == scope.value


@pytest.mark.parametrize("scope", [TokenScope.TASK, TokenScope.MAIN])
async def test_bootstrap_names_the_token_of_a_shared_agent(
    client: AsyncClient,
    db_session: AsyncSession,
    scope: TokenScope,
) -> None:
    """Обзорная проверка 1: у общего агентского токена участника нет, а токен есть.

    Оба набора, а не один: ответ, который выводил бы набор из отсутствия участника
    («нет участника — значит, `task`»), прошёл бы половину проверки.
    """
    issued = await tokens_service.issue_token(
        db_session, actor=TRACKER_ACTOR, scope=scope, name=f"shared {scope.value}"
    )
    client.headers["Authorization"] = f"Bearer {issued.secret}"
    client.headers[ACTOR_LABEL_HEADER] = "nightly_agent"

    response = await client.get("/api/v1/bootstrap")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["participant"] is None
    assert data["token"] == {"id": str(issued.token.id), "scope": scope.value}
    assert "trk_" not in response.text
    assert hash_token(issued.secret) not in response.text


async def test_the_first_screen_of_an_action_without_a_token_is_refused(
    db_session: AsyncSession,
) -> None:
    """Первый экран описывает токен: действию без токена он отказывает, а не отдаёт пустоту.

    Снаружи так не бывает — это действие самого трекера, — и именно поэтому `token` в
    контракте не бывает `null`: клиенту не приходится разбирать случай, которого нет.
    """
    with pytest.raises(UnauthorizedError) as refused:
        await bootstrap_service.read_bootstrap(db_session, actor=TRACKER_ACTOR)

    assert refused.value.details == {"reason": "first_screen_requires_token"}
