"""Состояние знакомства учётной записи: прошёл ли человек его и что скрыл.

Чистый Python: ни ORM, ни HTTP. Решение владельца — хранить на сервере, у учётной
записи, а не в браузере (`TRK-360#17`): экран «Начало» решает по нему, показываться ли
самому, а пояснения экранов — какие уже закрыты. Единственный вызывающий — REST
(`PATCH /api/v1/accounts/{account_id}/onboarding`, TRK-369): у MCP инструмента под это
нет, командной строки — тоже, поэтому форму ключа пояснения (шаблон, потолок списка)
проверяет схема запроса, а не эта проверка вторым слоем — второго вызывающего, для
которого она была бы нужна, не существует.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class OnboardingStatus(StrEnum):
    """Прошёл ли человек знакомство.

    `SKIPPED` — не «отказался», а «продуктом уже пользуется»: этим значением и
    `hidden_all: true` миграция `20260928_1200_onboarding_state` пометила учётные записи,
    существовавшие до этого поля. Экран «Начало» им доступен из панели, но сам не
    открывается. Новая учётная запись начинает с `PENDING` и пустых подсказок.
    """

    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


#: Ключ пояснения: латиница нижнего регистра с первой буквы, дальше цифры и `_.-`, не
#: длиннее 64 знаков. Сервер хранит его непрозрачным — экраны интерфейса и их состав он
#: не знает, и новый экран не требует правки бэкенда (`TRK-360#17`).
ONBOARDING_HINT_KEY_PATTERN = r"^[a-z][a-z0-9_.-]{0,63}$"

#: Список пояснений, скрытых по одному, не длиннее стольки ключей.
MAX_ONBOARDING_HIDDEN_HINTS = 64


@dataclass(frozen=True, slots=True)
class OnboardingHints:
    """Что человек скрыл: все пояснения разом или по одному, списком ключей."""

    hidden_all: bool
    hidden: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnboardingState:
    """Состояние знакомства целиком — то, что отдаёт `AccountRead.onboarding`."""

    status: OnboardingStatus
    hints: OnboardingHints


def normalize_hidden_hints(keys: Sequence[str]) -> list[str]:
    """Список ключей без повторов, в порядке первого появления.

    Форму ключа и потолок длины списка проверяет схема запроса (раздел модуля) —
    здесь только схлопывание повторов, которое проверкой формы не выражается: список
    ключей с повтором синтаксически годен, а хранить его дважды незачем.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized
