"""Чистые правила графа воркфлоу и готовые шаблоны процессов.

Модуль не знает ни про SQLAlchemy, ни про HTTP. Сервис разрешает ссылки на статусы и
поля, превращает ORM-объекты в определения ниже и вызывает единственный валидатор.
Благодаря этому массовое сохранение и точечные операции не могут разойтись в том, что
они считают корректным процессом.
"""

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.domain.catalogs import StatusCategory
from app.domain.errors import InvalidWorkflowGraphError

MAX_WORKFLOW_NAME_LENGTH = 255
MAX_TRANSITION_NAME_LENGTH = 255


class WorkflowTemplateKey(StrEnum):
    """Готовые процессы, из которых можно создать редактируемый воркфлоу очереди."""

    SIMPLE = "simple"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class WorkflowTemplate:
    """Описание шаблона без привязки к конкретным строкам справочника."""

    key: WorkflowTemplateKey
    name: str
    description: str
    includes_review: bool


WORKFLOW_TEMPLATES: tuple[WorkflowTemplate, ...] = (
    WorkflowTemplate(
        key=WorkflowTemplateKey.SIMPLE,
        name="Simple workflow",
        description="Open, work, complete and reopen",
        includes_review=False,
    ),
    WorkflowTemplate(
        key=WorkflowTemplateKey.REVIEW,
        name="Workflow with review",
        description="Open, work, review, complete and reopen",
        includes_review=True,
    ),
)


@dataclass(frozen=True, slots=True)
class WorkflowStatusDefinition:
    """Статус как узел графа: стабильная ссылка и машинная категория."""

    ref: str
    category: StatusCategory


@dataclass(frozen=True, slots=True)
class TransitionDefinition:
    """Переход в транспортно- и хранилище-независимом виде."""

    name: str
    source_status: str | None
    target_status: str
    required_fields: tuple[str, ...] = ()
    requires_resolution: bool = False
    id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WorkflowGraphDefinition:
    """Полный граф, который валидируется и сохраняется атомарно."""

    initial_status: str
    statuses: tuple[WorkflowStatusDefinition, ...]
    transitions: tuple[TransitionDefinition, ...]


def validate_workflow_name(name: str) -> str:
    """Непустое однострочное имя, пригодное и для кнопки, и для списка."""
    return _validate_name(name, field="name", maximum=MAX_WORKFLOW_NAME_LENGTH)


def validate_transition_name(name: str) -> str:
    """Непустое однострочное название действия перехода."""
    return _validate_name(name, field="transition.name", maximum=MAX_TRANSITION_NAME_LENGTH)


def normalize_required_fields(fields: Iterable[str]) -> tuple[str, ...]:
    """Убирает повторы обязательных полей, сохраняя порядок для формы перехода."""
    result: list[str] = []
    seen: set[str] = set()
    for field in fields:
        normalized = field.strip()
        if not normalized:
            raise InvalidWorkflowGraphError(
                details={"problems": [{"reason": "empty_required_field"}]}
            )
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def validate_graph(graph: WorkflowGraphDefinition) -> None:
    """Проверяет структурную целостность и достижимость завершения из каждого узла.

    Переход с `source_status=None` считается доступным из любого статуса, кроме самой
    цели: смена статуса на тот же статус не является переходом и события не порождает.
    Статусы категории `done` могут быть терминальными; любой другой статус обязан иметь
    путь хотя бы к одному `done`.
    """
    problems: list[dict[str, Any]] = []
    status_by_ref: dict[str, WorkflowStatusDefinition] = {}
    for status in graph.statuses:
        if status.ref in status_by_ref:
            problems.append({"reason": "duplicate_status", "status": status.ref})
        status_by_ref[status.ref] = status

    if not status_by_ref:
        problems.append({"reason": "no_statuses"})
    if graph.initial_status not in status_by_ref:
        problems.append({"reason": "initial_status_missing", "status": graph.initial_status})

    adjacency: dict[str, set[str]] = {ref: set() for ref in status_by_ref}
    seen_actions: set[tuple[str | None, str, str]] = set()
    for index, transition in enumerate(graph.transitions):
        location = {"transition": index, "name": transition.name}
        try:
            validate_transition_name(transition.name)
        except InvalidWorkflowGraphError as error:
            problems.extend(error.details.get("problems", []))

        if transition.source_status is not None and transition.source_status not in status_by_ref:
            problems.append(
                location | {"reason": "source_status_missing", "status": transition.source_status}
            )
        if transition.target_status not in status_by_ref:
            problems.append(
                location | {"reason": "target_status_missing", "status": transition.target_status}
            )
            continue
        if transition.source_status == transition.target_status:
            problems.append(location | {"reason": "self_transition"})

        action = (
            transition.source_status,
            transition.target_status,
            transition.name.strip(),
        )
        if action in seen_actions:
            problems.append(
                location
                | {
                    "reason": "duplicate_transition",
                    "source_status": transition.source_status,
                    "target_status": transition.target_status,
                }
            )
        seen_actions.add(action)

        target = status_by_ref[transition.target_status]
        if target.category is StatusCategory.DONE and not transition.requires_resolution:
            problems.append(location | {"reason": "done_transition_requires_resolution"})
        if target.category is not StatusCategory.DONE and transition.requires_resolution:
            problems.append(location | {"reason": "resolution_only_for_done_transition"})

        if transition.source_status is None:
            for source_ref in adjacency:
                if source_ref != transition.target_status:
                    adjacency[source_ref].add(transition.target_status)
        elif (
            transition.source_status in adjacency
            and transition.source_status != transition.target_status
        ):
            adjacency[transition.source_status].add(transition.target_status)

    done_statuses = {
        status.ref for status in status_by_ref.values() if status.category is StatusCategory.DONE
    }
    if not done_statuses:
        problems.append({"reason": "done_status_missing"})

    if graph.initial_status in status_by_ref:
        reachable = _reachable_from(graph.initial_status, adjacency)
        for ref in status_by_ref.keys() - reachable:
            problems.append({"reason": "unreachable_status", "status": ref})

    for ref, status in status_by_ref.items():
        if status.category is StatusCategory.DONE:
            continue
        if not adjacency[ref]:
            problems.append({"reason": "dead_end", "status": ref})
        elif not (_reachable_from(ref, adjacency) & done_statuses):
            problems.append({"reason": "no_path_to_done", "status": ref})

    if problems:
        raise InvalidWorkflowGraphError(details={"problems": problems})


def missing_required_fields(
    transition: TransitionDefinition,
    filled_fields: set[str] | frozenset[str],
) -> tuple[str, ...]:
    """Какие требования конкретного перехода не выполнены в целевом состоянии задачи."""
    required = list(transition.required_fields)
    if transition.requires_resolution and "resolution" not in required:
        required.append("resolution")
    return tuple(field for field in required if field not in filled_fields)


def filled_field_names(
    values: Mapping[str, Any],
    *,
    system_values: Mapping[str, Any],
) -> frozenset[str]:
    """Имена заполненных системных и кастомных полей.

    `False` и `0` считаются значениями; пустая строка и пустая коллекция — нет. Логика
    одна для списка доступных переходов и для проверки фактического выполнения.
    """
    filled = {name for name, value in system_values.items() if _is_filled(value)}
    filled.update(name for name, value in values.items() if _is_filled(value))
    return frozenset(filled)


def template_by_key(key: WorkflowTemplateKey) -> WorkflowTemplate:
    """Готовый шаблон по стабильному ключу."""
    return next(template for template in WORKFLOW_TEMPLATES if template.key is key)


def _reachable_from(start: str, adjacency: Mapping[str, set[str]]) -> set[str]:
    reached: set[str] = set()
    pending = deque([start])
    while pending:
        current = pending.popleft()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(adjacency.get(current, ()))
    return reached


def _validate_name(name: str, *, field: str, maximum: int) -> str:
    normalized = name.strip()
    problems: list[dict[str, Any]] = []
    if not normalized:
        problems.append({"reason": "required", "field": field})
    if "\n" in normalized or "\r" in normalized:
        problems.append({"reason": "multiline_not_allowed", "field": field})
    if len(normalized) > maximum:
        problems.append(
            {"reason": "too_long", "field": field, "max": maximum, "got": len(normalized)}
        )
    if problems:
        raise InvalidWorkflowGraphError(details={"problems": problems})
    return normalized


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    if isinstance(value, Mapping):
        return bool(value)
    return True
