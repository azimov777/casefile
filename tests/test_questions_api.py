"""Эндпоинт вопросов: «входящая» участника поперёк задач.

Вопрос — не отдельная сущность, а представление над делом, поэтому проверяется здесь
именно то, что из дела считается: открытость, адресат, признак `blocking`, проект.
"""

from typing import Any

from httpx import AsyncClient
from tests.test_case_api import append, create, package, refuse

from app.db.models.project import Project


async def register(client: AsyncClient, name: str) -> None:
    response = await client.post(
        "/api/v1/participants",
        json={"kind": "agent", "name": name, "description": "Проверяющий"},
    )
    assert response.status_code == 201, response.text


async def ask(client: AsyncClient, key: str, title: str, *, to: str, blocking: bool) -> int:
    entry = await append(
        client,
        key,
        type="question",
        title=title,
        payload={"addressees": [to], "blocking": blocking},
    )
    return entry["no"]


async def questions(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/questions", params=params)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert sorted(payload) == ["data", "meta"]
    return payload["data"]


async def test_the_inbox_keeps_the_open_blocking_questions_of_the_current_participant(
    auth_client: AsyncClient, project: Project
) -> None:
    """Обзорная проверка 9."""
    await register(auth_client, "reviewer")
    await create(auth_client)
    blocking_no = await ask(auth_client, "TRK-1", "Ждёт ответа", to="owner", blocking=True)
    await ask(auth_client, "TRK-1", "Ждать не нужно", to="owner", blocking=False)
    await ask(auth_client, "TRK-1", "Чужой", to="reviewer", blocking=True)

    blocking = await questions(auth_client, blocking=True)
    assert [question["title"] for question in blocking] == ["Ждёт ответа"]
    assert blocking[0]["task_key"] == "TRK-1"
    assert blocking[0]["payload"] == {"addressees": ["owner"], "blocking": True}

    assert [question["title"] for question in await questions(auth_client)] == [
        "Ждёт ответа",
        "Ждать не нужно",
    ]

    await append(
        auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": blocking_no}
    )

    assert await questions(auth_client, blocking=True) == []
    assert [question["title"] for question in await questions(auth_client)] == ["Ждать не нужно"]


async def test_the_answered_questions_are_readable_too(
    auth_client: AsyncClient, project: Project
) -> None:
    """`open=false` — вторая половина выдачи; «все вопросы задачи» читаются из её дела."""
    await create(auth_client)
    no = await ask(auth_client, "TRK-1", "Ждёт ответа", to="owner", blocking=False)
    await append(auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": no})

    assert await questions(auth_client) == []
    assert [question["title"] for question in await questions(auth_client, open=False)] == [
        "Ждёт ответа"
    ]


async def test_the_inbox_is_filtered_by_addressee_and_project(
    auth_client: AsyncClient, project: Project
) -> None:
    await register(auth_client, "reviewer")
    created = await auth_client.post(
        "/api/v1/projects", json={"key": "OPS", "title": "Эксплуатация", "description": ""}
    )
    assert created.status_code == 201, created.text
    core = await auth_client.post(
        "/api/v1/projects/OPS/areas", json={"key": "core", "title": "Основа"}
    )
    assert core.status_code == 201, core.text
    await create(auth_client)
    await create(auth_client, project="OPS", area="OPS/core")
    await ask(auth_client, "TRK-1", "Вопрос в TRK", to="reviewer", blocking=False)
    await ask(auth_client, "OPS-1", "Вопрос в OPS", to="reviewer", blocking=False)

    # Адресация мягкая по регистру — как и везде, где адресуют по имени.
    assert [q["title"] for q in await questions(auth_client, addressee="Reviewer")] == [
        "Вопрос в TRK",
        "Вопрос в OPS",
    ]
    assert [
        q["title"] for q in await questions(auth_client, addressee="reviewer", project="ops")
    ] == ["Вопрос в OPS"]
    assert await questions(auth_client) == []


async def test_an_unknown_addressee_is_a_refusal_rather_than_an_empty_inbox(
    auth_client: AsyncClient, project: Project
) -> None:
    response = await auth_client.get("/api/v1/questions", params={"addressee": "ghost"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "participant_not_found"


async def test_a_shared_agent_token_must_name_the_addressee(
    client: AsyncClient, shared_secret: str, project: Project
) -> None:
    """У временного агента адресата нет: пустой список соврал бы, что вопросов не пришло."""
    client.headers["Authorization"] = f"Bearer {shared_secret}"
    client.headers["X-Actor-Label"] = "nightly_agent"

    refused = await client.get("/api/v1/questions")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "actor_not_addressable"

    named = await client.get("/api/v1/questions", params={"addressee": "owner"})
    assert named.status_code == 200, named.text
    assert named.json()["data"] == []


async def test_a_question_carries_its_answers_in_order_and_only_its_own(
    auth_client: AsyncClient, project: Project
) -> None:
    """История: ответы едут со строкой вопроса, а не отдельным запросом на задачу.

    Номера записей в разных задачах совпадают, поэтому второй задаче задан вопрос с тем
    же номером: ответ первой к нему прилипнуть не должен.
    """
    await create(auth_client)
    await create(auth_client)
    answered = await ask(auth_client, "TRK-1", "Отвеченный", to="owner", blocking=False)
    twin = await ask(auth_client, "TRK-2", "Тот же номер", to="owner", blocking=False)
    assert answered == twin
    first = await append(
        auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": answered}
    )
    second = await append(
        auth_client, "TRK-1", type="answer", body="И ещё", payload={"question_no": answered}
    )

    rows = {row["task_key"]: row for row in await questions(auth_client, open=False)}

    assert [(a["no"], a["body"], a["task_key"]) for a in rows["TRK-1"]["answers"]] == [
        (first["no"], "Да", "TRK-1"),
        (second["no"], "И ещё", "TRK-1"),
    ]
    # Исход и замена лежат в нагрузке всегда (TRK-552): форма ответа одна в любом интерфейсе.
    assert rows["TRK-1"]["answers"][0]["payload"] == {
        "question_no": answered,
        "outcome": "answered",
        "replaced_by": None,
    }
    assert rows["TRK-2"]["answers"] == []
    # Во «входящей» ответов нет по определению: там только открытые вопросы.
    assert [(row["task_key"], row["answers"]) for row in await questions(auth_client)] == [
        ("TRK-2", [])
    ]


async def test_the_newest_order_pages_backwards_with_its_own_cursor(
    auth_client: AsyncClient, project: Project
) -> None:
    await create(auth_client)
    for title in ("Первый", "Второй", "Третий"):
        await ask(auth_client, "TRK-1", title, to="owner", blocking=False)

    first = await auth_client.get(
        "/api/v1/questions", params={"order": "newest", "limit": 2, "open": False}
    )
    assert first.status_code == 200, first.text
    assert [q["title"] for q in first.json()["data"]] == ["Третий", "Второй"]
    cursor = first.json()["meta"]["next_cursor"]
    assert cursor is not None

    rest = await auth_client.get(
        "/api/v1/questions",
        params={"order": "newest", "limit": 2, "open": False, "cursor": cursor},
    )
    assert rest.status_code == 200, rest.text
    assert [q["title"] for q in rest.json()["data"]] == ["Первый"]
    assert rest.json()["meta"]["has_more"] is False

    # Без `order` порядок прежний — «входящая» не изменилась.
    assert [q["title"] for q in await questions(auth_client)] == ["Первый", "Второй", "Третий"]

    # Курсор другого порядка — отказ, а не молча не та страница.
    mixed = await auth_client.get(
        "/api/v1/questions", params={"order": "oldest", "limit": 2, "cursor": cursor}
    )
    assert mixed.status_code == 422
    assert mixed.json()["error"]["code"] == "invalid_cursor"


async def test_any_addressee_drops_the_addressee_filter(
    auth_client: AsyncClient, project: Project
) -> None:
    await register(auth_client, "reviewer")
    await create(auth_client)
    await ask(auth_client, "TRK-1", "Мне", to="owner", blocking=False)
    await ask(auth_client, "TRK-1", "Ему", to="reviewer", blocking=False)

    assert [q["title"] for q in await questions(auth_client)] == ["Мне"]
    assert [q["title"] for q in await questions(auth_client, any_addressee=True)] == [
        "Мне",
        "Ему",
    ]

    both = await auth_client.get(
        "/api/v1/questions", params={"any_addressee": True, "addressee": "reviewer"}
    )
    assert both.status_code == 422
    assert both.json()["error"]["code"] == "addressee_with_any_addressee"


async def test_a_shared_agent_token_may_read_questions_to_anyone(
    client: AsyncClient, shared_secret: str, project: Project
) -> None:
    """Снятое явно условие адресата — не «мне»: отказывать временному агенту не в чем."""
    client.headers["Authorization"] = f"Bearer {shared_secret}"
    client.headers["X-Actor-Label"] = "nightly_agent"

    response = await client.get("/api/v1/questions", params={"any_addressee": True})

    assert response.status_code == 200, response.text
    assert response.json()["data"] == []


# --- Снятие и замена вопроса (TRK-552) ------------------------------------------------


async def case_size(client: AsyncClient, key: str) -> int:
    return len((await package(client, key))["index"])


async def test_a_withdrawn_question_leaves_the_inbox_and_its_history_names_why(
    auth_client: AsyncClient, project: Project
) -> None:
    """(б) и (в) через REST: снятый и заменённый вопрос уходят из входящей и счётчиков,
    а в истории стоят с записью исхода под собой."""
    await create(auth_client)
    dropped = await ask(
        auth_client, "TRK-1", "Нужен ли старый эндпоинт?", to="owner", blocking=True
    )
    stale = await ask(auth_client, "TRK-1", "Какой ключ канонический?", to="owner", blocking=True)
    fresh = await ask(auth_client, "TRK-1", "Верхний годится?", to="owner", blocking=False)
    before = (await package(auth_client, "TRK-1"))["features"]
    assert (before["open_questions"], before["open_blocking_questions"]) == (3, 2)

    withdrawn = await append(
        auth_client,
        "TRK-1",
        type="answer",
        body="Эндпоинт удалён в соседней задаче",
        payload={"question_no": dropped, "outcome": "withdrawn"},
    )
    after_withdrawal = (await package(auth_client, "TRK-1"))["features"]
    assert (after_withdrawal["open_questions"], after_withdrawal["open_blocking_questions"]) == (
        2,
        1,
    )
    replaced = await append(
        auth_client,
        "TRK-1",
        type="answer",
        body="Спрашиваю короче",
        payload={"question_no": stale, "outcome": "replaced", "replaced_by": fresh},
    )

    assert withdrawn["title"] == f"Answer to TRK-1#{dropped}: withdrawn"
    assert replaced["title"] == f"Answer to TRK-1#{stale}: replaced by TRK-1#{fresh}"
    data = await package(auth_client, "TRK-1")
    assert [q["no"] for q in data["questions"]] == [fresh]
    assert (data["features"]["open_questions"], data["features"]["open_blocking_questions"]) == (
        1,
        0,
    )
    facts = {line["no"]: line["facts"] for line in data["index"]}
    assert facts[replaced["no"]] == {
        "type": "answer",
        "question_no": stale,
        "outcome": "replaced",
        "replaced_by": fresh,
    }
    assert [q["no"] for q in await questions(auth_client)] == [fresh]

    rows = {row["no"]: row for row in await questions(auth_client, open=False)}
    assert rows[dropped]["answers"][0]["payload"] == {
        "question_no": dropped,
        "outcome": "withdrawn",
        "replaced_by": None,
    }
    assert rows[dropped]["answers"][0]["body"] == "Эндпоинт удалён в соседней задаче"
    assert rows[stale]["answers"][0]["payload"]["outcome"] == "replaced"
    assert rows[stale]["answers"][0]["payload"]["replaced_by"] == fresh


async def test_every_refusal_of_a_withdrawal_is_named_and_files_nothing(
    auth_client: AsyncClient, project: Project
) -> None:
    """(г) Каждое правило отказывает `entry_fields_invalid` с причиной; дело не растёт."""
    await create(auth_client)
    stale = await ask(auth_client, "TRK-1", "Какой ключ?", to="owner", blocking=False)
    fresh = await ask(auth_client, "TRK-1", "Верхний?", to="owner", blocking=False)
    note = await append(auth_client, "TRK-1", type="note", title="Заметка")
    size = await case_size(auth_client, "TRK-1")

    cases: list[tuple[dict[str, object], str, list[dict[str, object]]]] = [
        (
            {"question_no": stale, "outcome": "withdrawn"},
            "",
            [{"field": "body", "reason": "required", "required_for": "withdrawn"}],
        ),
        (
            {"question_no": stale, "outcome": "replaced"},
            "Причина",
            [{"field": "replaced_by", "reason": "required", "required_for": "replaced"}],
        ),
        (
            {"question_no": stale, "outcome": "withdrawn", "replaced_by": fresh},
            "Причина",
            [
                {
                    "field": "replaced_by",
                    "reason": "not_allowed",
                    "required_for": "replaced",
                    "got": "withdrawn",
                }
            ],
        ),
        (
            {"question_no": stale, "outcome": "replaced", "replaced_by": note["no"]},
            "Причина",
            [
                {
                    "field": "replaced_by",
                    "reason": "not_a_question",
                    "key": "TRK-1",
                    "no": note["no"],
                    "got": "note",
                }
            ],
        ),
        (
            {"question_no": stale, "outcome": "replaced", "replaced_by": 99},
            "Причина",
            [{"field": "replaced_by", "reason": "unknown_entry", "key": "TRK-1", "no": 99}],
        ),
        (
            {"question_no": fresh, "outcome": "replaced", "replaced_by": stale},
            "Причина",
            [
                {
                    "field": "replaced_by",
                    "reason": "not_after_question",
                    "question_no": fresh,
                    "got": stale,
                }
            ],
        ),
        (
            {"question_no": stale, "outcome": "replaced", "replaced_by": stale},
            "Причина",
            [
                {
                    "field": "replaced_by",
                    "reason": "not_after_question",
                    "question_no": stale,
                    "got": stale,
                }
            ],
        ),
    ]
    for payload, body, expected in cases:
        error = await refuse(auth_client, "TRK-1", type="answer", body=body, payload=payload)
        assert error["code"] == "entry_fields_invalid", payload
        assert error["details"]["fields"] == expected, payload
    assert await case_size(auth_client, "TRK-1") == size

    answer = await append(
        auth_client, "TRK-1", type="answer", body="Да", payload={"question_no": stale}
    )
    size = await case_size(auth_client, "TRK-1")
    error = await refuse(
        auth_client,
        "TRK-1",
        type="answer",
        body="Устарел",
        payload={"question_no": stale, "outcome": "withdrawn"},
    )
    assert error["details"]["fields"] == [
        {
            "field": "question_no",
            "reason": "already_answered",
            "key": "TRK-1",
            "no": stale,
            "answer_no": answer["no"],
        }
    ]
    assert await case_size(auth_client, "TRK-1") == size
    rows = {row["no"]: row for row in await questions(auth_client, open=False)}
    assert [a["no"] for a in rows[stale]["answers"]] == [answer["no"]]


async def test_a_repeated_withdrawal_answers_with_the_first_entry(
    auth_client: AsyncClient, project: Project
) -> None:
    """(ж) Повтор с тем же `Idempotency-Key` отдаёт первую запись, а не отказ «уже снят»."""
    await create(auth_client)
    stale = await ask(auth_client, "TRK-1", "Какой ключ?", to="owner", blocking=False)
    headers = {"Idempotency-Key": "c0ffee00-0000-4000-8000-000000000552"}
    entry = {
        "type": "answer",
        "body": "Устарел",
        "payload": {"question_no": stale, "outcome": "withdrawn"},
    }

    first = await auth_client.post("/api/v1/tasks/TRK-1/entries", json=entry, headers=headers)
    again = await auth_client.post("/api/v1/tasks/TRK-1/entries", json=entry, headers=headers)

    assert first.status_code == 201, first.text
    assert again.status_code == 201, again.text
    assert again.json() == first.json()
    rows = {row["no"]: row for row in await questions(auth_client, open=False)}
    assert [a["no"] for a in rows[stale]["answers"]] == [first.json()["data"]["no"]]
