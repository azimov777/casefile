"""Чеклист задачи: ограничения пункта и разреженные позиции для порядка.

Чистый Python: ни ORM, ни HTTP. Чеклист — лёгкая декомпозиция там, где заводить
подзадачи избыточно: у пункта нет ни статуса, ни своего процесса, ни истории — только
текст, отметка о выполнении и место в списке.

## Порядок держится на разреженных позициях

Арифметика позиций живёт в `app/domain/ranking.py` и здесь только реэкспортируется:
той же шкалой пользуется ранжирование карточек на доске, и две копии формулы однажды
разошлись бы обработкой исчерпанного зазора. Смысл шкалы ровно один: перемещение
пункта обязано менять **одну** строку. При сплошной нумерации перенос первого пункта в
конец переписал бы весь список, и чеклист из сорока пунктов давал бы сорок UPDATE на
каждое перетаскивание карточки.

Когда зазор между соседями исчерпан, `position_between` возвращает `None` — это не
ошибка, а сигнал сценарию перенумеровать список целиком (`rebalanced_positions`) и
повторить попытку. Перенумерация редка и стоит одного прохода по пунктам одной задачи.
"""

from datetime import datetime

from app.domain.errors import InvalidChecklistItemError, InvalidIssueDeadlineError
from app.domain.issues import validate_deadline
from app.domain.ranking import (
    POSITION_STEP,
    next_position,
    position_between,
    rebalanced_positions,
)

__all__ = [
    "CHECKLIST_CHANGE_FIELD",
    "MAX_CHECKLIST_ITEMS",
    "MAX_CHECKLIST_TEXT_LENGTH",
    "POSITION_STEP",
    "ensure_capacity",
    "next_position",
    "position_between",
    "rebalanced_positions",
    "validate_item_deadline",
    "validate_text",
]

#: Текст пункта — одна строка: пункт показывается в карточке задачи списком, и перевод
#: строки в нём означает, что нужен не пункт, а подзадача с описанием.
MAX_CHECKLIST_TEXT_LENGTH = 255

#: Потолок числа пунктов в одной задаче. Ограничение неочевидное, поэтому названо
#: прямо: чеклист отдаётся целиком, без пагинации, и его размер обязан быть конечным.
#: Задача, которой не хватает сотни пунктов, просит не чеклиста, а подзадач.
MAX_CHECKLIST_ITEMS = 100

#: Имя поля в журнале изменений задачи. Входит в `SYSTEM_FIELD_KEYS`
#: (`app/domain/fields.py`), поэтому кастомное поле с таким ключом завести нельзя.
CHECKLIST_CHANGE_FIELD = "checklist"


def validate_text(text: str) -> str:
    """Проверяет текст пункта и возвращает канонический вид."""
    normalized = text.strip()
    if not normalized:
        raise InvalidChecklistItemError(details={"field": "text", "reason": "required"})
    if "\n" in normalized or "\r" in normalized:
        raise InvalidChecklistItemError(
            details={"field": "text", "reason": "multiline_not_allowed"},
        )
    if len(normalized) > MAX_CHECKLIST_TEXT_LENGTH:
        raise InvalidChecklistItemError(
            details={
                "field": "text",
                "reason": "too_long",
                "max": MAX_CHECKLIST_TEXT_LENGTH,
                "got": len(normalized),
            },
        )
    return normalized


def validate_item_deadline(deadline: datetime | None) -> datetime | None:
    """Дедлайн пункта: то же правило, что у дедлайна задачи, но свой код ошибки.

    Правило одно и реализовано один раз — время без зоны отвергается, момент
    приводится к UTC. Наружу при этом уходит `invalid_checklist_item`, а не ошибка
    задачи: клиент, получивший `invalid_issue_deadline` в ответ на правку пункта,
    искал бы проблему в дедлайне самой задачи.
    """
    try:
        return validate_deadline(deadline)
    except InvalidIssueDeadlineError as exc:
        raise InvalidChecklistItemError(details={**exc.details, "field": "deadline"}) from exc


def ensure_capacity(count: int) -> None:
    """Отклоняет добавление пункта сверх потолка.

    Отдельная функция, а не проверка по месту: тот же потолок стережёт и сценарий
    добавления, и любой будущий импорт пунктов пачкой.
    """
    if count >= MAX_CHECKLIST_ITEMS:
        raise InvalidChecklistItemError(
            details={
                "field": "checklist",
                "reason": "too_many_items",
                "max": MAX_CHECKLIST_ITEMS,
                "got": count,
            },
        )
