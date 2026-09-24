"""Идемпотентность создающих вызовов: повтор возвращает первый ответ, а не второй объект.

Проверки идут через HTTP на транзакции теста: она общая у всех запросов фикстуры `app`,
поэтому строка ключа, занятая первым запросом, видна второму — ровно как зафиксированная
строка видна следующему запросу в бою. Всё, что требует **разных** транзакций (гонка
одновременных повторов и освобождение ключа при откате), живёт в
`tests/test_idempotency_race.py`: на общей сессии такая проверка была бы зелёной и на
сломанном коде.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.idempotency import IdempotencyKey
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.idempotency import IDEMPOTENCY_KEY_HEADER, KEY_TTL, MAX_KEY_LENGTH

KEY = "0f6f1e2c-8f2a-4d5e-9a1b-2c3d4e5f6071"


def with_key(key: str, *, secret: str | None = None) -> dict[str, str]:
    """Заголовки одного вызова: ключ идемпотентности и, если нужно, другой токен."""
    headers = {IDEMPOTENCY_KEY_HEADER: key}
    if secret is not None:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def task_body(project: Project, title: str = "Починить выдачу ключей") -> dict[str, Any]:
    return {"project": project.key, "title": title, "description": "Ключ сгорает на отказе"}


async def stored_keys(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(IdempotencyKey)) or 0


async def task_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Task)) or 0


# --- Повтор ------------------------------------------------------------------------


async def test_the_same_key_and_body_create_one_task(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Обзорная проверка 1: две задачи не заводятся, ответы совпадают целиком."""
    body = task_body(project)

    first = await auth_client.post("/api/v1/tasks", json=body, headers=with_key(KEY))
    second = await auth_client.post("/api/v1/tasks", json=body, headers=with_key(KEY))

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    # Побайтово, а не по ключу задачи: повтор обязан отдать **тот же** ответ, включая
    # отметки времени и версию, — иначе клиент увидит два разных состояния одного объекта.
    assert second.json() == first.json()
    assert first.json()["data"]["key"] == f"{project.key}-1"
    assert await task_count(db_session) == 1


async def test_the_same_key_with_another_body_is_a_conflict(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Обзорная проверка 2: ключ обещает «тот же вызов», и обещание проверяется."""
    await auth_client.post("/api/v1/tasks", json=task_body(project), headers=with_key(KEY))

    response = await auth_client.post(
        "/api/v1/tasks",
        json=task_body(project, title="Совсем другая задача"),
        headers=with_key(KEY),
    )

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "idempotency_key_reused"
    assert error["details"]["first_operation"] == "create_task"
    assert await task_count(db_session) == 1


async def test_the_same_key_on_another_operation_is_a_conflict(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Имя операции входит в отпечаток: иначе повтор получил бы ответ чужого действия."""
    await auth_client.post("/api/v1/tasks", json=task_body(project), headers=with_key(KEY))

    response = await auth_client.post(
        "/api/v1/projects",
        json={"key": "OPS", "title": "Эксплуатация"},
        headers=with_key(KEY),
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "idempotency_key_reused"


async def test_keys_of_two_tokens_are_independent(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    main_secret: str,
    task_secret: str,
) -> None:
    """Обзорная проверка 3: ключ живёт в паре с токеном."""
    body = task_body(project)

    first = await auth_client.post(
        "/api/v1/tasks", json=body, headers=with_key(KEY, secret=main_secret)
    )
    second = await auth_client.post(
        "/api/v1/tasks", json=body, headers=with_key(KEY, secret=task_secret)
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["data"]["key"] != second.json()["data"]["key"]
    assert await task_count(db_session) == 2


async def test_without_the_header_the_repeat_creates_a_second_task(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Без заголовка поведение обычное: механизм не включается сам по себе."""
    body = task_body(project)

    await auth_client.post("/api/v1/tasks", json=body)
    await auth_client.post("/api/v1/tasks", json=body)

    assert await task_count(db_session) == 2
    assert await stored_keys(db_session) == 0


# --- Срок жизни --------------------------------------------------------------------


async def test_an_expired_key_does_not_stop_a_new_object(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Обзорная проверка 6: ключ старше срока жизни не отвечает повтором."""
    body = task_body(project)
    await auth_client.post("/api/v1/tasks", json=body, headers=with_key(KEY))
    record = (await db_session.scalars(select(IdempotencyKey))).one()
    record.created_at = datetime.now(UTC) - KEY_TTL - timedelta(minutes=1)
    await db_session.flush()

    response = await auth_client.post("/api/v1/tasks", json=body, headers=with_key(KEY))

    assert response.status_code == 201, response.text
    assert response.json()["data"]["key"] == f"{project.key}-2"
    assert await task_count(db_session) == 2


async def test_writing_a_key_sweeps_the_expired_ones(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Уборка идёт попутно: фонового процесса, который снимал бы ключи, в трекере нет."""
    await auth_client.post("/api/v1/tasks", json=task_body(project), headers=with_key(KEY))
    stale = (await db_session.scalars(select(IdempotencyKey))).one()
    stale.created_at = datetime.now(UTC) - KEY_TTL - timedelta(minutes=1)
    await db_session.flush()

    await auth_client.post(
        "/api/v1/tasks",
        json=task_body(project, title="Другая задача"),
        headers=with_key("another-key"),
    )

    keys = (await db_session.scalars(select(IdempotencyKey.key))).all()
    assert list(keys) == ["another-key"]


# --- Форма ключа -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "reason"),
    [("   ", "empty"), ("x" * (MAX_KEY_LENGTH + 1), "too_long")],
)
async def test_a_malformed_key_is_rejected(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    key: str,
    reason: str,
) -> None:
    """Отказ, а не молчаливый пропуск: иначе клиент считал бы вызов защищённым."""
    response = await auth_client.post(
        "/api/v1/tasks", json=task_body(project), headers=with_key(key)
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_idempotency_key"
    assert response.json()["error"]["details"]["reason"] == reason
    assert await task_count(db_session) == 0


async def test_a_key_is_matched_after_trimming(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Ключ, скопированный с переводом строки, остаётся тем же ключом."""
    body = task_body(project)

    await auth_client.post("/api/v1/tasks", json=body, headers=with_key(KEY))
    response = await auth_client.post("/api/v1/tasks", json=body, headers=with_key(f" {KEY} "))

    assert response.status_code == 201, response.text
    assert await task_count(db_session) == 1


# --- Остальные создающие маршруты --------------------------------------------------


async def test_issuing_a_token_twice_returns_the_same_secret(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Обзорная проверка 5: секрет нельзя собрать заново, поэтому хранится ответ целиком."""
    body = {"name": "release-bot on ci", "scope": "task"}

    first = await auth_client.post("/api/v1/tokens", json=body, headers=with_key(KEY))
    second = await auth_client.post("/api/v1/tokens", json=body, headers=with_key(KEY))

    assert first.status_code == 201, first.text
    assert second.json() == first.json()
    assert second.json()["data"]["secret"] == first.json()["data"]["secret"]
    tokens = await db_session.scalar(select(func.count()).select_from(IdempotencyKey))
    assert tokens == 1


async def test_appending_an_entry_twice_appends_one(
    auth_client: AsyncClient,
    task: Task,
) -> None:
    """Повтор не подшивает вторую копию записи: дело неизменяемо и чистить его нечем."""
    body = {"type": "note", "title": "Заметка", "body": "Проверил вручную"}

    first = await auth_client.post(
        f"/api/v1/tasks/{task.key}/entries", json=body, headers=with_key(KEY)
    )
    second = await auth_client.post(
        f"/api/v1/tasks/{task.key}/entries", json=body, headers=with_key(KEY)
    )

    assert first.status_code == 201, first.text
    assert second.json() == first.json()
    listing = await auth_client.get(f"/api/v1/tasks/{task.key}/entries", params={"types": "note"})
    assert len(listing.json()["data"]) == 1


async def test_the_same_entry_key_in_another_task_is_a_conflict(
    auth_client: AsyncClient,
    project: Project,
    task: Task,
) -> None:
    """Ключ задачи входит в отпечаток: без него повтор подшил бы запись не в то дело."""
    body = {"type": "note", "title": "Заметка", "body": "Проверил вручную"}
    await auth_client.post(f"/api/v1/tasks/{task.key}/entries", json=body, headers=with_key(KEY))
    other = await auth_client.post("/api/v1/tasks", json=task_body(project, title="Вторая задача"))
    other_key = other.json()["data"]["key"]

    response = await auth_client.post(
        f"/api/v1/tasks/{other_key}/entries", json=body, headers=with_key(KEY)
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "idempotency_key_reused"


async def test_a_repeated_link_answers_with_the_first_one(
    auth_client: AsyncClient,
    project: Project,
    task: Task,
) -> None:
    """Повтор связи отвечает связью, а не `link_exists`: вызов тот же самый."""
    other = await auth_client.post("/api/v1/tasks", json=task_body(project, title="Вторая"))
    other_key = other.json()["data"]["key"]
    body = {"kind": "blocks", "other": other_key}

    first = await auth_client.post(
        f"/api/v1/tasks/{task.key}/links", json=body, headers=with_key(KEY)
    )
    second = await auth_client.post(
        f"/api/v1/tasks/{task.key}/links", json=body, headers=with_key(KEY)
    )

    assert first.status_code == 201, first.text
    assert second.json() == first.json()


async def test_a_repeated_project_answers_with_the_first_one(auth_client: AsyncClient) -> None:
    """Повтор создания проекта отвечает проектом, а не `project_key_taken`."""
    body = {"key": "OPS", "title": "Эксплуатация"}

    first = await auth_client.post("/api/v1/projects", json=body, headers=with_key(KEY))
    second = await auth_client.post("/api/v1/projects", json=body, headers=with_key(KEY))

    assert first.status_code == 201, first.text
    assert second.json() == first.json()


async def test_a_repeated_participant_answers_with_the_first_one(
    auth_client: AsyncClient,
) -> None:
    """То же у участника: повтор не спорит с уникальностью имени."""
    body = {"kind": "agent", "name": "release_bot", "description": "Выкладка"}

    first = await auth_client.post("/api/v1/participants", json=body, headers=with_key(KEY))
    second = await auth_client.post("/api/v1/participants", json=body, headers=with_key(KEY))

    assert first.status_code == 201, first.text
    assert second.json() == first.json()


# --- Отказ ключ не занимает --------------------------------------------------------


async def test_a_rejected_request_stores_nothing(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
) -> None:
    """Отказ до занятия ключа: несуществующий проект не тратит ключ.

    Отказ **после** занятия ключа снимает строку откатом транзакции — это видно только
    на настоящих транзакциях, и проверяет это `tests/test_idempotency_race.py`.
    """
    response = await auth_client.post(
        "/api/v1/tasks",
        json={"project": "NOPE", "title": "Задача", "description": "Есть"},
        headers=with_key(KEY),
    )

    assert response.status_code == 404, response.text
    assert await stored_keys(db_session) == 0
