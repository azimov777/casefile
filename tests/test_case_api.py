"""Эндпоинты дела: обзорные проверки задачи 23 через HTTP.

Полный цикл «вход, работа, выход, проверка» проходится здесь целиком через REST — так,
как его пройдёт агент.
"""

from typing import Any

from httpx import AsyncClient

from app.db.models.queue import Queue
from app.domain.case import SERVICE_ENTRY_TYPES

READY = {
    "queue": "trk",
    "title": "Починить выдачу ключей",
    "description": "Ключ сгорает на неудачном запросе",
    "goal": "Ключи не сгорают",
    "context": "Номер выдаёт очередь",
    "constraints": "Счётчик не переписывать",
    "output": "Тест на несгоревший номер",
    "checks": ["Создание задачи без названия не тратит номер"],
}

SUMMARY = {
    "done": "Разобрался, где сгорает номер",
    "remaining": "Перенести выдачу номера",
    "blockers": "нет",
    "next_step": "Перенести вызов в конец create_task\nи дописать тест",
}


async def create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/tasks", json={**READY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def append(client: AsyncClient, key: str, **entry: Any) -> dict[str, Any]:
    response = await client.post(f"/api/v1/tasks/{key}/entries", json=entry)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def refuse(client: AsyncClient, key: str, **entry: Any) -> dict[str, Any]:
    response = await client.post(f"/api/v1/tasks/{key}/entries", json=entry)
    assert response.status_code == 422, response.text
    return response.json()["error"]


async def transition(client: AsyncClient, key: str, to: str, **body: Any) -> Any:
    return await client.post(f"/api/v1/tasks/{key}/transition", json={"to": to, **body})


async def move(client: AsyncClient, key: str, *statuses: str, reason: str | None = None) -> None:
    for status in statuses:
        response = await transition(client, key, status, reason=reason)
        assert response.status_code == 200, response.text


async def package(client: AsyncClient, key: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/tasks/{key}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- Сводка ---------------------------------------------------------------------------


async def test_a_summary_needs_four_parts_and_is_titled_by_its_next_step(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 1."""
    await create(auth_client)

    refused = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries",
        json={"type": "summary", "payload": {**SUMMARY, "next_step": ""}},
    )
    assert refused.status_code == 422, refused.text

    entry = await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)

    assert entry["type"] == "summary"
    assert entry["payload"] == SUMMARY
    assert entry["title"] == "Перенести вызов в конец create_task"
    index = (await package(auth_client, "TRK-1"))["index"]
    assert index[-1]["title"] == "Перенести вызов в конец create_task"


async def test_leaving_in_progress_without_a_summary_is_refused(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 2."""
    await create(auth_client)
    await move(auth_client, "TRK-1", "open", "in_progress")

    refused = await transition(auth_client, "TRK-1", "open", reason="Нужны уточнения")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "summary_required"
    assert error["details"]["from"] == "in_progress"

    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)
    passed = await transition(auth_client, "TRK-1", "open", reason="Нужны уточнения")
    assert passed.status_code == 200, passed.text
    assert passed.json()["data"]["status"] == "open"


async def test_a_summary_of_the_previous_stint_does_not_count(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 3: задача, взятая повторно, старой справкой не закрывается."""
    await create(auth_client)
    await move(auth_client, "TRK-1", "open", "in_progress")
    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)
    await move(auth_client, "TRK-1", "open", reason="Жду ответа")
    await move(auth_client, "TRK-1", "in_progress")

    refused = await transition(auth_client, "TRK-1", "open", reason="Снова уточнения")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "summary_required"

    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)
    passed = await transition(auth_client, "TRK-1", "open", reason="Снова уточнения")
    assert passed.status_code == 200, passed.text


# --- Вопросы, ответы, вердикты --------------------------------------------------------


async def test_a_question_to_someone_outside_the_registry_is_refused(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 4: имя несуществующего адресата — в подробностях."""
    await create(auth_client)

    error = await refuse(
        auth_client,
        "TRK-1",
        type="question",
        title="Чей вердикт нужен?",
        payload={"addressees": ["owner", "ghost"], "blocking": False},
    )

    assert error["code"] == "entry_fields_invalid"
    assert error["details"]["fields"] == [
        {"field": "addressees", "reason": "unknown_participant", "name": "ghost"}
    ]


async def test_an_answer_to_something_that_is_not_a_question_is_refused(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 5."""
    await create(auth_client)
    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)

    error = await refuse(auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": 2})
    assert error["details"]["fields"][0]["reason"] == "not_a_question"

    missing = await refuse(
        auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": 99}
    )
    assert missing["details"]["fields"][0]["reason"] == "unknown_entry"


async def test_a_verdict_outside_the_check_range_names_the_range(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 6: у задачи три проверки, вердикт по пятой отвергается."""
    await create(auth_client, checks=["первая", "вторая", "третья"])

    error = await refuse(
        auth_client, "TRK-1", type="verdict", payload={"check_no": 5, "outcome": "passed"}
    )

    assert error["details"]["fields"] == [
        {"field": "check_no", "reason": "out_of_range", "min": 1, "max": 3, "got": 5}
    ]


async def test_closing_needs_a_passing_verdict_on_every_check(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 7: полный цикл до `done` через REST."""
    await create(auth_client, checks=["первая", "вторая"])
    await move(auth_client, "TRK-1", "open", "in_progress")
    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)

    await append(auth_client, "TRK-1", type="verdict", payload={"check_no": 1, "outcome": "passed"})
    await append(
        auth_client,
        "TRK-1",
        type="verdict",
        body="Прогон красный",
        payload={"check_no": 2, "outcome": "failed"},
    )

    refused = await transition(auth_client, "TRK-1", "done")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "checks_not_passed"
    assert error["details"]["checks"] == [{"check_no": 2, "reason": "failed"}]

    await append(
        auth_client,
        "TRK-1",
        type="verdict",
        body="Прогон зелёный",
        payload={"check_no": 2, "outcome": "passed"},
    )
    passed = await transition(auth_client, "TRK-1", "done")
    assert passed.status_code == 200, passed.text
    assert passed.json()["data"]["status"] == "done"


# --- Пакет преемника ------------------------------------------------------------------


async def test_the_package_shows_the_summary_and_questions_in_full_and_the_rest_as_headings(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 8."""
    await create(auth_client)
    await append(auth_client, "TRK-1", type="decision", title="Решил так", body="Длинное тело")
    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)
    answered = await append(
        auth_client,
        "TRK-1",
        type="question",
        title="Первый вопрос",
        payload={"addressees": ["owner"], "blocking": True},
    )
    await append(
        auth_client,
        "TRK-1",
        type="question",
        title="Второй вопрос",
        body="Подробности",
        payload={"addressees": ["owner"], "blocking": False},
    )
    await append(
        auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": answered["no"]}
    )

    data = await package(auth_client, "TRK-1")

    assert data["summary"]["payload"] == SUMMARY
    assert [question["title"] for question in data["questions"]] == ["Второй вопрос"]
    assert data["questions"][0]["body"] == "Подробности"
    # Последняя запись агента — ответ: он подшит последним, и служебных записей
    # после него нет. Признак берётся из описи, а не выписывается числом: так он
    # остаётся верным, если в расстановку добавят ещё запись.
    last_agent = [
        heading
        for heading in data["index"]
        if heading["type"] not in {item.value for item in SERVICE_ENTRY_TYPES}
    ][-1]
    assert data["features"] == {
        "blocked": False,
        "open_questions": 1,
        "open_blocking_questions": 0,
        "last_summary_at": data["summary"]["created_at"],
        "last_entry_at": last_agent["created_at"],
    }
    assert [heading["no"] for heading in data["index"]] == [1, 2, 3, 4, 5, 6]
    for heading in data["index"]:
        assert sorted(heading) == ["author", "created_at", "facts", "no", "title", "type"]


# --- Чтение записей -------------------------------------------------------------------


async def test_entries_are_read_by_number_type_and_position(
    auth_client: AsyncClient, queue: Queue
) -> None:
    await create(auth_client)
    await append(auth_client, "TRK-1", type="summary", payload=SUMMARY)
    await append(auth_client, "TRK-1", type="note", title="Заметка")

    async def numbers(**params: Any) -> list[int]:
        response = await auth_client.get("/api/v1/tasks/TRK-1/entries", params=params)
        assert response.status_code == 200, response.text
        return [entry["no"] for entry in response.json()["data"]]

    assert await numbers() == [1, 2, 3]
    assert await numbers(types=["summary"]) == [2]
    assert await numbers(after_no=2) == [3]
    assert await numbers(nos=[1, 3]) == [1, 3]

    one = await auth_client.get("/api/v1/tasks/TRK-1/entries/2")
    assert one.status_code == 200, one.text
    assert one.json()["data"]["payload"] == SUMMARY

    missing = await auth_client.get("/api/v1/tasks/TRK-1/entries/99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "entry_not_found"


async def test_a_reference_must_exist_while_an_address_is_taken_as_is(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Обзорная проверка 10."""
    await create(auth_client)

    error = await refuse(auth_client, "TRK-1", type="finding", title="Нашёл", refs=["TRK-1#99"])
    assert error["details"]["fields"] == [
        {"field": "refs", "reason": "unknown_entry", "ref": "TRK-1#99"}
    ]

    entry = await append(
        auth_client,
        "TRK-1",
        type="finding",
        title="Нашёл",
        refs=["trk-1#1", "https://example.com/a#b"],
    )
    assert entry["refs"] == ["TRK-1#1", "https://example.com/a#b"]


async def test_a_note_is_filed_into_a_closed_task(auth_client: AsyncClient, queue: Queue) -> None:
    """Обзорная проверка 11: дело закрытой задачи продолжает пополняться."""
    await create(auth_client)
    await move(auth_client, "TRK-1", "cancelled", reason="Задача снята")

    entry = await append(auth_client, "TRK-1", type="note", title="Всё же пригодилось")

    assert entry["type"] == "note"
    assert (await package(auth_client, "TRK-1"))["task"]["status"] == "cancelled"


# --- Что запрос не принимает ----------------------------------------------------------


async def test_a_service_type_cannot_be_filed_through_the_endpoint(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """Служебные записи подшивает трекер: в объединение запроса их типы не входят."""
    await create(auth_client)

    response = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries",
        json={"type": "status_changed", "title": "Сам перевёл"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_a_derived_title_is_not_accepted_from_the_client(
    auth_client: AsyncClient, queue: Queue
) -> None:
    """У сводки заголовок равен первой строке `next_step`, и второго способа задать его нет."""
    await create(auth_client)

    response = await auth_client.post(
        "/api/v1/tasks/TRK-1/entries",
        json={"type": "summary", "title": "Своя строка", "payload": SUMMARY},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
