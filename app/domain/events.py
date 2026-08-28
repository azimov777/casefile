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
    #: Связь между задачами. Объект события — сама связь, а не одна из двух задач:
    #: выбрать «главную» сторону было бы произволом, а подписчику нужны обе. Ключи
    #: обеих задач лежат в `object_key` и в полезной нагрузке.
    LINK = "link"
    #: Комментарий. Объект — сам комментарий, а не задача: подписчик уведомлений
    #: адресует ответ и упоминание конкретной записи обсуждения, а не задаче целиком.
    #: Ключ задачи при этом лежит в `object_key` и в полезной нагрузке.
    COMMENT = "comment"
    #: Пункт чеклиста. Объект — пункт по той же причине: отметка о выполнении
    #: относится к пункту, а не к задаче, у которой их может быть сотня.
    CHECKLIST_ITEM = "checklist_item"
    #: Проект и портфель. Объект — сам проект: подписчик дашборда следит за проектом, а
    #: не за очередью, из которой в него попала задача. Смена проекта у задачи при этом
    #: остаётся событием **задачи** (`issue.updated` с полем `project`) — она меняет
    #: строку задачи, и её история не должна зависеть от того, куда её переложили.
    PROJECT = "project"
    PORTFOLIO = "portfolio"
    #: Доска. Объект — сама доска, в том числе у события о переставленной карточке:
    #: ранг принадлежит доске, а не задаче, и подписчик, который держит открытой одну
    #: доску, обязан уметь отобрать эти события по её идентификатору.
    BOARD = "board"
    #: Спринт. Объект — спринт, а не доска: инбокс и дашборд следят за конкретным
    #: спринтом, а перенос задачи в него остаётся событием **задачи**
    #: (`issue.updated` с полем `sprint`) — он меняет строку задачи.
    SPRINT = "sprint"


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
    LINK_CREATED = "link.created"
    LINK_DELETED = "link.deleted"
    COMMENT_CREATED = "comment.created"
    COMMENT_UPDATED = "comment.updated"
    #: Удаление комментария мягкое: строка остаётся в ленте плашкой без текста.
    #: Событие всё равно нужно — уведомление о комментарии могло уйти раньше, и
    #: подписчик, ведущий свою копию обсуждения, обязан узнать, что текста больше нет.
    COMMENT_DELETED = "comment.deleted"
    CHECKLIST_ITEM_ADDED = "checklist.item_added"
    CHECKLIST_ITEM_UPDATED = "checklist.item_updated"
    #: Отметка и её снятие — два типа, а не один с флагом в нагрузке: «пункт
    #: выполнен» — самое частое условие автоматики и уведомлений, и подписчик должен
    #: отбирать его по типу, не разбирая полезную нагрузку каждого изменения пункта.
    CHECKLIST_ITEM_CHECKED = "checklist.item_checked"
    CHECKLIST_ITEM_UNCHECKED = "checklist.item_unchecked"
    CHECKLIST_ITEM_MOVED = "checklist.item_moved"
    CHECKLIST_ITEM_REMOVED = "checklist.item_removed"
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    #: Архивация и возврат из архива — отдельные типы, а не `project.updated` с полем в
    #: нагрузке. Причина та же, по которой выделен `issue.status_changed`: «проект
    #: выбыл из работы» — самое частое условие дашбордов и уведомлений, и подписчик
    #: должен отбирать его по типу, не разбирая список изменений каждой правки
    #: названия. Возврат — свой тип, а не тот же самый: подписчик, который на архивацию
    #: что-то закрыл, обязан узнать об обратном событии, а не искать его в `changes`.
    PROJECT_ARCHIVED = "project.archived"
    PROJECT_RESTORED = "project.restored"
    PORTFOLIO_CREATED = "portfolio.created"
    PORTFOLIO_UPDATED = "portfolio.updated"
    PORTFOLIO_ARCHIVED = "portfolio.archived"
    PORTFOLIO_RESTORED = "portfolio.restored"
    BOARD_CREATED = "board.created"
    BOARD_UPDATED = "board.updated"
    BOARD_DELETED = "board.deleted"
    #: Карточку переставили. Отдельный тип, а не `board.updated`: перетаскивание — самое
    #: частое событие доски, и подписчик, обновляющий открытый экран, обязан отличать
    #: его от правки настроек, не разбирая полезную нагрузку каждого изменения доски.
    #: Строку задачи оно не меняет и в её историю не попадает — ранг принадлежит доске.
    BOARD_ISSUE_RANKED = "board.issue_ranked"
    SPRINT_CREATED = "sprint.created"
    SPRINT_UPDATED = "sprint.updated"
    #: Запуск и завершение — свои типы, а не `sprint.updated` с полем в нагрузке. Причина
    #: та же, по которой выделены архивация проекта и смена статуса задачи: «спринт
    #: начался» и «спринт закрыт» — самые частые условия уведомлений и отчётов.
    SPRINT_STARTED = "sprint.started"
    SPRINT_COMPLETED = "sprint.completed"
    SPRINT_DELETED = "sprint.deleted"


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
    # Теги — поле задачи, поэтому их правка даёт обычный `issue.updated`, как и
    # подписка. Отдельные действия нужны только проверке прав: «пометить задачу»
    # и «переписать её название» — разные по смыслу операции, и когда появятся
    # роли, разрешать их придётся по отдельности.
    "issue.tag": EventType.ISSUE_UPDATED,
    "issue.untag": EventType.ISSUE_UPDATED,
    "issue.delete": EventType.ISSUE_DELETED,
    # Связи не меняют строку задачи, поэтому и события у них свои, а не `issue.updated`:
    # подписчик, которому интересны только поля задачи, не должен разбирать поток
    # изменений связей, а подписчику связей не нужны все правки названий.
    "link.create": EventType.LINK_CREATED,
    "link.delete": EventType.LINK_DELETED,
    # Обсуждение и чеклист не меняют строку задачи, поэтому события у них свои, а не
    # `issue.updated`: подписчику, которому нужны поля задачи, незачем разбирать поток
    # реплик, а движку уведомлений об упоминаниях — все правки названий.
    "comment.create": EventType.COMMENT_CREATED,
    "comment.update": EventType.COMMENT_UPDATED,
    "comment.delete": EventType.COMMENT_DELETED,
    "checklist.item_add": EventType.CHECKLIST_ITEM_ADDED,
    "checklist.item_update": EventType.CHECKLIST_ITEM_UPDATED,
    "checklist.item_check": EventType.CHECKLIST_ITEM_CHECKED,
    "checklist.item_uncheck": EventType.CHECKLIST_ITEM_UNCHECKED,
    "checklist.item_move": EventType.CHECKLIST_ITEM_MOVED,
    "checklist.item_remove": EventType.CHECKLIST_ITEM_REMOVED,
    # Проект и портфель меняются своими сценариями, но задача при добавлении в проект
    # меняется обычным путём: `issue.set_project` — это правка поля `project`, поэтому
    # она даёт `issue.updated`, а не собственный тип. Отдельное действие нужно проверке
    # прав: «переложить задачу в другой проект» и «переписать её название» — разные по
    # смыслу операции, и когда появятся роли, разрешать их придётся по отдельности.
    "issue.set_project": EventType.ISSUE_UPDATED,
    "project.create": EventType.PROJECT_CREATED,
    "project.update": EventType.PROJECT_UPDATED,
    "project.archive": EventType.PROJECT_ARCHIVED,
    "project.restore": EventType.PROJECT_RESTORED,
    "portfolio.create": EventType.PORTFOLIO_CREATED,
    "portfolio.update": EventType.PORTFOLIO_UPDATED,
    "portfolio.archive": EventType.PORTFOLIO_ARCHIVED,
    "portfolio.restore": EventType.PORTFOLIO_RESTORED,
    # Спринт задаётся полем задачи, как и проект: `issue.set_sprint` — это правка поля
    # `sprint`, поэтому она даёт `issue.updated`, а не собственный тип. Отдельное
    # действие нужно проверке прав: «взять задачу в спринт» и «переписать её название»
    # — разные по смыслу операции.
    "issue.set_sprint": EventType.ISSUE_UPDATED,
    "board.create": EventType.BOARD_CREATED,
    "board.update": EventType.BOARD_UPDATED,
    "board.delete": EventType.BOARD_DELETED,
    # Правка колонок — это правка настроек доски, а не отдельная сущность в потоке
    # событий: подписчику доски одинаково важно перечитать её конфигурацию и в том, и
    # в другом случае, а три типа заставили бы его знать на два больше без пользы.
    "board.column_add": EventType.BOARD_UPDATED,
    "board.column_update": EventType.BOARD_UPDATED,
    "board.column_remove": EventType.BOARD_UPDATED,
    "board.rank": EventType.BOARD_ISSUE_RANKED,
    "sprint.create": EventType.SPRINT_CREATED,
    "sprint.update": EventType.SPRINT_UPDATED,
    "sprint.start": EventType.SPRINT_STARTED,
    "sprint.complete": EventType.SPRINT_COMPLETED,
    "sprint.delete": EventType.SPRINT_DELETED,
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
