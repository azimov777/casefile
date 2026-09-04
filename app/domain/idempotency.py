"""Ключ идемпотентности: форма ключа и отпечаток запроса.

Агент падает и повторяет вызов, не зная, прошёл ли предыдущий (`CONCEPT.md`, 4.5).
Ключ — это обещание клиента: «два вызова с одним ключом — это один и тот же вызов».
Проверить обещание нечем, кроме отпечатка запроса, поэтому он здесь и живёт.

Модуль чистый: ни базы, ни HTTP. Одни и те же правила действуют в REST (заголовок
`Idempotency-Key`) и в MCP (аргумент `idempotency_key`) — второй набор правил развёл бы
интерфейсы на первом же краевом случае.
"""

import hashlib
import json
from datetime import timedelta
from typing import Any

from app.domain.errors import InvalidIdempotencyKeyError

#: Заголовок REST. Имя стандартное (черновик IETF, `Idempotency-Key`) — клиенты и
#: библиотеки повторов знают его без документации.
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

#: Имя аргумента у инструментов MCP. Названо здесь, а не в `app/mcp`, чтобы имена
#: заголовка и аргумента лежали рядом: расходиться им некуда.
IDEMPOTENCY_KEY_ARGUMENT = "idempotency_key"

#: Потолок длины ключа. Под него задана колонка `idempotency_keys.key`: без проверки
#: длинный ключ доехал бы до базы и вернулся пятисоткой драйвера вместо внятного отказа.
MAX_KEY_LENGTH = 255

#: Сколько ключ помнят. Сутки — компромисс: агент повторяет вызов через секунды, но
#: упавший и поднятый наутро процесс обязан получить тот же ответ, а не второй объект.
#: Дольше суток хранить нечего — а у выпуска токена и вредно: в ответе лежит секрет.
KEY_TTL = timedelta(days=1)

#: Длина hex-представления SHA-256: под неё задана колонка `idempotency_keys.fingerprint`.
FINGERPRINT_LENGTH = 64


def normalize_idempotency_key(value: str) -> str:
    """Ключ в каноническом виде или `invalid_idempotency_key`.

    Обрезка по краям — то же правило, что у секрета токена (`app/domain/tokens.py`):
    ключ часто копируют вместе с пробелом, и без нормализации повтор молча считался бы
    другим ключом, то есть создавал бы второй объект — ровно то, от чего механизм заводят.
    """
    key = value.strip()
    if not key:
        raise InvalidIdempotencyKeyError(
            message="Idempotency key must not be empty",
            details={"reason": "empty"},
        )
    if len(key) > MAX_KEY_LENGTH:
        raise InvalidIdempotencyKeyError(
            message=f"Idempotency key must be at most {MAX_KEY_LENGTH} characters",
            details={"reason": "too_long", "max_length": MAX_KEY_LENGTH, "length": len(key)},
        )
    return key


def fingerprint(operation: str, request: Any) -> str:
    """Отпечаток вызова: имя операции плюс её запрос.

    Имя операции входит в отпечаток обязательно. Ключ уникален в паре с токеном, а не в
    паре с маршрутом, поэтому без имени операции агент, повторивший один ключ на двух
    разных действиях, получил бы ответ **чужого** действия вместо отказа.

    Считается по каноническому JSON: ключи объектов отсортированы, разделители без
    пробелов. Иначе отпечаток зависел бы от порядка полей в словаре, то есть от версии
    библиотеки и от случайностей сборки запроса, — и повтор того же вызова временами
    отвечал бы `409`.

    Тип, который не сериализуется в JSON, роняет вызов, а не превращается в строку:
    молчаливое `str(...)` дало бы одинаковый отпечаток разным объектам одного класса.
    """
    canonical = json.dumps(
        {"operation": operation, "request": request},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
