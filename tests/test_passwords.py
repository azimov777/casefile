"""Хеш пароля владельца без базы: формат строки, проверка, отказы (`app/domain/passwords.py`).

Строка хеша уезжает в `.env`, а compose подставляет там `$имя`: поэтому проверяется не
только «хеш сходится», но и то, что в строке нет ни одного символа, который файл
окружения или оболочка поймут по-своему.
"""

import re

import pytest

from app.domain.passwords import (
    HASH_SCHEME,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
    PasswordHash,
    PasswordHashError,
    WeakPasswordError,
    check_new_password,
    hash_password,
    verify_password,
)

PASSWORD = "correct horse battery staple"

#: Дешёвые параметры: логике проверки стоимость scrypt безразлична, она читает их из строки.
CHEAP = {"n": 2**4, "r": 1, "p": 1}

#: Символы, которые допустимы в строке хеша: схема, числа, base64url и двоеточия.
SAFE = re.compile(r"^[A-Za-z0-9_:-]+$")


def test_the_default_hash_uses_the_recommended_scrypt_cost() -> None:
    """Без параметров хеш получает стоимость OWASP, и она записана в самой строке."""
    rendered = hash_password(PASSWORD).render()

    scheme, n, r, p, _, _ = rendered.split(":")
    assert (scheme, int(n), int(r), int(p)) == (HASH_SCHEME, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    assert (SCRYPT_N, SCRYPT_R, SCRYPT_P) == (2**15, 8, 3)


def test_the_hash_line_survives_an_env_file() -> None:
    """Ни `$`, ни кавычек, ни пробелов: строку можно вписать в `.env` как есть."""
    rendered = hash_password(PASSWORD, **CHEAP).render()

    assert SAFE.match(rendered), rendered
    assert "$" not in rendered
    assert PASSWORD not in rendered


def test_the_hash_parses_back_and_verifies() -> None:
    stored = PasswordHash.parse(hash_password(PASSWORD, **CHEAP).render())

    assert verify_password(PASSWORD, stored)
    assert not verify_password(PASSWORD + " ", stored)
    assert not verify_password("", stored)


def test_the_same_password_hashes_differently_every_time() -> None:
    """Соль свежая: два хеша одного пароля не совпадают, и оба его принимают."""
    first = hash_password(PASSWORD, **CHEAP)
    second = hash_password(PASSWORD, **CHEAP)

    assert first.render() != second.render()
    assert verify_password(PASSWORD, first) and verify_password(PASSWORD, second)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "$scrypt$16$1$1$c2FsdA$a2V5",
        "argon2:16:1:1:c2FsdA:a2V5",
        "scrypt:16:1:1:c2FsdA",
        "scrypt:15:1:1:c2FsdA:" + "A" * 43,
        f"scrypt:{2**21}:1:1:c2FsdA:" + "A" * 43,
        "scrypt:16:0:1:c2FsdA:" + "A" * 43,
        "scrypt:16:1:1:c2FsdA:short",
        "scrypt:16:1:1:соль:" + "A" * 43,
        "scrypt:sixteen:1:1:c2FsdA:" + "A" * 43,
    ],
)
def test_a_malformed_hash_is_refused_without_repeating_it(text: str) -> None:
    """Испорченная строка — отказ с правилом, и в сообщении нет самой строки."""
    with pytest.raises(PasswordHashError) as refused:
        PasswordHash.parse(text)

    if text:
        assert text not in str(refused.value)


def test_a_short_password_is_refused_with_the_rule() -> None:
    with pytest.raises(WeakPasswordError, match=str(MIN_PASSWORD_LENGTH)):
        check_new_password("x" * (MIN_PASSWORD_LENGTH - 1))

    check_new_password("x" * MIN_PASSWORD_LENGTH)


def test_an_overlong_password_is_refused_before_scrypt() -> None:
    """Потолок длины держит и новый пароль, и попытку входа: тело без потолка — нагрузка."""
    stored = hash_password(PASSWORD, **CHEAP)

    with pytest.raises(WeakPasswordError):
        check_new_password("x" * (MAX_PASSWORD_LENGTH + 1))
    assert not verify_password("x" * (MAX_PASSWORD_LENGTH + 1), stored)
