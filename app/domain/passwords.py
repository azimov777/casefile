"""Пароль учётной записи: хеш scrypt в одну строку и его проверка.

Пароль открывает вход учётной записи (`docs/CONCEPT.md`, 5.4). Сам он нигде не
хранится: в строке учётной записи лежит только хеш (`accounts.password_hash`). Та же
строка — и формат прежнего пароля установки `TRACKER_PASSWORD_HASH`: подъём переносит
его в учётную запись администратора как есть (`app/services/setup.py`), поэтому формат
менять нельзя, не ломая перенос.

## Почему scrypt, а не SHA-256, как у токенов

У токена 256 бит энтропии, и быстрый хеш там верен (`app/domain/tokens.py`). У пароля,
который человек помнит, энтропии мало, и утёкший хеш перебирается словарём — медленная
функция с памятью делает каждую попытку дорогой. scrypt есть в стандартной библиотеке
(`hashlib.scrypt`), поэтому новой зависимости задача не тянет.

## Почему в строке нет `$`

Строка родилась для `.env` (`TRACKER_PASSWORD_HASH`), где привычная запись `$scrypt$...`
ломается молча: compose подставляет `$имя` в значениях файла, и хеш приезжал бы в процесс
обрезанным. Разделитель — двоеточие, части — base64url без выравнивания. В базе это уже не
важно, но формат один — ради переноса прежнего хеша.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from app.domain.errors import WeakPasswordError

#: Имя схемы — первая часть строки хеша. По ней видно, что лежит в настройке, и её
#: можно будет сменить, не ломая прежние хеши.
HASH_SCHEME = "scrypt"

#: Параметры scrypt по рекомендации OWASP: `N=2^15`, `r=8`, `p=3` — около 32 МиБ памяти на
#: попытку. Хранятся в самой строке хеша, поэтому проверка читает их оттуда, и смена
#: умолчаний здесь не ломает уже выданные хеши.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 3

#: Потолок стоимости, которую примет проверка. Перенесённый хеш писал владелец в `.env`,
#: и опечатка в `N` не должна превращать каждую попытку входа в гигабайты памяти
#: процесса API.
MAX_SCRYPT_N = 2**20
MAX_SCRYPT_R = 32
MAX_SCRYPT_P = 16

SALT_BYTES = 16
KEY_BYTES = 32

#: Короче новый пароль не принимается нигде. Перебор ограничен окном
#: (`app/services/login.py`), но окно держит онлайн-попытки, а не утёкший хеш.
MIN_PASSWORD_LENGTH = 12

#: Длиннее не принимает вход: scrypt переварит любую длину, но тело запроса без
#: потолка — это способ занять процесс чужими мегабайтами.
MAX_PASSWORD_LENGTH = 1024


class PasswordHashError(ValueError):
    """Строка не похожа на хеш `scrypt:<n>:<r>:<p>:<соль>:<ключ>`.

    Сообщение никогда не содержит саму строку: она уходит в журнал подъёма контура.
    """


@dataclass(frozen=True, slots=True)
class PasswordHash:
    """Разобранный хеш: параметры scrypt, соль и выведенный ключ."""

    n: int
    r: int
    p: int
    salt: bytes
    key: bytes

    def render(self) -> str:
        """Строка для `.env`: `scrypt:<n>:<r>:<p>:<соль>:<ключ>`."""
        return ":".join(
            [HASH_SCHEME, str(self.n), str(self.r), str(self.p), _b64(self.salt), _b64(self.key)]
        )

    @classmethod
    def parse(cls, text: str) -> PasswordHash:
        """Разбирает строку хеша или отказывает с причиной, не называя саму строку."""
        parts = text.strip().split(":")
        if len(parts) != 6 or parts[0] != HASH_SCHEME:
            raise PasswordHashError(f"expected `{HASH_SCHEME}:<n>:<r>:<p>:<salt>:<key>`")
        _, n_text, r_text, p_text, salt_text, key_text = parts
        try:
            n, r, p = int(n_text), int(r_text), int(p_text)
            salt, key = _unb64(salt_text), _unb64(key_text)
        except (ValueError, binascii.Error) as exc:
            raise PasswordHashError("parameters or encoded parts do not parse") from exc
        if n < 2 or n & (n - 1) or n > MAX_SCRYPT_N:
            raise PasswordHashError(f"n must be a power of two up to {MAX_SCRYPT_N}")
        if not 1 <= r <= MAX_SCRYPT_R or not 1 <= p <= MAX_SCRYPT_P:
            raise PasswordHashError(f"r must be 1..{MAX_SCRYPT_R} and p must be 1..{MAX_SCRYPT_P}")
        if not salt or len(key) != KEY_BYTES:
            raise PasswordHashError(f"the salt is empty or the key is not {KEY_BYTES} bytes")
        return cls(n=n, r=r, p=p, salt=salt, key=key)


def check_new_password(password: str) -> None:
    """Годится ли пароль в новый хеш. Отказ `weak_password` называет правило, а не пароль."""
    limits = {"min_length": MIN_PASSWORD_LENGTH, "max_length": MAX_PASSWORD_LENGTH}
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters",
            details={"reason": "too_short", **limits},
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"The password must be at most {MAX_PASSWORD_LENGTH} characters",
            details={"reason": "too_long", **limits},
        )


def hash_password(
    password: str,
    *,
    n: int = SCRYPT_N,
    r: int = SCRYPT_R,
    p: int = SCRYPT_P,
) -> PasswordHash:
    """Хеш нового пароля со свежей солью.

    Параметры открыты ради тестов: полный scrypt стоит десятые доли секунды на попытку,
    а проверке логики входа стоимость хеша безразлична — она читает параметры из строки.
    """
    salt = secrets.token_bytes(SALT_BYTES)
    return PasswordHash(n=n, r=r, p=p, salt=salt, key=_derive(password, salt, n, r, p))


def verify_password(password: str, stored: PasswordHash) -> bool:
    """Совпадает ли пароль с хешем. Сравнение по времени не зависит от места расхождения.

    Долгая: вызывающий в асинхронном коде обязан увести её в поток, иначе каждая попытка
    входа держит цикл событий всего процесса.
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    candidate = _derive(password, stored.salt, stored.n, stored.r, stored.p)
    return hmac.compare_digest(candidate, stored.key)


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # `maxmem` обязателен: умолчание OpenSSL — 32 МиБ, а `N=2^15, r=8` требует ровно
    # столько же плюс служебное, и scrypt отказал бы на рекомендуемых параметрах.
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=256 * r * (n + p),
        dklen=KEY_BYTES,
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    if not text or not text.isascii() or not text.replace("-", "").replace("_", "").isalnum():
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
