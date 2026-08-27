"""Домен акторов и токенов: проверяется без базы, потому что базы он не знает."""

import pytest

from app.domain.actors import ACTOR_KEY_PATTERN, RESERVED_ACTOR_KEYS, validate_actor_key
from app.domain.errors import InvalidActorKeyError
from app.domain.tokens import TOKEN_HASH_LENGTH, TOKEN_PREFIX, generate_token, hash_token


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("owner", "owner"), ("  Release_Bot  ", "release_bot"), ("a1_b2", "a1_b2")],
)
def test_valid_key_is_normalized(raw: str, expected: str) -> None:
    assert validate_actor_key(raw) == expected


@pytest.mark.parametrize("raw", ["", "a", "1bot", "Ключ", "with-dash", "with.dot", "x" * 65])
def test_invalid_key_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidActorKeyError) as error:
        validate_actor_key(raw)

    assert error.value.details["pattern"] == ACTOR_KEY_PATTERN


def test_reserved_key_is_rejected() -> None:
    """`me` занят маршрутом `/actors/me`: актор с таким ключом был бы недостижим."""
    for key in RESERVED_ACTOR_KEYS:
        with pytest.raises(InvalidActorKeyError) as error:
            validate_actor_key(key)

        assert error.value.details["reason"] == "reserved"


def test_generated_tokens_are_unique_and_prefixed() -> None:
    tokens = {generate_token() for _ in range(100)}

    assert len(tokens) == 100
    assert all(token.startswith(TOKEN_PREFIX) for token in tokens)


def test_hash_is_stable_and_ignores_surrounding_whitespace() -> None:
    """Скопированный вместе с переводом строки токен должен продолжать работать."""
    token = generate_token()

    assert hash_token(token) == hash_token(f"  {token}\n")
    assert len(hash_token(token)) == TOKEN_HASH_LENGTH


def test_hash_does_not_contain_the_secret() -> None:
    token = generate_token()

    assert token not in hash_token(token)
