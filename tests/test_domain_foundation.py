"""Домен без базы: имена, ключи, метки, наборы и структура автора.

Всё, что здесь проверяется, не требует ни PostgreSQL, ни HTTP: это правила, одинаковые
для REST, MCP и командной строки.
"""

import pytest

from app.domain.authors import (
    TRACKER,
    Author,
    AuthorKind,
    label_author,
    participant_author,
    validate_actor_label,
)
from app.domain.errors import (
    InvalidActorLabelError,
    InvalidParticipantNameError,
    InvalidQueueKeyError,
)
from app.domain.participants import ParticipantKind, validate_participant_name
from app.domain.queues import validate_queue_key
from app.domain.tokens import TOKEN_PREFIX, TokenScope, generate_token, hash_token

# --- Имена участников --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("release_bot", "release_bot"),
        ("  release_bot  ", "release_bot"),
        ("Release_Bot", "release_bot"),
        ("A1", "a1"),
    ],
)
def test_a_name_is_canonicalised_to_lowercase(raw: str, expected: str) -> None:
    """Верхний регистр не отвергается, а приводится: имена уникальны без учёта регистра."""
    assert validate_participant_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "a", "1bot", "release-bot", "релиз", "with space", "x" * 65])
def test_a_malformed_name_is_rejected_with_the_pattern(raw: str) -> None:
    """В подробностях уезжает шаблон: агент обязан исправить запрос с первой попытки."""
    with pytest.raises(InvalidParticipantNameError) as error:
        validate_participant_name(raw)

    assert error.value.code == "invalid_participant_name"
    assert error.value.details["pattern"]


# --- Ключи очередей ----------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [("TRK", "TRK"), ("trk", "TRK"), (" Ops2 ", "OPS2")])
def test_a_queue_key_is_canonicalised_to_uppercase(raw: str, expected: str) -> None:
    """Ключ идёт в ключ задачи (`TRK-42`) и там обязан читаться как ключ."""
    assert validate_queue_key(raw) == expected


@pytest.mark.parametrize("raw", ["", "T", "1TRK", "TRK-1", "TRK_OPS", "ОЧЕРЕДЬ", "T" * 17])
def test_a_malformed_queue_key_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidQueueKeyError) as error:
        validate_queue_key(raw)

    assert error.value.code == "invalid_queue_key"


# --- Метка временного агента -------------------------------------------------------


def test_a_label_lives_in_the_same_namespace_as_names() -> None:
    """Подпись одна, поэтому и правила написания у метки те же, что у имени участника."""
    assert validate_actor_label(" Nightly_Agent ") == "nightly_agent"

    with pytest.raises(InvalidActorLabelError) as error:
        validate_actor_label("nightly agent")
    assert error.value.details["header"] == "X-Actor-Label"


# --- Структура автора --------------------------------------------------------------


def test_a_participant_author_keeps_kind_and_name() -> None:
    author = participant_author(ParticipantKind.AGENT.value, "release_bot")

    assert author == Author(kind=AuthorKind.AGENT, signature="release_bot")


def test_a_labelled_author_is_always_an_agent() -> None:
    """Метку предъявляет тот, кто пришёл с общим агентским токеном: род тут зашит."""
    assert label_author("Nightly_Agent") == Author(kind=AuthorKind.AGENT, signature="nightly_agent")


def test_the_tracker_has_no_signature() -> None:
    assert TRACKER.kind is AuthorKind.TRACKER
    assert TRACKER.signature is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": AuthorKind.TRACKER, "signature": "tracker"},
        {"kind": AuthorKind.AGENT, "signature": None},
        {"kind": AuthorKind.HUMAN, "signature": ""},
    ],
)
def test_an_author_without_a_valid_signature_cannot_be_built(kwargs: dict) -> None:
    """Инвариант держит конструктор: анонимная запись не должна получиться случайно.

    `ValueError`, а не доменная ошибка с кодом: до пользователя такое состояние дойти не
    может — это ошибка кода, и она обязана падать громко и сразу.
    """
    with pytest.raises(ValueError, match="signature"):
        Author(**kwargs)


# --- Наборы токена -----------------------------------------------------------------


def test_main_opens_everything_task_opens_and_task_does_not_open_main() -> None:
    """Вложенность наборов живёт в перечислении: единая точка прав ею только пользуется."""
    assert TokenScope.MAIN.allows(TokenScope.TASK)
    assert TokenScope.MAIN.allows(TokenScope.MAIN)
    assert TokenScope.TASK.allows(TokenScope.TASK)
    assert not TokenScope.TASK.allows(TokenScope.MAIN)


# --- Секрет токена -----------------------------------------------------------------


def test_a_generated_token_is_prefixed_and_unique() -> None:
    first, second = generate_token(), generate_token()

    assert first.startswith(TOKEN_PREFIX)
    assert first != second


def test_hashing_ignores_surrounding_whitespace() -> None:
    """Токен копируют вместе с переводом строки, и без нормализации он молча ломается."""
    secret = generate_token()

    assert hash_token(f" {secret}\n") == hash_token(secret)
    assert secret not in hash_token(secret)
