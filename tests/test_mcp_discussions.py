"""Обсуждения через MCP (TRK-671, решение проекта TRK#51): вопрос по задаче заводит
обсуждение и привязку, ответ и заметка — по адресу, привязка — `link` видом `attached`,
итог и закрытие — своими инструментами, пакет `get_task` несёт обсуждения задачи.

Вызовы идут настоящим клиентом SDK, как в `tests/test_mcp_tools.py`: половина того, что
может сломаться, — разбор аргументов по схеме и свёртка ответа.
"""

import jsonschema
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.case import EntryType
from app.domain.errors import QuestionNotATaskEntryError
from app.domain.participants import ParticipantKind
from app.services import case as case_service
from app.services import participants as participants_service
from app.services import tasks as tasks_service
from app.services.auth import TRACKER_ACTOR, Actor
from conftest import Connect, call, make_task, refuse, without_empty_standing

QUESTION = "Хранить ли дела отменённых задач вечно?"


@pytest.fixture
async def open_task(db_session: AsyncSession, task_actor: Actor, task: Task) -> Task:
    """Задача `TRK-1` в `open`, исполнитель — владелец."""
    await tasks_service.transition_task(db_session, task, actor=task_actor, to="open")
    return task


async def test_ask_about_a_task_opens_a_discussion_and_attaches_the_task(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Обзорная проверка 1: `ask` с ключом задачи заводит обсуждение этим вопросом и тем же
    вызовом привязывает задачу; в деле задачи вопроса нет, есть `attached`. Вопрос по
    адресу ложится в то же обсуждение, нового не заводит."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        declared = {tool.name: tool for tool in (await session.list_tools()).tools}
        asked = await call(
            session, "ask", key=key, addressees=["owner"], title=QUESTION, body="Сколько?"
        )
        address = asked["discussion"]
        again = await call(
            session, "ask", key=address, addressees=["owner"], title="Архивных тоже?"
        )
        discussion_case = await call(session, "read_project_entries", key=address)
        task_case = await call(session, "read_entries", key=key)
        package = await call(session, "get_task", key=key)

    assert "blocking" not in declared["ask"].input_schema["properties"]
    assert (address, asked["no"], asked["task_key"], asked["title"]) == (
        "TRK~1",
        2,
        None,
        QUESTION,
    )
    # TRK-702: ключ привязанной задачи — в ответе по ключу задачи, не по адресу обсуждения.
    assert asked["attached_task"] == key
    assert (again["discussion"], again["no"], again["attached_task"]) == (address, 4, None)
    assert again["title"] == "Архивных тоже?"
    assert [(item["no"], item["type"]) for item in discussion_case["items"]] == [
        (1, "created"),
        (2, "question"),
        (3, "attached"),
        (4, "question"),
    ]
    question = discussion_case["items"][1]
    assert (question["title"], question["body"], question["discussion"]) == (
        QUESTION,
        "Сколько?",
        address,
    )
    assert question["payload"] == {"addressees": ["owner"], "blocking": True, "options": None}
    assert [item["type"] for item in task_case["items"]][-1] == "attached"
    assert "question" not in {item["type"] for item in task_case["items"]}
    assert task_case["items"][-1]["title"] == f"Attached to discussion {address}"

    (discussion,) = package["discussions"]
    assert {key: discussion[key] for key in ("address", "title", "status", "turn")} == {
        "address": address,
        "title": QUESTION,
        "status": "open",
        "turn": "human",
    }
    assert [item["no"] for item in discussion["open_questions"]] == [2, 4]
    assert discussion["conclusion"] is None
    assert package["questions"] == []
    assert package["features"]["open_questions"] == 2
    assert package["features"]["open_blocking_questions"] == 2
    assert [(item["no"], item["discussion"]) for item in package["state"]["questions"]] == [
        (2, address),
        (4, address),
    ]


async def test_ask_takes_no_blocking_and_repeats_by_its_key(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Признака `blocking` у вопроса больше нет — лишний аргумент отвергается схемой; повтор
    с тем же ключом идемпотентности отвечает первым вопросом и второго обсуждения не
    заводит."""
    key = open_task.key
    arguments = {
        "key": key,
        "addressees": ["owner"],
        "title": QUESTION,
        "idempotency_key": "0b6a1c3e-9f42-4f1e-8a77-3c2d1e0f9a10",
    }
    async with mcp_session(task_secret) as session:
        extra = await refuse(session, "ask", **arguments, blocking=True)
        first = await call(session, "ask", **arguments)
        second = await call(session, "ask", **arguments)
        package = await call(session, "get_task", key=key)

    assert "blocking" in extra
    assert first == second
    assert first["attached_task"] == key
    assert [item["address"] for item in package["discussions"]] == [first["discussion"]]


async def test_a_question_in_a_task_case_is_refused_on_every_path(
    mcp_session: Connect,
    auth_client: AsyncClient,
    db_session: AsyncSession,
    task_secret: str,
    task_actor: Actor,
    open_task: Task,
) -> None:
    """Обзорная проверка 1: вопрос в деле задачи — отказ. Домен отвечает своим кодом
    (`question_not_a_task_entry`) и сценарию записи, и REST; у MCP пути в дело задачи у
    вопроса нет вовсе: `add_entry` и записи `close_task` его типа не знают."""
    key = open_task.key
    with pytest.raises(QuestionNotATaskEntryError) as domain:
        await case_service.append_entry(
            db_session,
            open_task,
            actor=task_actor,
            type=EntryType.QUESTION,
            title="Вопрос?",
            payload={"addressees": ["owner"], "blocking": True},
        )
    rest = await auth_client.post(
        f"/api/v1/tasks/{key}/entries",
        json={
            "type": "question",
            "title": "Вопрос?",
            "payload": {"addressees": ["owner"], "blocking": True},
        },
    )
    async with mcp_session(task_secret) as session:
        by_entry = await refuse(session, "add_entry", key=key, type="question", title="Вопрос?")
        listed = await call(session, "read_entries", key=key)

    assert domain.value.details == {"key": key}
    assert (rest.status_code, rest.json()["error"]["code"]) == (422, "question_not_a_task_entry")
    assert "question" in by_entry
    assert "question" not in {item["type"] for item in listed["items"]}


async def test_get_task_carries_discussions_with_the_latest_conclusion(
    mcp_session: Connect,
    auth_client: AsyncClient,
    task_secret: str,
    open_task: Task,
) -> None:
    """Обзорная проверка 1: пакет несёт обсуждения задачи — адрес, название, статус, чей
    ход, открытые вопросы и последний итог целиком; `state` называет итоги и записи
    человека после последней правки разделов; REST отдаёт то же поле в поле."""
    key = open_task.key
    async with mcp_session(task_secret) as session:
        declared = {tool.name: tool.output_schema for tool in (await session.list_tools()).tools}
        asked = await call(session, "ask", key=key, addressees=["owner"], title=QUESTION)
        address = asked["discussion"]
        answered = await call(
            session, "answer", key=address, question_no=asked["no"], body="Храним вечно"
        )
        replied = await call(session, "get_task", key=key)
        concluded = await call(
            session,
            "add_conclusion",
            key=address,
            decided=f"Храним вечно ({address}#{answered['no']})",
            superseded="ничего",
            open="ничего",
        )
        package = await call(session, "get_task", key=key)

    assert replied["discussions"][0]["turn"] == "agent"
    assert concluded["title"] == f"Храним вечно ({address}#{answered['no']})"
    (discussion,) = package["discussions"]
    assert discussion["turn"] is None
    assert discussion["open_questions"] == []
    conclusion = discussion["conclusion"]
    assert (conclusion["no"], conclusion["type"], conclusion["discussion"]) == (
        concluded["no"],
        "conclusion",
        address,
    )
    assert conclusion["payload"] == {
        "decided": f"Храним вечно ({address}#{answered['no']})",
        "superseded": "ничего",
        "open": "ничего",
    }
    # Вопрос и ответ подписаны человеком (токен владельца), итог — запись, задающая работу.
    assert package["state"]["discussions_after_card"] == [
        f"{address}#{asked['no']}",
        f"{address}#{answered['no']}",
        f"{address}#{concluded['no']}",
    ]
    jsonschema.validate(package, declared["get_task"])
    response = await auth_client.get(f"/api/v1/tasks/{key}")
    assert response.status_code == 200, response.text
    assert package == without_empty_standing(response.json()["data"])


async def test_the_entries_after_the_card_count_from_the_last_section_edit(
    mcp_session: Connect,
    auth_client: AsyncClient,
    task_secret: str,
    task: Task,
) -> None:
    """`discussions_after_card` считается от последней правки разделов, как
    `decisions_after_card`: правка после записи обсуждения её оттуда убирает, записка
    человека после правки — возвращает в список."""
    key = task.key
    async with mcp_session(task_secret) as session:
        asked = await call(session, "ask", key=key, addressees=["owner"], title=QUESTION)
        address = asked["discussion"]
        before = await call(session, "get_task", key=key, brief=True)
        await call(session, "update_task", key=key, changes={"goal": "Новая цель"})
        edited = await call(session, "get_task", key=key, brief=True)
    noted = await auth_client.post(
        f"/api/v1/discussions/{address}/entries",
        json={"type": "note", "title": "Подумал ещё", "body": "Записка человека"},
    )
    assert noted.status_code == 201, noted.text
    async with mcp_session(task_secret) as session:
        after = await call(session, "get_task", key=key, brief=True)

    assert before["state"]["discussions_after_card"] == [f"{address}#{asked['no']}"]
    assert edited["state"]["discussions_after_card"] == []
    assert after["state"]["discussions_after_card"] == [f"{address}#{noted.json()['data']['no']}"]


async def test_link_attaches_and_unlink_detaches_a_task(
    mcp_session: Connect,
    db_session: AsyncSession,
    task_secret: str,
    task_actor: Actor,
    project: Project,
    open_task: Task,
) -> None:
    """Обзорная проверка 1: привязка и отвязка — `link`/`unlink` видом `attached`; записи
    `attached`/`detached` в делах обеих сторон, номера — в ответе. Вид решает, как читать
    `other`: при `attached` — адрес обсуждения, при остальных — ключ задачи."""
    other = await make_task(
        db_session, actor=task_actor, project=project, title="Соседняя", description="Ждёт итога"
    )
    other_key, key = other.key, open_task.key
    async with mcp_session(task_secret) as session:
        asked = await call(session, "ask", key=key, addressees=["owner"], title=QUESTION)
        address = asked["discussion"]
        attached = await call(session, "link", key=other_key, kind="attached", other=address)
        held = await call(session, "get_task", key=other_key, brief=True)
        repeat = await refuse(session, "link", key=other_key, kind="attached", other=address)
        wrong_other = await refuse(session, "link", key=other_key, kind="attached", other=key)
        wrong_kind = await refuse(session, "link", key=other_key, kind="relates", other=address)
        detached = await call(session, "unlink", key=other_key, kind="attached", other=address)
        missing = await refuse(session, "unlink", key=other_key, kind="attached", other=address)
        released = await call(session, "get_task", key=other_key)
        discussion_case = await call(session, "read_project_entries", key=address)
        other_case = await call(session, "read_entries", key=other_key)

    by_no = {item["no"]: item for item in discussion_case["items"]}
    assert attached["key"] == other_key
    assert by_no[attached["other_entry"]]["type"] == "attached"
    assert by_no[detached["other_entry"]]["type"] == "detached"
    own = {item["no"]: item["type"] for item in other_case["items"]}
    assert (own[attached["entry"]], own[detached["entry"]]) == ("attached", "detached")
    assert held["features"]["open_blocking_questions"] == 1
    assert "discussion_task_exists" in repeat
    assert "invalid_discussion_address" in wrong_other
    assert "invalid_task_key" in wrong_kind
    assert "discussion_task_not_found" in missing
    assert released["discussions"] == []
    assert released["features"]["open_blocking_questions"] == 0


async def test_a_note_and_the_case_of_a_discussion_go_through_the_project_tools(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Заметка — `add_project_entry` по адресу, только типа `note`, без `supersedes`; дело —
    `read_project_entries` по адресу с подстрокой; отбора по статусу у обсуждения нет."""
    async with mcp_session(task_secret) as session:
        asked = await call(session, "ask", key=open_task.key, addressees=["owner"], title=QUESTION)
        address = asked["discussion"]
        note = await call(
            session, "add_project_entry", key=address, type="note", title="Справка по теме"
        )
        decision = await refuse(
            session, "add_project_entry", key=address, type="decision", title="Решил"
        )
        replacing = await refuse(
            session, "add_project_entry", key=address, type="note", title="Ещё", supersedes=[5]
        )
        found = await call(session, "read_project_entries", key=address, text="справка")
        in_force = await call(session, "read_project_entries", key=address, in_force=True)

    assert (note["project_key"], note["no"]) == (address, 4)
    assert "not_allowed" in decision and "entry_fields_invalid" in decision
    assert "supersedes" in replacing
    assert [(item["no"], item["type"]) for item in found["items"]] == [(4, "note")]
    assert in_force["items"] == []


async def test_close_discussion_closes_with_a_conclusion_and_frees_the_task(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """Закрытие — итог и `closed` одной транзакцией: при вопросе без ответа отказ, и
    задачу при открытом обсуждении не закрыть; после закрытия обсуждение заморожено."""
    key = open_task.key
    parts = {"decided": "Храним вечно", "superseded": "ничего", "open": "ничего"}
    async with mcp_session(task_secret) as session:
        asked = await call(session, "ask", key=key, addressees=["owner"], title=QUESTION)
        address = asked["discussion"]
        early = await refuse(session, "close_discussion", key=address, **parts)
        await call(session, "answer", key=address, question_no=asked["no"], body="Вечно")
        await call(session, "transition", key=key, to="in_progress")
        await call(
            session, "add_summary", key=key, done="d", remaining="r", blockers="b", next_step="n"
        )
        closing = {
            "key": key,
            "summary": {
                "done": "Сделано",
                "remaining": "nothing",
                "blockers": "nothing",
                "next_step": "no steps",
                "unmeasured": "nothing",
            },
            "verdicts": [{"check_no": 1, "outcome": "passed", "evidence": "прогон"}],
        }
        held = await refuse(session, "close_task", **closing)
        closed = await call(session, "close_discussion", key=address, **parts)
        frozen = await refuse(session, "add_conclusion", key=address, **parts)
        no_more = await refuse(session, "ask", key=address, addressees=["owner"], title="Ещё?")
        package = await call(session, "get_task", key=key)
        done = await call(session, "close_task", **closing)

    assert "discussion_has_open_questions" in early
    assert f"{address}#{asked['no']}" in early
    assert "task_has_open_discussions" in held
    assert closed == {"discussion": address, "status": "closed", "entries": [5, 6]}
    assert "discussion_closed" in frozen and "discussion_closed" in no_more
    (discussion,) = package["discussions"]
    assert (discussion["status"], discussion["turn"]) == ("closed", None)
    assert discussion["conclusion"]["payload"] == parts
    assert done["status"] == "done"


async def test_an_answer_to_an_earlier_task_question_still_files_in_the_task_case(
    mcp_session: Connect, db_session: AsyncSession, task_secret: str, open_task: Task
) -> None:
    """Прежний вопрос дела задачи принимает ответ по ключу задачи — так его и закрывают;
    ответ называет задачу, а не обсуждение."""
    key = open_task.key
    question = await case_service.file_legacy_task_question(
        db_session,
        open_task,
        actor=Actor(author=open_task.created_by, participant=None),
        addressees=["owner"],
        title="Прежний вопрос",
        blocking=True,
    )
    async with mcp_session(task_secret) as session:
        answered = await call(
            session,
            "answer",
            key=key,
            question_no=question.no,
            outcome="withdrawn",
            body="Переспрошу в обсуждении",
        )
        package = await call(session, "get_task", key=key)

    assert (answered["task_key"], answered["discussion"]) == (key, None)
    assert answered["title"] == f"Answer to {key}#{question.no}: withdrawn"
    assert package["questions"] == []
    assert package["features"]["open_blocking_questions"] == 0


async def test_a_repeated_add_entry_returns_the_same_body_and_files_one_entry(
    mcp_session: Connect, task_secret: str, open_task: Task
) -> None:
    """TRK-702: `add_entry` отвечает присланным заголовком, повтор по ключу отдаёт то же
    тело и второй записи не подшивает."""
    key = open_task.key
    arguments = {
        "key": key,
        "type": "finding",
        "title": "X",
        "idempotency_key": "5d2f0c7a-3b1e-4c58-9a16-7e4b2d8f1a03",
    }
    async with mcp_session(task_secret) as session:
        first = await call(session, "add_entry", **arguments)
        second = await call(session, "add_entry", **arguments)
        case = await call(session, "read_entries", key=key, types=["finding"])

    assert first == second
    assert first["title"] == "X"
    assert [item["no"] for item in case["items"]] == [first["no"]]


async def test_an_agent_files_an_answer_relayed_from_a_human(
    mcp_session: Connect, shared_secret: str, owner: Participant, open_task: Task
) -> None:
    """TRK-711: ответ агента со слов человека хранит имя в нагрузке и отдаёт его при
    чтении и в описи; ответ без аргумента читается с `null`; автор записи остаётся агентом."""
    async with mcp_session(shared_secret, label="claude") as session:
        asked = await call(session, "ask", key=open_task.key, addressees=["owner"], title=QUESTION)
        address = asked["discussion"]
        relayed = await call(
            session,
            "answer",
            key=address,
            question_no=asked["no"],
            relayed_from="Owner",
            body="Вечно, сказал в чате",
        )
        own = await call(
            session, "answer", key=address, question_no=asked["no"], body="Дополню сам"
        )
        case = await call(session, "read_project_entries", key=address, types=["answer"])
        package = await call(session, "get_task", key=open_task.key)

    assert relayed["title"] == own["title"]
    by_no = {item["no"]: item for item in case["items"]}
    assert by_no[relayed["no"]]["payload"]["relayed_from"] == "owner"
    assert by_no[own["no"]]["payload"]["relayed_from"] is None
    assert by_no[relayed["no"]]["author"] == {"kind": "agent", "signature": "claude"}
    (discussion,) = package["discussions"]
    assert discussion["status"] == "open"


async def test_relayed_from_is_refused_for_the_four_wrong_cases(
    mcp_session: Connect,
    shared_secret: str,
    task_secret: str,
    owner: Participant,
    db_session: AsyncSession,
    open_task: Task,
) -> None:
    """TRK-711: неизвестное имя, имя агента, исход `withdrawn` и автор-человек — каждое
    `entry_fields_invalid` с полем `relayed_from`."""
    await participants_service.register_participant(
        db_session, actor=TRACKER_ACTOR, kind=ParticipantKind.AGENT, name="helper"
    )
    async with mcp_session(shared_secret, label="claude") as session:
        asked = await call(session, "ask", key=open_task.key, addressees=["owner"], title=QUESTION)
        address, no = asked["discussion"], asked["no"]
        unknown = await refuse(
            session, "answer", key=address, question_no=no, relayed_from="nobody", body="x"
        )
        agent = await refuse(
            session, "answer", key=address, question_no=no, relayed_from="helper", body="x"
        )
        withdrawn = await refuse(
            session,
            "answer",
            key=address,
            question_no=no,
            relayed_from="owner",
            outcome="withdrawn",
            body="устарел",
        )
    async with mcp_session(task_secret) as session:
        by_human = await refuse(
            session, "answer", key=address, question_no=no, relayed_from="owner", body="x"
        )
    async with mcp_session(shared_secret, label="claude") as session:
        case = await call(session, "read_project_entries", key=address, types=["answer"])

    for text, reason in (
        (unknown, "unknown_participant"),
        (agent, "not_a_human"),
        (withdrawn, "not_allowed"),
        (by_human, "author_is_human"),
    ):
        assert "entry_fields_invalid" in text, text
        assert "relayed_from" in text, text
        assert reason in text, text
    assert case["items"] == []


OPTIONS = [
    {"label": "A", "text": "Хранить вечно"},
    {"label": "B", "text": "Удалять через год"},
]


async def test_ask_takes_options_and_answer_takes_choice(
    mcp_session: Connect, shared_secret: str, open_task: Task
) -> None:
    """TRK-719: `ask(options=…)` кладёт варианты в нагрузку вопроса, `answer(choice=…)` — метку
    в нагрузку ответа с пустым телом; обе схемы объявляют аргументы необязательными."""
    async with mcp_session(shared_secret, label="claude") as session:
        declared = {tool.name: tool for tool in (await session.list_tools()).tools}
        asked = await call(
            session,
            "ask",
            key=open_task.key,
            addressees=["owner"],
            title=QUESTION,
            options=OPTIONS,
        )
        address = asked["discussion"]
        answered = await call(session, "answer", key=address, question_no=asked["no"], choice="A")
        case = await call(session, "read_project_entries", key=address)

    for name, argument in (("ask", "options"), ("answer", "choice")):
        schema = declared[name].input_schema
        assert argument in schema["properties"]
        assert argument not in schema.get("required", [])
    by_no = {item["no"]: item for item in case["items"]}
    assert by_no[asked["no"]]["payload"]["options"] == OPTIONS
    assert by_no[answered["no"]]["payload"]["choice"] == "A"
    assert by_no[answered["no"]]["body"] == ""


async def test_options_and_choice_are_refused_when_malformed(
    mcp_session: Connect, shared_secret: str, open_task: Task
) -> None:
    """TRK-719: одна пара, метка вне вариантов и выбор у вопроса без вариантов — отказы
    `entry_fields_invalid` с полем и причиной."""
    key = open_task.key
    async with mcp_session(shared_secret, label="claude") as session:
        one = await refuse(
            session,
            "ask",
            key=key,
            addressees=["owner"],
            title=QUESTION,
            options=OPTIONS[:1],
        )
        asked = await call(
            session,
            "ask",
            key=key,
            addressees=["owner"],
            title=QUESTION,
            options=OPTIONS,
        )
        plain = await call(
            session, "ask", key=asked["discussion"], addressees=["owner"], title="Без вариантов"
        )
        outside = await refuse(
            session, "answer", key=asked["discussion"], question_no=asked["no"], choice="Z"
        )
        free = await refuse(
            session, "answer", key=asked["discussion"], question_no=plain["no"], choice="A"
        )

    assert "entry_fields_invalid" in one and "options" in one, one
    assert "not_an_option" in outside, outside
    assert "question_has_no_options" in free, free
