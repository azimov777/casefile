"""Учётные записи людей: почта как имя входа и пароль, который выдаёт трекер.

Чистый Python: ни ORM, ни HTTP. Правила одинаковы для REST, командной строки и шага
подъёма установки, поэтому живут здесь, а не в схемах запросов (`docs/CONCEPT.md`, 3.1
и 5.4).

## Почта — только имя входа

Писем трекер не шлёт никогда, поэтому адрес не подтверждается и проверяется ровно
настолько, насколько нужно имени входа: одна `@`, непустые части, без пробелов.
Доменная часть без точки законна намеренно: учётная запись, которую установка заводит
себе сама, называется `owner@localhost` (`local_admin_email`), и спросить настоящий
адрес при подъёме не у кого. Почта канонизируется в нижний регистр — как имя участника,
и по той же причине: уникальность без учёта регистра держит обычное `UNIQUE`.
"""

import re
import secrets

from app.domain.errors import InvalidEmailError

#: Потолок длины адреса по RFC 5321: длиннее адрес не бывает, а колонке нужна граница.
MAX_EMAIL_LENGTH = 254

#: Одна `@`, по обе стороны — непустое без пробелов и без второй `@`. Строже не нужно:
#: почта здесь имя входа, а не адрес доставки (см. раздел модуля).
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"
_EMAIL_RE = re.compile(EMAIL_PATTERN)

#: Домен почты учётной записи, которую установка заводит сама: адрес только называет
#: её и никуда не ведёт.
LOCAL_EMAIL_DOMAIN = "localhost"

#: Энтропия пароля, который трекер генерирует сам: 18 байт — 24 символа base64url,
#: 144 бита. Такой пароль не перебрать и без окна попыток; длина проходит
#: `check_new_password` с запасом.
GENERATED_PASSWORD_BYTES = 18


def normalize_email(email: str) -> str:
    """Канонический вид почты: без пробелов по краям, в нижнем регистре."""
    return email.strip().lower()


def validate_email(email: str) -> str:
    """Проверяет почту и возвращает канонический вид или отказывает `invalid_email`."""
    normalized = normalize_email(email)
    if len(normalized) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(normalized):
        raise InvalidEmailError(
            details={
                "email": email,
                "reason": "pattern_mismatch",
                "pattern": EMAIL_PATTERN,
                "max_length": MAX_EMAIL_LENGTH,
            }
        )
    return normalized


def local_admin_email(participant_name: str) -> str:
    """Почта учётной записи администратора, которую установка заводит себе сама."""
    return f"{participant_name}@{LOCAL_EMAIL_DOMAIN}"


def generate_password() -> str:
    """Новый случайный пароль. Показывается администратору один раз и нигде не хранится."""
    return secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
