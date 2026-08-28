"""Словарь событий, правило выбора типа и формат записи изменения.

Чистый Python: ни ORM, ни HTTP. Здесь живёт то, что обязано быть одинаковым у журнала
изменений, у outbox и у подписчиков, — иначе три механики начнут понимать одно и то же
событие по-разному.

## Один словарь на права и на события

Имена действий для проверки прав (`issue.update`, `issue.assign`, `issue.follow`) уже
различаются по сценариям. Второй, независимый набор имён для событий неизбежно с ними
разъехался бы: кто-то добавил бы действие и забыл событие, и изменение молча перестало
бы доходить до автоматики. Поэтому тип события выводится из действия таблицей
`ACTION_EVENTS`, а не задаётся вызывающим кодом.

Неизвестное действие — не повод «на всякий случай» выдать `issue.updated`: это ошибка
программиста, и она обязана быть громкой. Тихая подстановка означала бы событие
неверного типа, на которое подписчик не среагирует, и искать причину пришлось бы в
подписчике, а не здесь.

## Тип события — ярлык, а не полный список изменений

Одна мутация даёт одну запись журнала и одно событие, даже если поменялось три поля.
Тип выбирается по лестнице приоритетов (см. `event_type_for`), а **что именно**
изменилось, лежит в полезной нагрузке целиком. Подписчику, которому важно конкретное
поле, надо смотреть в `changes`, а не только на тип: `issue.status_changed` может
нести вместе со статусом ещё и смену исполнителя.
"""

from collections.abc import Collection, Iterable, Sequence
from enum import StrEnum
from typing import Any

from app.domain.issues import IssueChange, IssueField


class ObjectType(StrEnum):
    """К чему относится событие.

    Растёт вместе с доменом: комментарий (задача 09), проект (10), доска (11). Пара
    «тип объекта + идентификатор» заменяет внешний ключ, которого у события быть не
    может: событие об удалении задачи обязано пережить саму задачу.
    """

    ISSUE = "issue"
    STATUS = "status"


class EventType(StrEnum):
    """Типы событий шины. Открытый словарь: каждая следующая задача дописывает свои.

    Значения хранятся в базе строкой, а не перечислением с ограничением CHECK, — это
    осознанное отступление от общего правила проекта (`app/db/base.py`, `string_enum`).
    Причина в том, что набор растёт почти каждой задачей: `comment.created` в задаче 09,
    `link.created` в 08, события проектов в 10. С CHECK каждое такое добавление
    требовало бы миграции ради одной строки, и соблазн «пока обойдусь существующим
    типом» победил бы точность словаря.
    """

    ISSUE_CREATED = "issue.created"
    ISSUE_UPDATED = "issue.updated"
    ISSUE_STATUS_CHANGED = "issue.status_changed"
    ISSUE_ASSIGNED = "issue.assigned"
    ISSUE_DELETED = "issue.deleted"
    #: Массовый перенос задач между статусами: одно событие на весь перенос, а не по
    #: событию на задачу. Почему так — в `app/services/issue_usage.py`.
    STATUS_ISSUES_MOVED = "status.issues_moved"


class OutboxStatus(StrEnum):
    """Состояние события в outbox.

    `PENDING` — ждёт обработки или следующей попытки; `DELIVERED` — отработали все
    подписчики; `FAILED` — попытки исчерпаны, событие помечено «не доставлено» и само
    больше не повторится. Набор закрытый, поэтому в базе он и есть перечисление с
    проверкой значений, в отличие от типа события.
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


#: Действие проверки прав → событие, которое оно порождает. Ключи — те самые строки,
#: которые сценарии задачи 05 передают в `ensure_allowed`; сверку стережёт тест.
ACTION_EVENTS: dict[str, EventType] = {
    "issue.create": EventType.ISSUE_CREATED,
    "issue.update": EventType.ISSUE_UPDATED,
    "issue.transition": EventType.ISSUE_STATUS_CHANGED,
    "issue.assign": EventType.ISSUE_ASSIGNED,
    # Подписка и отписка — это изменение поля `followers`, а не отдельная механика:
    # заводить им собственный тип значило бы обязать каждого подписчика знать на один
    # тип больше ради того же самого «у задачи изменился набор наблюдателей».
    "issue.follow": EventType.ISSUE_UPDATED,
    "issue.unfollow": EventType.ISSUE_UPDATED,
    "issue.delete": EventType.ISSUE_DELETED,
}


def event_type_for(action: str, changed_fields: Collection[str] = ()) -> EventType:
    """Тип события для действия и набора фактически изменённых полей.

    Лестница приоритетов, ровно две ступени:

    1. У действия есть собственный тип (`issue.assign` → `issue.assigned`) — берётся он.
    2. Действие даёт общий `issue.updated`, но среди изменений есть статус — берётся
       `issue.status_changed`.

    Смена статуса выделена потому, что на неё подписывается почти всё: автоматика,
    уведомления, доски. Без выделения подписчику пришлось бы разбирать `changes`
    каждого `issue.updated`, а это чтение всего потока событий ради одного поля.

    Неизвестное действие — `ValueError`, а не значение по умолчанию: событие неверного
    типа не дойдёт до подписчика, и искать причину будут где угодно, кроме этой строки.
    """
    try:
        event_type = ACTION_EVENTS[action]
    except KeyError as exc:
        raise ValueError(
            f"Action {action!r} has no event type; add it to ACTION_EVENTS in app/domain/events.py"
        ) from exc

    if event_type is EventType.ISSUE_UPDATED and IssueField.STATUS.value in changed_fields:
        return EventType.ISSUE_STATUS_CHANGED
    return event_type


def encode_changes(changes: Sequence[IssueChange]) -> list[dict[str, Any]]:
    """Изменения в вид, пригодный для JSONB и для полезной нагрузки события.

    Значения не преобразуются: они уже приведены к JSON-виду в единой точке применения
    изменений (`app/services/issues.py`). Второе преобразование здесь означало бы, что
    формат «было/стало» описан в двух местах.
    """
    return [
        {"field": change.field, "before": change.before, "after": change.after}
        for change in changes
    ]


def decode_changes(raw: Iterable[dict[str, Any]]) -> tuple[IssueChange, ...]:
    """Обратное преобразование: строки журнала — снова записи об изменении."""
    return tuple(
        IssueChange(field=item["field"], before=item.get("before"), after=item.get("after"))
        for item in raw
    )


def changed_fields(changes: Sequence[IssueChange]) -> tuple[str, ...]:
    """Имена изменённых полей: системные (`status`) и ссылки кастомных (`TRK.severity`).

    Отдельным списком в полезной нагрузке, потому что подписчик почти всегда сначала
    спрашивает «а моё поле трогали?» и только потом лезет за значениями.
    """
    return tuple(change.field for change in changes)
