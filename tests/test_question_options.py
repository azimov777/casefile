"""Варианты ответа у вопроса (TRK-718, вариант А из TRK-710#9): `options` в вопросе обсуждения,
`choice` в ответе.

По правилу задачи на каждое свой тест: форма вариантов (число, метки, текст), форма `choice`,
сверка метки с вариантами вопроса, ответ с одним `choice` без тела, прежние вопрос и ответ
без изменений, выдача вариантов и выбора по REST.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discussion import Discussion
from app.db.models.project import Project
from app.domain.authors import label_author
from app.domain.case import EntryContext, EntryType, build_entry
from app.domain.errors import EntryFieldsInvalidError
from app.services import case as case_service
from app.services import discussions as service
from app.services.auth import Actor

AGENT = Actor(author=label_author("options_bot"))
CONTEXT = EntryContext(task_key="TRK~1", checks=(), discussion=True)
OPTIONS = [
    {"label": "A", "text": "Держать v1 ещё месяц"},
    {"label": "B", "text": "Убрать v1 сейчас"},
]


def _question(options: Any) -> Any:
    return build_entry(
        CONTEXT,
        type=EntryType.QUESTION,
        title="Что решаем дальше?",
        payload={"addressees": ["owner"], "options": options},
    )


async def _asked(session: AsyncSession, project: Project, options: Any = None) -> Discussion:
    discussion = await service.create_discussion(
        session, actor=AGENT, project=project, title="Старт", opening=EntryType.NOTE
    )
    await case_service.ask_in_discussion(
        session,
        discussion,
        actor=AGENT,
        addressees=["owner"],
        title="Что решаем дальше?",
        options=options,
    )
    return discussion


async def _answer(session: AsyncSession, discussion: Discussion, *, body: str = "", **payload: Any):
    return await case_service.answer_in_discussion(
        session,
        discussion,
        actor=AGENT,
        question_no=_last_question(discussion),
        body=body,
        **payload,
    )


def _last_question(discussion: Discussion) -> int:
    return 3  # №1 created, №2 заметка, №3 вопрос


# --- Форма вариантов ---------------------------------------------------------------------


def test_a_question_keeps_its_options_trimmed_and_in_order() -> None:
    draft = _question([{"label": " A ", "text": " один "}, {"label": "B", "text": "два"}])

    assert draft.payload["options"] == [
        {"label": "A", "text": "один"},
        {"label": "B", "text": "два"},
    ]


def test_a_question_without_options_carries_none() -> None:
    assert _question(None).payload["options"] is None


@pytest.mark.parametrize(
    "options",
    [
        [OPTIONS[0]],
        [{"label": str(n), "text": "x"} for n in range(9)],
        "AB",
        [OPTIONS[0], "B"],
        [OPTIONS[0], {"label": "B", "text": "x", "note": "лишнее"}],
        [OPTIONS[0], {"label": "B"}],
        [OPTIONS[0], {"label": " ", "text": "x"}],
        [OPTIONS[0], {"label": "B", "text": " "}],
        [OPTIONS[0], {"label": "B" * 33, "text": "x"}],
        [OPTIONS[0], {"label": "B", "text": "x" * 501}],
        [OPTIONS[0], {"label": "a", "text": "дубль без учёта регистра"}],
    ],
)
def test_options_of_a_wrong_shape_are_refused(options: Any) -> None:
    with pytest.raises(EntryFieldsInvalidError) as raised:
        _question(options)

    assert [item["field"] for item in raised.value.details["fields"]] == ["options"]


def test_the_boundaries_of_the_option_count_are_accepted() -> None:
    assert len(_question(OPTIONS).payload["options"]) == 2
    eight = [{"label": str(n), "text": "x"} for n in range(8)]
    assert len(_question(eight).payload["options"]) == 8


# --- Форма choice ------------------------------------------------------------------------


def test_choice_is_trimmed_and_lies_in_the_payload_always() -> None:
    with_choice = build_entry(
        CONTEXT, type=EntryType.ANSWER, payload={"question_no": 3, "choice": " A "}
    )
    without = build_entry(CONTEXT, type=EntryType.ANSWER, body="да", payload={"question_no": 3})

    assert with_choice.payload["choice"] == "A"
    assert without.payload["choice"] is None


@pytest.mark.parametrize("value", [5, " "])
def test_choice_takes_only_a_non_empty_string(value: Any) -> None:
    with pytest.raises(EntryFieldsInvalidError):
        build_entry(CONTEXT, type=EntryType.ANSWER, payload={"question_no": 3, "choice": value})


@pytest.mark.parametrize("outcome", ["withdrawn", "replaced"])
def test_choice_is_refused_with_an_outcome_other_than_answered(outcome: str) -> None:
    payload: dict[str, Any] = {"question_no": 3, "outcome": outcome, "choice": "A"}
    if outcome == "replaced":
        payload["replaced_by"] = 9

    with pytest.raises(EntryFieldsInvalidError) as raised:
        build_entry(CONTEXT, type=EntryType.ANSWER, body="почему", payload=payload)

    assert "choice" in str(raised.value.details)


# --- Сверка с вопросом -------------------------------------------------------------------


async def test_a_choice_outside_the_options_is_refused_and_one_from_them_is_accepted(
    db_session: AsyncSession, project: Project
) -> None:
    """Обзорная проверка 2: метка вне вариантов — `entry_fields_invalid`, из них — принята."""
    discussion = await _asked(db_session, project, OPTIONS)

    with pytest.raises(EntryFieldsInvalidError) as raised:
        await _answer(db_session, discussion, choice="C")
    [problem] = raised.value.details["fields"]
    assert (problem["field"], problem["reason"], problem["allowed"]) == (
        "choice",
        "not_an_option",
        ["A", "B"],
    )

    accepted = await _answer(db_session, discussion, choice="B")
    assert accepted.payload["choice"] == "B"
    assert accepted.body == ""


async def test_a_choice_is_compared_exactly(db_session: AsyncSession, project: Project) -> None:
    discussion = await _asked(db_session, project, OPTIONS)

    with pytest.raises(EntryFieldsInvalidError):
        await _answer(db_session, discussion, choice="a")


async def test_a_choice_on_a_question_without_options_is_refused(
    db_session: AsyncSession, project: Project
) -> None:
    discussion = await _asked(db_session, project)

    with pytest.raises(EntryFieldsInvalidError) as raised:
        await _answer(db_session, discussion, choice="A", body="да")

    assert raised.value.details["fields"][0]["reason"] == "question_has_no_options"


async def test_a_choice_may_come_with_a_free_text_body(
    db_session: AsyncSession, project: Project
) -> None:
    """Свободный текст остаётся в любом случае, в том числе рядом с выбором."""
    discussion = await _asked(db_session, project, OPTIONS)

    answer = await _answer(db_session, discussion, choice="A", body="Анонсировать заранее")

    assert (answer.payload["choice"], answer.body) == ("A", "Анонсировать заранее")


async def test_a_question_and_an_answer_without_options_work_as_before(
    db_session: AsyncSession, project: Project
) -> None:
    """Обзорная проверка 3: вопрос без `options` и ответ одним `body` принимаются."""
    discussion = await _asked(db_session, project)

    answer = await _answer(db_session, discussion, body="Да")

    assert answer.payload == {
        "question_no": 3,
        "outcome": "answered",
        "replaced_by": None,
        "relayed_from": None,
        "choice": None,
    }
    question = (
        await case_service.list_discussion_entries(db_session, discussion, actor=AGENT)
    ).items[2]
    assert question.payload == {"addressees": ["owner"], "blocking": True, "options": None}


async def test_an_answer_without_body_and_choice_is_still_accepted(
    db_session: AsyncSession, project: Project
) -> None:
    """Пустой ответ без `choice` принимался и раньше: тело необязательно по существу."""
    discussion = await _asked(db_session, project, OPTIONS)

    answer = await _answer(db_session, discussion)

    assert answer.payload["choice"] is None


# --- REST --------------------------------------------------------------------------------


async def test_rest_files_a_choice_and_shows_options_and_choice(
    db_session: AsyncSession, auth_client: AsyncClient, project: Project
) -> None:
    discussion = await _asked(db_session, project, OPTIONS)
    address = discussion.address

    refused = await auth_client.post(
        f"/api/v1/discussions/{address}/entries",
        json={"type": "answer", "payload": {"question_no": 3, "choice": "Z"}},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "entry_fields_invalid"

    filed = await auth_client.post(
        f"/api/v1/discussions/{address}/entries",
        json={"type": "answer", "payload": {"question_no": 3, "choice": "A"}},
    )
    assert filed.status_code == 201, filed.text
    assert filed.json()["data"]["payload"]["choice"] == "A"

    entries = await auth_client.get(f"/api/v1/discussions/{address}/entries")
    by_type = {item["type"]: item for item in entries.json()["data"]}
    assert by_type["question"]["payload"]["options"] == OPTIONS
    assert by_type["answer"]["payload"]["choice"] == "A"
