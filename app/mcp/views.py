"""Представления объектов для инструментов MCP: то, что увидит модель.

Каждое поле ответа съедает контекст агента, поэтому представления здесь **компактнее**
ответов REST: служебных идентификаторов, времён создания и правки нет там, где по ним не
адресуют и не решают. Это не сокращение ради красоты — задача 16 называет экономию
контекста главным требованием: сто задач с полным набором полей и полной историей
делают сервер непригодным на реальных объёмах.

## Три приёма экономии, и все три видимы клиенту

1. **Выбор полей.** Задача собирается из именованного набора: `brief` — восемь полей,
   `full` — все. Тот же механизм обслуживает параметр `fields` поиска, поэтому «краткая
   задача» и «задача с выбранными полями» — не два разных представления, а одно.
2. **Усечение длинных текстов.** Описание задачи и тело комментария обрезаются до
   `TRACKER_MCP_TEXT_LIMIT`, и рядом появляется признак `..._truncated` с полной длиной.
   Молчаливая обрезка была бы хуже отсутствия текста: агент принял бы обрывок за целое.
3. **Ссылки вместо вложенных записей.** Очередь — ключ, статус и тип — ссылки
   справочника, акторы — ключи. Полные записи отдаёт конфигурация очереди, и рассылать
   их в каждой задаче значило бы повторять один и тот же словарь сто раз подряд.

Формы полей совпадают с REST (`app/api/schemas/`), и это осознанное повторение имён, а
не общий код: `mcp` не имеет права зависеть от `api` (`docs/CONVENTIONS.md`). Совпадать
обязаны имена и смысл, а состав — намеренно разный.

Момент времени приводится к строке ISO 8601 здесь, а не в сериализаторе MCP: инструмент
возвращает обычный словарь, и полагаться на то, как чужая библиотека свернёт `datetime`,
означало бы менять контракт вместе с её версией.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.db.models.automation import AutomationRule, AutomationRun
from app.db.models.board import Board, BoardColumn
from app.db.models.catalog import IssueType, Status
from app.db.models.checklist import ChecklistItem
from app.db.models.comment import Comment
from app.db.models.event import ChangelogEntry
from app.db.models.field import Field
from app.db.models.issue import Issue
from app.db.models.notification import Notification
from app.db.models.project import Portfolio, Project
from app.db.models.queue import Queue
from app.domain.projects import PlanningKind, Progress
from app.services.automation import RuleView
from app.services.catalogs import CatalogEntry, format_entry_ref
from app.services.fields import field_ref
from app.services.links import IssueLinkView, IssueTreeNode
from app.services.notifications import InboxWait
from app.services.queues import QueueConfig
from app.services.workflow import TransitionAvailability, WorkflowImpact, WorkflowView

#: Поля краткого представления задачи. Отвечают на вопрос «что это и чем занято»:
#: по ним агент решает, читать ли задачу целиком, и ни одно из них не длиннее строки.
BRIEF_FIELDS: tuple[str, ...] = (
    "key",
    "summary",
    "status",
    "issue_type",
    "priority",
    "assignee",
    "deadline",
    "updated_at",
)


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Текст до предела и признак обрезки.

    Признак возвращается отдельно, а не приписывается к тексту многоточием: агент,
    сравнивающий строки, не должен принимать метку за часть значения.
    """
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def issue(
    entry: Issue,
    *,
    fields: Sequence[str] = (),
    value_refs: Sequence[str] = (),
    text_limit: int,
) -> dict[str, Any]:
    """Задача с выбранными полями. Пустой набор полей означает «все».

    Ключ приезжает всегда, даже если его не просили: выдача без него бесполезна — по
    ней нельзя ни прочитать задачу, ни сослаться на неё.
    """
    description, truncated = clip(entry.description, text_limit)
    payload: dict[str, Any] = {
        "key": entry.key,
        "queue": entry.queue.key,
        "issue_type": format_entry_ref(entry.issue_type),
        "status": format_entry_ref(entry.status),
        "status_category": entry.status.category.value,
        "resolution": None if entry.resolution is None else format_entry_ref(entry.resolution),
        "priority": entry.priority.value,
        "summary": entry.summary,
        "description": description,
        "author": entry.author.key,
        "assignee": None if entry.assignee is None else entry.assignee.key,
        "followers": [follower.key for follower in entry.followers],
        "deadline": moment(entry.deadline),
        "tags": list(entry.tags),
        "project": None if entry.project is None else entry.project.key,
        "values": _selected_values(entry, value_refs),
        "version": entry.version,
        "created_at": moment(entry.created_at),
        "updated_at": moment(entry.updated_at),
    }
    if truncated:
        payload["description_truncated"] = True
        payload["description_length"] = len(entry.description)
    if fields:
        selected = {*fields, "key"}
        payload = {name: value for name, value in payload.items() if name in selected}
    return payload


def issue_brief(entry: Issue, *, text_limit: int) -> dict[str, Any]:
    """Задача одной строкой смысла: восемь полей из `BRIEF_FIELDS`."""
    return issue(entry, fields=BRIEF_FIELDS, text_limit=text_limit)


def _selected_values(entry: Issue, value_refs: Sequence[str]) -> dict[str, Any]:
    """Значения кастомных полей: все либо только названные ссылками в `fields`."""
    if not value_refs:
        return dict(entry.values)
    return {ref: entry.values[ref] for ref in value_refs if ref in entry.values}


def changelog_entry(entry: ChangelogEntry) -> dict[str, Any]:
    """Запись истории изменений: кто, что и с какого значения на какое."""
    return {
        "event_type": entry.event_type,
        "actor": entry.actor.key,
        "changes": [dict(change) for change in entry.changes],
        "created_at": moment(entry.created_at),
    }


def comment(entry: Comment, *, text_limit: int) -> dict[str, Any]:
    """Реплика обсуждения. Удалённая остаётся плашкой: тела нет, признак стоит."""
    body, truncated = clip(entry.body or "", text_limit)
    payload: dict[str, Any] = {
        "id": str(entry.id),
        "author": entry.author.key,
        "body": None if entry.is_deleted else body,
        "mentions": list(entry.mentions),
        "is_deleted": entry.is_deleted,
        "edited_at": moment(entry.edited_at),
        "created_at": moment(entry.created_at),
    }
    if truncated and not entry.is_deleted:
        payload["body_truncated"] = True
        payload["body_length"] = len(entry.body or "")
    return payload


def checklist_item(item: ChecklistItem) -> dict[str, Any]:
    """Пункт чеклиста. Позиции здесь нет намеренно: место задаётся соседом (`after`)."""
    return {
        "id": str(item.id),
        "text": item.text,
        "is_done": item.is_done,
        "assignee": None if item.assignee is None else item.assignee.key,
        "deadline": moment(item.deadline),
    }


def link(view: IssueLinkView) -> dict[str, Any]:
    """Связь глазами одной из двух задач: тип такой, каким его видит именно она.

    `view.issue` — задача на **другой** стороне: сценарий уже развернул связь к тому,
    кто спрашивал, и определять сторону здесь второй раз значило бы завести второе
    толкование направления.
    """
    other = view.issue
    return {
        "id": str(view.link.id),
        "type": view.link_type.value,
        "issue": other.key,
        "summary": other.summary,
        "status": format_entry_ref(other.status),
    }


def tree(node: IssueTreeNode) -> dict[str, Any]:
    """Дерево подзадач. `has_more_children` отличает обрезанную ветку от листа."""
    payload: dict[str, Any] = {
        "key": node.issue.key,
        "summary": node.issue.summary,
        "status": format_entry_ref(node.issue.status),
        "status_category": node.issue.status.category.value,
        "assignee": None if node.issue.assignee is None else node.issue.assignee.key,
    }
    if node.children:
        payload["children"] = [tree(child) for child in node.children]
    if node.has_more_children:
        payload["has_more_children"] = True
    return payload


def notification(entry: Notification) -> dict[str, Any]:
    """Запись инбокса: готовый текст человеку, идентификаторы — агенту."""
    return {
        "id": str(entry.id),
        "event_type": entry.event_type,
        "object_type": entry.object_type,
        "object_key": entry.object_key,
        "issue": entry.issue_key,
        "body": entry.body,
        "details": dict(entry.details),
        "count": entry.count,
        "is_read": entry.is_read,
        "created_at": moment(entry.created_at),
    }


def inbox_wait(outcome: InboxWait) -> dict[str, Any]:
    """Итог ожидания.

    `waited` и `timed_out` обязаны доехать до агента: по коду ответа «ничего не пришло»
    от сбоя не отличить — успешны оба случая.
    """
    return {
        "notifications": [notification(item) for item in outcome.notifications],
        "waited": round(outcome.waited, 3),
        "timed_out": outcome.timed_out,
    }


def queue(entry: Queue) -> dict[str, Any]:
    """Очередь: ключ, название и значения по умолчанию, которыми заполняются задачи."""
    return {
        "key": entry.key,
        "name": entry.name,
        "description": entry.description,
        "owner": entry.owner.key,
        "default_issue_type": format_entry_ref(entry.default_issue_type),
        "default_status": format_entry_ref(entry.default_status),
        "is_archived": entry.is_archived,
    }


def catalog_entry(entry: CatalogEntry) -> dict[str, Any]:
    """Запись справочника: ссылка, название и то, чем этот вид отличается от других."""
    payload: dict[str, Any] = {
        "ref": format_entry_ref(entry),
        "name": entry.name,
        "is_active": entry.is_active,
    }
    if isinstance(entry, Status):
        payload["category"] = entry.category.value
    if isinstance(entry, IssueType) and entry.icon:
        payload["icon"] = entry.icon
    return payload


def field(entry: Field) -> dict[str, Any]:
    """Описание кастомного поля: под этой же ссылкой лежит значение в `values`."""
    payload: dict[str, Any] = {
        "ref": field_ref(entry),
        "name": entry.name,
        "value_type": entry.value_type.value,
        "is_multiple": entry.is_multiple,
        "is_required": entry.is_required,
        "is_hidden": entry.is_hidden,
    }
    if entry.options:
        payload["options"] = [option["key"] for option in entry.options]
    if entry.default_value is not None:
        payload["default_value"] = entry.default_value
    if entry.issue_types:
        payload["issue_types"] = [format_entry_ref(item) for item in entry.issue_types]
    return payload


def queue_config(config: QueueConfig) -> dict[str, Any]:
    """Всё, чем можно заполнять задачу в этой очереди. Только активные записи."""
    return {
        "queue": queue(config.queue),
        "issue_types": [catalog_entry(entry) for entry in config.issue_types],
        "statuses": [catalog_entry(entry) for entry in config.statuses],
        "resolutions": [catalog_entry(entry) for entry in config.resolutions],
        "fields": [field(entry) for entry in config.fields],
        "workflows": [workflow(view) for view in config.workflows],
    }


def workflow(view: WorkflowView) -> dict[str, Any]:
    """Граф процесса вместе с отчётом о последствиях его текущей формы."""
    graph = view.workflow
    return {
        "id": str(graph.id),
        "queue": graph.queue.key,
        "name": graph.name,
        "issue_types": [format_entry_ref(entry) for entry in view.issue_types],
        "initial_status": graph.initial_status.ref,
        "statuses": [
            {
                "ref": item.status.ref,
                "name": item.status.name,
                "category": item.status.category.value,
                "is_initial": item.status_id == graph.initial_status_id,
            }
            for item in graph.status_links
        ],
        "transitions": [
            {
                "id": str(item.id),
                "name": item.name,
                "from_status": None if item.from_status is None else item.from_status.ref,
                "to_status": item.to_status.ref,
                "required_fields": list(item.required_fields),
                "requires_resolution": item.requires_resolution,
            }
            for item in graph.transitions
        ],
        "impact": impact(view.impact),
    }


def impact(report: WorkflowImpact) -> dict[str, Any]:
    """Что процесс делает с живыми задачами: где они застрянут после применения графа."""
    return {
        "issues_without_outgoing_transitions": report.issues_without_outgoing_transitions,
        "by_status": [
            {"status": status, "issues": count} for status, count in report.by_status.items()
        ],
    }


def transition(item: TransitionAvailability) -> dict[str, Any]:
    """Переход задачи: можно ли им воспользоваться прямо сейчас и чего не хватает."""
    return {
        "id": str(item.transition.id),
        "name": item.transition.name,
        "to_status": item.transition.to_status.ref,
        "to_status_category": item.transition.to_status.category.value,
        "requires_resolution": item.transition.requires_resolution,
        "required_fields": list(item.transition.required_fields),
        "is_available": item.is_available,
        "missing_fields": list(item.missing_fields),
    }


def project(entry: Project, *, progress: Progress) -> dict[str, Any]:
    """Проект с прогрессом. Прогресс считается при чтении, а не хранится колонкой."""
    return {
        "key": entry.key,
        "kind": PlanningKind.PROJECT.value,
        "name": entry.name,
        "description": entry.description,
        "status": entry.status.value,
        "lead": entry.lead.key,
        "members": [member.key for member in entry.members],
        "portfolio": None if entry.portfolio is None else entry.portfolio.key,
        "start_date": day(entry.start_date),
        "end_date": day(entry.end_date),
        "tags": list(entry.tags),
        "is_archived": entry.is_archived,
        "progress": _progress(progress),
    }


def portfolio(
    entry: Portfolio,
    *,
    progress: Progress,
    counts: Mapping[UUID, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Портфель с прогрессом по задачам входящих проектов и составом в числах."""
    payload: dict[str, Any] = {
        "key": entry.key,
        "kind": PlanningKind.PORTFOLIO.value,
        "name": entry.name,
        "description": entry.description,
        "status": entry.status.value,
        "lead": entry.lead.key,
        "members": [member.key for member in entry.members],
        "parent": None if entry.parent is None else entry.parent.key,
        "start_date": day(entry.start_date),
        "end_date": day(entry.end_date),
        "tags": list(entry.tags),
        "is_archived": entry.is_archived,
        "progress": _progress(progress),
    }
    if counts is not None:
        projects, portfolios = counts.get(entry.id, (0, 0))
        payload["content"] = {"projects": projects, "portfolios": portfolios}
    return payload


def board(entry: Board) -> dict[str, Any]:
    """Доска: чем отбирает задачи и как разложены её колонки."""
    return {
        "id": str(entry.id),
        "name": entry.name,
        "description": entry.description,
        "saved_filter": str(entry.saved_filter_id),
        "columns": [column(item) for item in entry.columns],
    }


def column(entry: BoardColumn) -> dict[str, Any]:
    """Колонка доски: имя, статусы, лимит незавершённой работы."""
    return {
        "id": str(entry.id),
        "name": entry.name,
        "statuses": [link.status.ref for link in entry.status_links],
        "wip_limit": entry.wip_limit,
    }


def rule(view: RuleView) -> dict[str, Any]:
    """Правило автоматики: объявление из кода плюс настройка из базы.

    `params_schema` едет целиком: по ней агент собирает `params` для настройки, и
    пересказать её короче нечем — у каждого правила она своя.
    """
    entry: AutomationRule = view.rule
    definition = view.definition
    return {
        "key": entry.rule_key,
        "name": entry.rule_key if definition is None else definition.name,
        "description": "" if definition is None else definition.description,
        "kind": None if definition is None else definition.kind.value,
        "events": [] if definition is None else list(definition.events),
        "schedule_seconds": (
            None
            if definition is None or definition.schedule is None
            else int(definition.schedule.total_seconds())
        ),
        "is_available": view.is_available,
        "is_enabled": entry.is_enabled,
        "queue": None if entry.queue is None else entry.queue.key,
        "saved_filter": None if entry.saved_filter_id is None else str(entry.saved_filter_id),
        "params": dict(entry.params),
        "params_schema": {} if definition is None else definition.params_schema(),
        "last_run_at": moment(entry.last_run_at),
        "next_run_at": moment(entry.next_run_at),
    }


def run(entry: AutomationRun) -> dict[str, Any]:
    """Запись журнала срабатываний.

    Неудача правила приезжает сюда `status: failed` вместе с текстом причины и **не**
    является сбоем вызова: проброс исключения откатил бы транзакцию вместе с этой
    записью, и единственный след неудачного макроса пропал бы.
    """
    return {
        "id": str(entry.id),
        "rule": entry.rule_key,
        "issue": entry.issue_key,
        "status": entry.status.value,
        "trigger": entry.trigger.value,
        "reason": entry.reason,
        "error": entry.error,
        "actions": list(entry.actions),
        "created_at": moment(entry.created_at),
    }


def page(items: Iterable[dict[str, Any]], *, next_cursor: str | None) -> dict[str, Any]:
    """Страница коллекции. Форма одна на все инструменты, как оболочка ответа в REST.

    `has_more` дублирует наличие курсора намеренно: агент принимает по нему решение, а
    сравнение с `null` — лишний шаг рассуждения на каждом вызове.
    """
    return {
        "items": list(items),
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    }


def _progress(progress: Progress) -> dict[str, Any]:
    """Готовность по задачам.

    Счётчики едут рядом с долей, а `ratio` у объекта без задач — `null`, а не ноль:
    «нечего делать» и «ничего не сделано» — разные ответы, и ноль их склеил бы.
    """
    return {"total": progress.total, "done": progress.done, "ratio": progress.ratio}


def moment(value: datetime | None) -> str | None:
    """Момент времени в ISO 8601. Хранится он в UTC, поэтому приводить ничего не нужно."""
    return None if value is None else value.isoformat()


def day(value: date | None) -> str | None:
    """Календарная дата в ISO 8601 — без времени и без зоны, как она и хранится."""
    return None if value is None else value.isoformat()
