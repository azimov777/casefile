"""Уведомления: области подписки, адресация по нагрузке события, текст записи.

Чистый Python: ни ORM, ни HTTP. Здесь живёт то, что обязано быть одинаковым у
подписчика шины, у сценариев инбокса и у схем API, — иначе три механики начнут
понимать одну и ту же подписку по-разному.

## Адресат считается из нагрузки события, а не из базы

В событии лежит снимок объекта **на момент изменения**: автор, исполнитель,
наблюдатели, упомянутые, «было → стало». Прочитать задачу из базы в момент доставки
значило бы взять другое состояние — пока событие ждало в очереди, задачу успели
изменить, и уведомление «статус стал в работе» ушло бы с текстом «закрыта».

Отсюда правило: `audience_of` и `describe` принимают тип события и словарь нагрузки, и
больше ничего. Ни сессии, ни моделей у них в сигнатуре нет — не по стилю, а чтобы
поход в базу был физически невозможен.

## Роль и область — одно перечисление, а не два

«Я исполнитель» — это и роль актора в событии, и область подписки. Разделить их на два
набора имён значило бы держать таблицу соответствия между ними и однажды её не
дополнить. Поэтому `SubscriptionScope` описывает и то и другое, а различает их деление
на `ROLE_SCOPES` (проверяются по нагрузке) и `TARGET_SCOPES` (проверяются по ключу
объекта).

## Правила по умолчанию живут здесь, а не строками в базе

Автор, исполнитель, наблюдатели, упомянутые и участники проекта получают события своих
объектов без единой строки в `notification_subscriptions`. Строка подписки нужна только
чтобы **добавить** область (очередь, проект, чужая задача) или **погасить** роль
(`is_enabled = false`).

Причина: строки по умолчанию пришлось бы заводить при создании актора и мигрировать
всем, кто заведён раньше этой задачи. Актор без подписок означал бы актора, до которого
не доходит ничего, — и объяснялось бы это не кодом, а историей установки.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.errors import InvalidSubscriptionError
from app.domain.events import EventType, ObjectType

#: Потолок готового текста уведомления. Текст хранится собранным и читается пачками:
#: инбокс агента — это страница из полусотни записей, и абзац в каждой съел бы его
#: контекст. Длинные куски (тело комментария, название задачи) обрезаются отрывком.
MAX_TEXT_LENGTH = 400

#: Длина отрывка чужого текста внутри уведомления: тела комментария, названия задачи.
EXCERPT_LENGTH = 120

#: Тип «события» у уведомления, отправленного адресно, а не выведенного из шины: так
#: помечает свои сообщения правило автоматики (`ctx.notify`). Строка в том же
#: пространстве имён, что и `EventType`, но членом его не является намеренно: событием
#: шины она не становится, в outbox не попадает и подписчиков не будит.
DIRECT_EVENT_TYPE = "notification.direct"


class SubscriptionScope(StrEnum):
    """Что именно интересует актора.

    Делится на две группы, и деление принципиально. Ролевые области
    (`ROLE_SCOPES`) отвечают на вопрос «кем я прихожусь этому событию» и считаются по
    нагрузке. Предметные (`TARGET_SCOPES`) отвечают на вопрос «к какому объекту оно
    относится» и требуют ключа в `scope_key`.
    """

    #: Весь поток событий установки. Ключа не требует и роли не проверяет — этим
    #: отличается от обеих групп сразу, поэтому не входит ни в одну.
    ALL = "all"
    QUEUE = "queue"
    #: Проект и портфель. Одна область на оба вида: ключ проекта лежит в снимке задачи
    #: (`payload["issue"]["project"]`), и получателя видно по нагрузке, не заходя в базу.
    PROJECT = "project"
    ISSUE = "issue"
    AUTHOR = "author"
    ASSIGNEE = "assignee"
    FOLLOWER = "follower"
    MENTION = "mention"
    #: Участник или руководитель проекта либо портфеля — для событий самого проекта.
    #: У задач своей роли «участник» нет: там причастность выражают автор, исполнитель
    #: и наблюдатели.
    MEMBER = "member"


class DeliveryChannel(StrEnum):
    """Куда доставлять.

    Значение пока одно, и это не заготовка «на будущее», а граница задачи. Вебхуки
    (задача 15) заводят **собственную** подписку с адресом и секретом — их нельзя
    описать этой строкой. MCP-нотификации (задача 16) не второй канал, а способ
    показать тот же инбокс: они читают эти же записи.

    Колонка при этом нужна: без неё «выключить инбокс, оставив вебхуки» пришлось бы
    выражать удалением подписки, а это разные вещи.
    """

    INBOX = "inbox"


#: Области, которые проверяются по нагрузке события: актор получает уведомление, если
#: он оказался в этой роли.
ROLE_SCOPES: frozenset[SubscriptionScope] = frozenset(
    {
        SubscriptionScope.AUTHOR,
        SubscriptionScope.ASSIGNEE,
        SubscriptionScope.FOLLOWER,
        SubscriptionScope.MENTION,
        SubscriptionScope.MEMBER,
    }
)

#: Области, которые адресуют объект и потому требуют ключа в `scope_key`.
TARGET_SCOPES: frozenset[SubscriptionScope] = frozenset(
    {
        SubscriptionScope.QUEUE,
        SubscriptionScope.PROJECT,
        SubscriptionScope.ISSUE,
    }
)

#: Роли, которые уведомляют без всякой подписки. Строка подписки на такую область
#: нужна только чтобы её **выключить** или сузить набором типов событий.
DEFAULT_ROLE_SCOPES: frozenset[SubscriptionScope] = ROLE_SCOPES

#: Порядок ролей по адресности — от самой личной к самой общей. Один и тот же актор
#: бывает причастен несколькими способами сразу, а в уведомлении причина записывается
#: одна: агент решает по ней, насколько срочно вмешаться.
#:
#: Порядок именно такой, а не алфавитный, и это не косметика. Реплика «@bob, посмотри»
#: по задаче, где Боб и так исполнитель, обязана прийти к нему как **упоминание**:
#: «меня позвали лично» и «изменилось что-то в моей задаче» — разные поводы, и агент,
#: разбирающий ленту, отличает их именно по этому полю.
SCOPE_PRIORITY: tuple[SubscriptionScope, ...] = (
    SubscriptionScope.MENTION,
    SubscriptionScope.ASSIGNEE,
    SubscriptionScope.AUTHOR,
    SubscriptionScope.FOLLOWER,
    SubscriptionScope.MEMBER,
    SubscriptionScope.ISSUE,
    SubscriptionScope.PROJECT,
    SubscriptionScope.QUEUE,
    SubscriptionScope.ALL,
)


def strongest_scope(scopes: Iterable[SubscriptionScope]) -> SubscriptionScope | None:
    """Самая адресная из ролей, в которых актор оказался причастен событию.

    `None` означает пустой набор — такого адресата быть не должно, и молча подставлять
    сюда «что-нибудь» нельзя: пустая роль означала бы уведомление без причины.
    """
    present = set(scopes)
    return next((scope for scope in SCOPE_PRIORITY if scope in present), None)


#: Уведомлять ли актора о его собственных действиях. `False`, потому что иначе агент,
#: обновивший задачу, немедленно разбудит сам себя своим же изменением. Меняется
#: подпиской (`notify_own_actions`), а не правкой этой строки.
DEFAULT_NOTIFY_OWN_ACTIONS = False

#: Известные типы событий: по ним проверяется набор в подписке. Опечатка в типе иначе
#: дала бы подписку, которая молча никогда не срабатывает.
KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {member.value for member in EventType} | {DIRECT_EVENT_TYPE}
)


@dataclass(frozen=True, slots=True)
class EventAudience:
    """Кто причастен к событию и к каким объектам оно относится.

    Всё посчитано из нагрузки. `roles` — ключ актора и набор ролей, в которых он
    оказался: один и тот же актор бывает и автором, и исполнителем сразу, и подписке
    достаточно совпасть по любой из ролей.

    `project_keys` — набор, а не одно значение, и это не запас на будущее. Добавление
    задачи в проект приходит обычным `issue.updated` с полем `project`, и уход из
    проекта выглядит так же. Подписчик проекта, из которого задачу забрали, обязан
    узнать об этом — значит в набор входит и прежнее значение, и новое.
    """

    roles: dict[str, frozenset[SubscriptionScope]] = field(default_factory=dict)
    issue_key: str | None = None
    issue_id: str | None = None
    queue_key: str | None = None
    project_keys: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class NotificationSummary:
    """Готовый текст уведомления и структурированные подробности к нему.

    Оба собираются один раз, при создании записи, и хранятся. Восстанавливать текст
    позже из события и текущего состояния задачи — значит показывать неверную историю:
    уведомление «задача назначена на вас» через час читалось бы как «задача назначена
    на Петра», потому что исполнителя с тех пор сменили.
    """

    body: str
    details: dict[str, Any] = field(default_factory=dict)


def audience_of(event_type: str, payload: Mapping[str, Any]) -> EventAudience:
    """Причастные к событию акторы и адреса объектов — всё из полезной нагрузки.

    Неизвестный тип события — не ошибка: возвращается пустая аудитория, и уведомлений
    не будет. Падать здесь нельзя, потому что подписчик работает в воркере, и
    исключение пометило бы событие недоставленным из-за типа, до которого этой механике
    вообще нет дела.
    """
    if event_type.startswith("comment."):
        return _comment_audience(event_type, payload)
    if event_type.startswith("checklist."):
        return _checklist_audience(payload)
    if event_type.startswith("link."):
        return _link_audience(payload)
    if event_type.startswith(("project.", "portfolio.")):
        return _planning_audience(payload)
    if event_type == EventType.STATUS_ISSUES_MOVED:
        return EventAudience(queue_key=payload.get("queue"))
    if event_type.startswith("issue."):
        return _issue_audience(payload)
    # Доска причастных акторов не имеет: у неё нет ни автора, ни участников.
    # До подписчика на область `all` они всё равно дойдут — этим и объясняется пустая
    # аудитория вместо отказа.
    return EventAudience()


def describe(event_type: str, payload: Mapping[str, Any]) -> NotificationSummary:
    """Текст уведомления и его подробности.

    Текст английский, как весь служебный слой проекта: перевод для интерфейса —
    забота фронтенда, и он выбирает его по `event_type` и `details`, а не по строке.
    Пользовательские данные (название задачи, текст реплики) подставляются как есть.

    Названий статусов и типов здесь нет, только ссылки (`TRK.open`): в снимке задачи
    лежат именно они, а сходить за отображаемым названием в базу нельзя — см. шапку
    модуля.
    """
    builder = _DESCRIBERS.get(event_type)
    summary = _describe_unknown(event_type, payload) if builder is None else builder(payload)
    return NotificationSummary(
        body=_clamp(summary.body, MAX_TEXT_LENGTH),
        details=summary.details,
    )


def digest_key(event_type: str, object_key: str) -> str:
    """Ключ склейки повторов: пара «объект + тип события».

    Десять правок одной задачи за минуту дают один ключ и одну запись в инбоксе со
    счётчиком, а не десять писем. Объект, а не задача, потому что у комментария и
    пункта чеклиста свой ключ (`TRK-7:<id>`): каждая новая реплика обязана быть
    отдельным уведомлением, а десять правок одной реплики — одним.

    Ключ намеренно не включает адресата: он одинаков у всех получателей события, а
    искать по нему приходится всегда вместе с `actor_id` — так ложится индекс.
    """
    return f"{event_type}:{object_key}"


def validate_subscription(
    scope: SubscriptionScope,
    scope_key: str | None,
    event_types: Iterable[str] | None,
) -> tuple[str | None, list[str]]:
    """Проверяет подписку и возвращает канонические `scope_key` и набор типов.

    Три правила, и каждое ловит свою молчаливую ошибку:

    - предметная область без ключа отбирает всё подряд, а не очередь `TRK`;
    - ролевая область с ключом выглядит настроенной, хотя ключ нигде не читается;
    - неизвестный тип события — опечатка, которая даёт подписку, никогда не
      срабатывающую. Такую подписку невозможно отличить от исправной, глядя на неё.
    """
    normalized_key = None if scope_key is None else scope_key.strip()
    if scope in TARGET_SCOPES and not normalized_key:
        raise InvalidSubscriptionError(
            details={
                "field": "scope_key",
                "reason": "required",
                "scope": scope.value,
                "scopes_with_key": sorted(item.value for item in TARGET_SCOPES),
            },
        )
    if scope not in TARGET_SCOPES and normalized_key:
        raise InvalidSubscriptionError(
            details={"field": "scope_key", "reason": "not_applicable", "scope": scope.value},
        )

    types = sorted({item.strip() for item in event_types or () if item.strip()})
    unknown = [item for item in types if item not in KNOWN_EVENT_TYPES]
    if unknown:
        raise InvalidSubscriptionError(
            details={"field": "event_types", "reason": "unknown", "unknown": unknown},
        )
    return (normalized_key or None), types


def matches_event_type(subscribed: Iterable[str], event_type: str) -> bool:
    """Проходит ли событие фильтр подписки. Пустой набор означает «все типы».

    Пустой набор — именно «все», а не «ни одного»: подписка без указания типов должна
    работать сразу, иначе заведение подписки в два шага (создать, потом перечислить
    типы) стало бы обязательным ритуалом.
    """
    types = tuple(subscribed)
    return not types or event_type in types


# --- Аудитория по видам событий ----------------------------------------------------


def _issue_audience(payload: Mapping[str, Any]) -> EventAudience:
    issue = payload.get("issue") or {}
    roles: dict[str, set[SubscriptionScope]] = {}
    _collect_issue_roles(roles, issue)
    return EventAudience(
        roles=_freeze(roles),
        issue_key=issue.get("key"),
        issue_id=issue.get("id"),
        queue_key=issue.get("queue"),
        project_keys=_project_keys(payload, issue),
    )


def _comment_audience(event_type: str, payload: Mapping[str, Any]) -> EventAudience:
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    roles: dict[str, set[SubscriptionScope]] = {}
    _collect_issue_roles(roles, issue)

    # Упомянутые берутся готовым полем, а не разбором текста заново: разбор живёт в
    # одном месте (`app/domain/comments.py`) и уже отсеял несуществующие ключи.
    mentions = set(comment.get("mentions") or ())
    if event_type == EventType.COMMENT_UPDATED:
        # Правка комментария: адресаты — только **новые** упоминания. Без вычитания
        # прежнего набора каждая правка опечатки уведомляла бы заново всех, кто был
        # упомянут в первой редакции.
        previous = payload.get("previous") or {}
        mentions -= set(previous.get("mentions") or ())
    for key in mentions:
        roles.setdefault(key, set()).add(SubscriptionScope.MENTION)

    return EventAudience(
        roles=_freeze(roles),
        issue_key=issue.get("key"),
        issue_id=issue.get("id"),
        queue_key=issue.get("queue"),
        project_keys=_project_keys(payload, issue),
    )


def _checklist_audience(payload: Mapping[str, Any]) -> EventAudience:
    issue = payload.get("issue") or {}
    item = payload.get("item") or {}
    roles: dict[str, set[SubscriptionScope]] = {}
    _collect_issue_roles(roles, issue)

    # У пункта свой необязательный исполнитель, и он может не совпадать с исполнителем
    # задачи: «сделать замеры» назначено на одного, сама задача — на другого. Роль та
    # же самая (`assignee`), потому что подписка «где я исполнитель» обязана покрывать
    # оба случая — заводить ради пункта отдельную область значило бы требовать от
    # каждого актора настроить на одну подписку больше.
    item_assignee = item.get("assignee")
    if item_assignee:
        roles.setdefault(item_assignee, set()).add(SubscriptionScope.ASSIGNEE)

    return EventAudience(
        roles=_freeze(roles),
        issue_key=issue.get("key"),
        issue_id=issue.get("id"),
        queue_key=issue.get("queue"),
        project_keys=_project_keys(payload, issue),
    )


def _link_audience(payload: Mapping[str, Any]) -> EventAudience:
    """Связь: причастны обе стороны, а адресуется уведомление исходной задаче.

    Ключ объекта у события связи — обе задачи сразу, а колонка уведомления одна.
    Исходная выбрана потому, что связь читается от неё (`TRK-7 depends_on TRK-9`), и
    вторая сторона всё равно названа в тексте и в подробностях.
    """
    issues = payload.get("issues") or {}
    source = issues.get("source") or {}
    target = issues.get("target") or {}
    roles: dict[str, set[SubscriptionScope]] = {}
    _collect_issue_roles(roles, source)
    _collect_issue_roles(roles, target)

    projects = set(_project_keys(payload, source)) | set(_project_keys(payload, target))
    return EventAudience(
        roles=_freeze(roles),
        issue_key=source.get("key"),
        issue_id=source.get("id"),
        queue_key=source.get("queue"),
        project_keys=frozenset(projects),
    )


def _planning_audience(payload: Mapping[str, Any]) -> EventAudience:
    """Проект или портфель: причастны руководитель и участники.

    Задачи у такого события нет вовсе, поэтому нет и записи в журнале изменений
    (`changelog_entries.issue_id` обязателен). Текст и адресаты собираются только из
    нагрузки — другого источника у этих типов не существует.
    """
    entity = payload.get("project") or payload.get("portfolio") or {}
    roles: dict[str, set[SubscriptionScope]] = {}
    lead = entity.get("lead")
    if lead:
        roles.setdefault(lead, set()).add(SubscriptionScope.MEMBER)
    for member in entity.get("members") or ():
        roles.setdefault(member, set()).add(SubscriptionScope.MEMBER)

    key = entity.get("key")
    return EventAudience(
        roles=_freeze(roles),
        project_keys=frozenset() if key is None else frozenset({key}),
    )


def _collect_issue_roles(
    roles: dict[str, set[SubscriptionScope]],
    issue: Mapping[str, Any],
) -> None:
    """Автор, исполнитель и наблюдатели из снимка задачи."""
    author = issue.get("author")
    if author:
        roles.setdefault(author, set()).add(SubscriptionScope.AUTHOR)
    assignee = issue.get("assignee")
    if assignee:
        roles.setdefault(assignee, set()).add(SubscriptionScope.ASSIGNEE)
    for follower in issue.get("followers") or ():
        roles.setdefault(follower, set()).add(SubscriptionScope.FOLLOWER)


def _project_keys(payload: Mapping[str, Any], issue: Mapping[str, Any]) -> frozenset[str]:
    """Проекты, к которым событие относится: текущий задачи и покинутый, если её увели.

    Прежнее значение берётся из `changes`, а не домысливается: перенос задачи между
    проектами приходит обычным `issue.updated` с полем `project`, и для подписчика
    старого проекта это событие «задача ушла». Без прежнего ключа он бы о ней просто
    перестал что-либо получать — молча.
    """
    keys = set()
    current = issue.get("project")
    if current:
        keys.add(current)
    for change in payload.get("changes") or ():
        if change.get("field") != "project":
            continue
        for value in (change.get("before"), change.get("after")):
            if value:
                keys.add(value)
    return frozenset(keys)


def _freeze(roles: Mapping[str, set[SubscriptionScope]]) -> dict[str, frozenset[SubscriptionScope]]:
    return {key: frozenset(value) for key, value in roles.items()}


# --- Текст по видам событий --------------------------------------------------------


def _describe_issue_created(payload: Mapping[str, Any]) -> NotificationSummary:
    issue = payload.get("issue") or {}
    key = issue.get("key", "?")
    return NotificationSummary(
        body=f"{key} created: {_clamp(issue.get('summary', ''), EXCERPT_LENGTH)}",
        details=_issue_details(issue),
    )


def _describe_issue_updated(payload: Mapping[str, Any]) -> NotificationSummary:
    issue = payload.get("issue") or {}
    fields = list(payload.get("fields") or ())
    key = issue.get("key", "?")
    changed = ", ".join(fields) if fields else "no fields"
    return NotificationSummary(
        body=f"{key} updated: {changed}",
        details=_issue_details(issue) | {"fields": fields},
    )


def _describe_status_changed(payload: Mapping[str, Any]) -> NotificationSummary:
    issue = payload.get("issue") or {}
    change = _change_of(payload, "status")
    key = issue.get("key", "?")
    before = None if change is None else change.get("before")
    after = issue.get("status") if change is None else change.get("after")
    return NotificationSummary(
        body=f"{key} status: {before or '-'} -> {after or '-'}",
        details=_issue_details(issue)
        | {"fields": list(payload.get("fields") or ()), "status_from": before, "status_to": after},
    )


def _describe_issue_assigned(payload: Mapping[str, Any]) -> NotificationSummary:
    issue = payload.get("issue") or {}
    key = issue.get("key", "?")
    assignee = issue.get("assignee")
    text = f"{key} assigned to {assignee}" if assignee else f"{key} is no longer assigned"
    return NotificationSummary(body=text, details=_issue_details(issue))


def _describe_issue_deleted(payload: Mapping[str, Any]) -> NotificationSummary:
    issue = payload.get("issue") or {}
    key = issue.get("key", "?")
    return NotificationSummary(
        body=f"{key} deleted: {_clamp(issue.get('summary', ''), EXCERPT_LENGTH)}",
        details=_issue_details(issue),
    )


def _describe_issues_moved(payload: Mapping[str, Any]) -> NotificationSummary:
    """Массовый перенос задач между статусами: одно уведомление на весь перенос.

    Разворачивать событие обратно в уведомление на каждую задачу нельзя — ради этого
    оно и было схлопнуто в шине (`app/services/events.py`). Ключи задач при этом лежат
    в подробностях целиком: агент, которому нужны конкретные задачи, разберёт список
    сам, не перечитывая событие.
    """
    status = payload.get("status") or {}
    count = payload.get("count", 0)
    return NotificationSummary(
        body=f"{count} issues moved from {status.get('from', '-')} to {status.get('to', '-')}",
        details={
            "count": count,
            "status_from": status.get("from"),
            "status_to": status.get("to"),
            "queue": payload.get("queue"),
            "issues": list(payload.get("issues") or ()),
        },
    )


def _describe_link(payload: Mapping[str, Any], *, removed: bool) -> NotificationSummary:
    link = payload.get("link") or {}
    verb = "removed" if removed else "added"
    source = link.get("source", "?")
    target = link.get("target", "?")
    link_type = link.get("type", "?")
    return NotificationSummary(
        body=f"Link {verb}: {source} {link_type} {target}",
        details={"source": source, "target": target, "link_type": link_type},
    )


def _describe_comment(payload: Mapping[str, Any], *, verb: str) -> NotificationSummary:
    comment = payload.get("comment") or {}
    issue = payload.get("issue") or {}
    author = comment.get("author", "?")
    key = issue.get("key", "?")
    # У удалённого комментария текста нет — плашка вместо отрывка. Показывать прежний
    # текст в уведомлении об удалении нельзя: удаление обязано убирать сказанное.
    body = _clamp(comment.get("body") or "", EXCERPT_LENGTH)
    tail = f": {body}" if body else ""
    return NotificationSummary(
        body=f"{author} {verb} on {key}{tail}",
        details={
            "comment": comment.get("id"),
            "author": author,
            "mentions": list(comment.get("mentions") or ()),
        },
    )


def _describe_checklist(payload: Mapping[str, Any], *, verb: str) -> NotificationSummary:
    item = payload.get("item") or {}
    issue = payload.get("issue") or {}
    key = issue.get("key", "?")
    text = _clamp(item.get("text") or "", EXCERPT_LENGTH)
    return NotificationSummary(
        body=f"{key}: checklist item {verb} - {text}",
        details={
            "item": item.get("id"),
            "is_done": item.get("is_done"),
            "assignee": item.get("assignee"),
        },
    )


def _describe_planning(payload: Mapping[str, Any], *, verb: str) -> NotificationSummary:
    kind = "Portfolio" if "portfolio" in payload else "Project"
    entity = payload.get("project") or payload.get("portfolio") or {}
    key = entity.get("key", "?")
    fields = list(payload.get("fields") or ())
    tail = f": {', '.join(fields)}" if fields else ""
    return NotificationSummary(
        body=f"{kind} {key} {verb}{tail}",
        details={"key": key, "name": entity.get("name"), "fields": fields},
    )


def _describe_board(payload: Mapping[str, Any], *, verb: str) -> NotificationSummary:
    board = payload.get("board") or {}
    return NotificationSummary(
        body=f"Board {board.get('name', '?')} {verb}",
        details={"board": board.get("id"), "fields": list(payload.get("fields") or ())},
    )


def _describe_board_ranked(payload: Mapping[str, Any]) -> NotificationSummary:
    board = payload.get("board") or {}
    issue = payload.get("issue") or {}
    return NotificationSummary(
        body=f"{issue.get('key', '?')} moved on board {board.get('name', '?')}",
        details={"board": board.get("id"), "issue": issue.get("key")},
    )


def _describe_unknown(event_type: str, payload: Mapping[str, Any]) -> NotificationSummary:
    """Событие, для которого текста не написано.

    Молчать нельзя: тип, добавленный следующей задачей и забытый здесь, дал бы
    уведомление с пустой строкой, и понять по инбоксу, что произошло, было бы нельзя.
    Тип события в тексте — минимум, который всегда верен.
    """
    issue = payload.get("issue") or {}
    key = issue.get("key")
    return NotificationSummary(
        body=f"{event_type}{f' on {key}' if key else ''}",
        details={"fields": list(payload.get("fields") or ())},
    )


#: Тип события → сборщик текста. Словарём, а не лестницей `if`: тип, для которого текст
#: не написан, обязан находиться поиском по этому словарю, а не чтением ветвлений.
_DESCRIBERS = {
    EventType.ISSUE_CREATED.value: _describe_issue_created,
    EventType.ISSUE_UPDATED.value: _describe_issue_updated,
    EventType.ISSUE_STATUS_CHANGED.value: _describe_status_changed,
    EventType.ISSUE_ASSIGNED.value: _describe_issue_assigned,
    EventType.ISSUE_DELETED.value: _describe_issue_deleted,
    EventType.STATUS_ISSUES_MOVED.value: _describe_issues_moved,
    EventType.LINK_CREATED.value: lambda payload: _describe_link(payload, removed=False),
    EventType.LINK_DELETED.value: lambda payload: _describe_link(payload, removed=True),
    EventType.COMMENT_CREATED.value: lambda payload: _describe_comment(payload, verb="commented"),
    EventType.COMMENT_UPDATED.value: lambda payload: _describe_comment(
        payload, verb="edited a comment"
    ),
    EventType.COMMENT_DELETED.value: lambda payload: _describe_comment(
        payload, verb="deleted a comment"
    ),
    EventType.CHECKLIST_ITEM_ADDED.value: lambda payload: _describe_checklist(
        payload, verb="added"
    ),
    EventType.CHECKLIST_ITEM_UPDATED.value: lambda payload: _describe_checklist(
        payload, verb="updated"
    ),
    EventType.CHECKLIST_ITEM_CHECKED.value: lambda payload: _describe_checklist(
        payload, verb="done"
    ),
    EventType.CHECKLIST_ITEM_UNCHECKED.value: lambda payload: _describe_checklist(
        payload, verb="reopened"
    ),
    EventType.CHECKLIST_ITEM_MOVED.value: lambda payload: _describe_checklist(
        payload, verb="moved"
    ),
    EventType.CHECKLIST_ITEM_REMOVED.value: lambda payload: _describe_checklist(
        payload, verb="removed"
    ),
    EventType.PROJECT_CREATED.value: lambda payload: _describe_planning(payload, verb="created"),
    EventType.PROJECT_UPDATED.value: lambda payload: _describe_planning(payload, verb="updated"),
    EventType.PROJECT_ARCHIVED.value: lambda payload: _describe_planning(payload, verb="archived"),
    EventType.PROJECT_RESTORED.value: lambda payload: _describe_planning(payload, verb="restored"),
    EventType.PORTFOLIO_CREATED.value: lambda payload: _describe_planning(payload, verb="created"),
    EventType.PORTFOLIO_UPDATED.value: lambda payload: _describe_planning(payload, verb="updated"),
    EventType.PORTFOLIO_ARCHIVED.value: lambda payload: _describe_planning(
        payload, verb="archived"
    ),
    EventType.PORTFOLIO_RESTORED.value: lambda payload: _describe_planning(
        payload, verb="restored"
    ),
    EventType.BOARD_CREATED.value: lambda payload: _describe_board(payload, verb="created"),
    EventType.BOARD_UPDATED.value: lambda payload: _describe_board(payload, verb="updated"),
    EventType.BOARD_DELETED.value: lambda payload: _describe_board(payload, verb="deleted"),
    EventType.BOARD_ISSUE_RANKED.value: _describe_board_ranked,
}


def _issue_details(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Идентификаторы задачи в подробностях уведомления.

    Агент принимает решения по ним программно, а не разбором текста: ключ задачи, её
    статус, исполнитель и очередь — то, по чему он решает, браться ли за неё сейчас.
    """
    return {
        "issue": issue.get("key"),
        "queue": issue.get("queue"),
        "status": issue.get("status"),
        "assignee": issue.get("assignee"),
        "project": issue.get("project"),
    }


def _change_of(payload: Mapping[str, Any], field_name: str) -> Mapping[str, Any] | None:
    for change in payload.get("changes") or ():
        if change.get("field") == field_name:
            return change
    return None


def _clamp(value: str, limit: int) -> str:
    """Обрезает текст по границе, добавляя многоточие. Пустую строку не трогает."""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}…"


def object_type_of(event_type: str) -> str:
    """Вид объекта события по его типу — для записи уведомления без похода в базу.

    Дублирует то, что подписчик и так получает в конверте события, ровно для одного
    случая: адресного уведомления от правила автоматики, у которого события нет вовсе.
    """
    if event_type.startswith("comment."):
        return ObjectType.COMMENT.value
    if event_type.startswith("checklist."):
        return ObjectType.CHECKLIST_ITEM.value
    if event_type.startswith("link."):
        return ObjectType.LINK.value
    if event_type.startswith("project."):
        return ObjectType.PROJECT.value
    if event_type.startswith("portfolio."):
        return ObjectType.PORTFOLIO.value
    if event_type.startswith("board."):
        return ObjectType.BOARD.value
    if event_type == EventType.STATUS_ISSUES_MOVED:
        return ObjectType.STATUS.value
    return ObjectType.ISSUE.value
