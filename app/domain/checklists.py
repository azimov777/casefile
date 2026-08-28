"""Чеклист задачи: ограничения пункта и разреженные позиции для порядка.

Чистый Python: ни ORM, ни HTTP. Чеклист — лёгкая декомпозиция там, где заводить
подзадачи избыточно: у пункта нет ни статуса, ни своего процесса, ни истории — только
текст, отметка о выполнении и место в списке.

## Порядок держится на разреженных позициях

Позиция пункта — целое число с большим шагом между соседями (`POSITION_STEP`), а не
номер по порядку. Смысл ровно один: перемещение пункта обязано менять **одну** строку.
При сплошной нумерации перенос первого пункта в конец переписал бы весь список, и
чеклист из сорока пунктов давал бы сорок UPDATE на каждое перетаскивание карточки.

Зазор между соседями конечен: после серии вставок в одно и то же место (каждая делит
зазор пополам) он исчерпывается. Тогда `position_between` возвращает `None` — это не
ошибка, а сигнал сценарию перенумеровать список целиком (`rebalanced_positions`) и
повторить попытку. Перенумерация редка и стоит одного прохода по пунктам одной задачи;
без неё пришлось бы либо переписывать список при каждом перемещении, либо однажды
получить два пункта на одной позиции.

Дробные позиции (`numeric`) сняли бы исчерпание зазора, но подменили бы его худшей
проблемой: двоичная дробь делится пополам бесконечно, и после сотни вставок в одно
место позиция превращается в число, которое база хранит, а человек не читает.
"""

from datetime import datetime

from app.domain.errors import InvalidChecklistItemError, InvalidIssueDeadlineError
from app.domain.issues import validate_deadline

#: Текст пункта — одна строка: пункт показывается в карточке задачи списком, и перевод
#: строки в нём означает, что нужен не пункт, а подзадача с описанием.
MAX_CHECKLIST_TEXT_LENGTH = 255

#: Потолок числа пунктов в одной задаче. Ограничение неочевидное, поэтому названо
#: прямо: чеклист отдаётся целиком, без пагинации, и его размер обязан быть конечным.
#: Задача, которой не хватает сотни пунктов, просит не чеклиста, а подзадач.
MAX_CHECKLIST_ITEMS = 100

#: Шаг между соседними позициями. Степень двойки не случайна: вставка делит зазор
#: пополам, и с шагом 1024 подряд помещается десять вставок в одно и то же место,
#: прежде чем понадобится перенумерация.
POSITION_STEP = 1024

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


def next_position(last: int | None) -> int:
    """Позиция для пункта, добавляемого в конец списка."""
    return POSITION_STEP if last is None else last + POSITION_STEP


def position_between(before: int | None, after: int | None) -> int | None:
    """Позиция строго между соседями или `None`, если зазор исчерпан.

    `None` означает «перенумеруй список и попробуй ещё раз», а не «ошибка»: вызывающая
    сторона обязана обработать этот случай, иначе два пункта однажды получат одну
    позицию и порядок между ними станет произвольным.

    Границы списка выражены `None`: `before is None` — вставка в начало, `after is
    None` — в конец. Вставка в начало упирается в ноль, и это тоже исчерпание зазора:
    отрицательные позиции запрещены — они делают порядок нечитаемым в дампе и
    ломают предположение «позиция растёт вниз по списку».
    """
    if before is None:
        if after is None:
            return POSITION_STEP
        return after // 2 if after >= 2 else None
    if after is None:
        return before + POSITION_STEP
    if after - before < 2:
        return None
    return (before + after) // 2


def rebalanced_positions(count: int) -> list[int]:
    """Позиции для перенумерации списка: снова с полным шагом между соседями.

    Порядок пунктов сохраняется, меняются только числа. Вызывается редко — когда зазор
    в одном месте исчерпан, — и переписывает список целиком: это единственная операция
    чеклиста, которая трогает больше одной строки.
    """
    return [POSITION_STEP * (index + 1) for index in range(count)]
