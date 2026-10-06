"""Инструмент `get_task`: пакет преемника — всё о задаче одним вызовом.

Пакет совпадает с `GET /api/v1/tasks/{key}` поле в поле; связи здесь — со стороны этой
задачи, опись дела — строками из `app/mcp/tools/case/views.py`.
"""

from datetime import datetime
from typing import Annotated

import pydantic_core
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from app.domain.tasks import PARENT_GOAL_LIMIT, clip_parent_goal
from app.mcp.arguments import TaskKeyArg
from app.mcp.enums import DecisionStatusSchema, LinkKindSchema, TaskStatusSchema
from app.mcp.tools.case.views import EntryView, HeadingView, entry, heading
from app.mcp.tools.tasks.state import TaskBriefCardView, TaskStateView, task_state
from app.mcp.tools.tasks.views import FeaturesView, TaskView, features, task
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import AuthorView, author
from app.services import tasks as tasks_service
from app.services.decisions import CitedDecision, DecisionRef
from app.services.links import TaskLink
from app.services.tasks import TaskPackage


class LinkOtherView(BaseModel):
    """Task on the other side of a link."""

    key: str
    title: str
    status: TaskStatusSchema


class ParentCardView(LinkOtherView):
    """Parent task: key, title, status and its goal."""

    goal: str = Field(
        description=f"The parent's `goal` section, cut at {PARENT_GOAL_LIMIT} characters"
    )
    goal_truncated: bool = Field(
        description="`true` when `goal` was cut and the full text is longer"
    )


class LinkView(BaseModel):
    """Link seen from this task: `kind` is the role of this task."""

    kind: LinkKindSchema
    other: LinkOtherView
    author: AuthorView
    created_at: datetime


def link_other(value: TaskLink) -> LinkOtherView:
    """Задача на другом конце связи: ключ, название и статус — родитель или ребёнок."""
    return LinkOtherView(key=value.other.key, title=value.other.title, status=value.other.status)


def link(value: TaskLink) -> LinkView:
    """Связь со стороны своей задачи: вид назван ролью **этой** задачи.

    В `other` лежит задача на **другом** конце — сторону вычислил сценарий, и определять
    её здесь во второй раз не нужно и неверно: канонизация могла записать связь в
    обратном порядке (`docs/notes/mcp.md`).
    """
    return LinkView(
        kind=value.kind,
        other=LinkOtherView(
            key=value.other.key, title=value.other.title, status=value.other.status
        ),
        author=author(value.author),
        created_at=value.created_at,
    )


class DecisionRefView(BaseModel):
    """Project decision named by its reference."""

    ref: str = Field(
        description="Address of the `decision` entry in the project's case",
        examples=["TRK#15"],
    )
    title: str
    status: DecisionStatusSchema


class CitedDecisionView(DecisionRefView):
    """Project decision the task relies on, with its status computed on read."""

    superseded_by: DecisionRefView | None = Field(
        description=(
            "The later decision that named this one in `supersedes`, with its own status; "
            "`null` while this one is in force"
        )
    )


def decision_ref(value: DecisionRef) -> DecisionRefView:
    """Решение, названное ссылкой: адрес, заголовок и статус."""
    return DecisionRefView(ref=value.ref, title=value.title, status=value.status)


def cited_decision(value: CitedDecision) -> CitedDecisionView:
    """Решение, на которое ссылается задача, и его преемник — тот же набор, что в REST."""
    return CitedDecisionView(
        ref=value.ref,
        title=value.title,
        status=value.status,
        superseded_by=None if value.superseded_by is None else decision_ref(value.superseded_by),
    )


def parent_card(value: TaskLink) -> ParentCardView:
    """Родитель в карточке ребёнка: как `link_other`, плюс цель не длиннее потолка."""
    goal, truncated = clip_parent_goal(value.other.goal)
    return ParentCardView(**link_other(value).model_dump(), goal=goal, goal_truncated=truncated)


# Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.
class TaskPackageView(BaseModel):
    """Task package, `state` first; `brief=true` leaves out all but the fields it names."""

    state: TaskStateView
    task: TaskView | TaskBriefCardView
    #: Родитель и дети — полями, а не видами в `links` (TRK-135): имя поля и есть ответ
    #: на «кто родитель», направление разбирать не нужно.
    parent: ParentCardView | LinkOtherView | None
    #: Поля ниже в кратком ответе отсутствуют (`brief=true`), поэтому в схеме не обязательны.
    children: list[LinkOtherView] = Field(default=None)  # type: ignore[assignment]
    links: list[LinkView] = Field(default=None)  # type: ignore[assignment]
    decisions: list[CitedDecisionView] = Field(
        default=None,  # type: ignore[assignment]
        description=(
            "Project decisions the task relies on, in the order of its `decisions` field. "
            "The project's other decisions in force are listed by `get_project`"
        ),
    )
    features: FeaturesView
    summary: EntryView | None = None
    questions: list[EntryView] = Field(default=None)  # type: ignore[assignment]
    remarks: list[EntryView] = Field(default=None)  # type: ignore[assignment]
    transitions: list[TaskStatusSchema]
    index: list[HeadingView] = Field(default=None)  # type: ignore[assignment]


def task_package(package: TaskPackage) -> TaskPackageView:
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.

    Совпадает с `GET /api/v1/tasks/{key}` поле в поле, и это проверяется тестом. Не
    ради красоты: агент и человек обязаны видеть одну и ту же задачу, иначе разбор
    «почему агент решил иначе, чем показывал интерфейс» упирается в два разных ответа.
    """
    key = package.task.key
    return TaskPackageView(
        state=task_state(package.state),
        task=task(package.task),
        parent=None if package.parent is None else parent_card(package.parent),
        children=[link_other(item) for item in package.children],
        links=[link(item) for item in package.links],
        decisions=[cited_decision(item) for item in package.decisions],
        features=features(package.features),
        summary=None if package.summary is None else entry(package.summary, task_key=key),
        questions=[entry(question, task_key=key) for question in package.questions],
        remarks=[entry(remark, task_key=key) for remark in package.remarks],
        transitions=list(package.transitions),
        index=[heading(item) for item in package.index],
    )


def brief_package(package: TaskPackage) -> CallToolResult:
    """Краткий ответ `brief=true`: шапка, родитель без цели, признаки, `state`, переходы.

    Поля, которых в кратком ответе нет, не присылаются вовсе, а не пустыми: ключ с `null`
    стоил бы токенов, ради которых режим и заведён. Ответ собирается вручную, потому что
    SDK сериализует модель с её умолчаниями; форму он по-прежнему сверяет со схемой.
    """
    item = package.task
    data = {
        "state": task_state(package.state),
        "task": TaskBriefCardView(
            key=item.key,
            title=item.title,
            status=item.status,
            assignee=item.assignee,
            priority=item.priority,
            direction=None if item.direction is None else item.direction.address,
            version=item.version,
            updated_at=item.updated_at,
        ),
        "parent": None if package.parent is None else link_other(package.parent),
        "features": features(package.features),
        "transitions": list(package.transitions),
    }
    structured = pydantic_core.to_jsonable_python(data)
    text = pydantic_core.to_json(data, indent=2).decode()
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structured_content=structured
    )


BriefArg = Annotated[
    bool,
    Field(description="`true`: `state`, a short header, `parent`, `features`, `transitions` only"),
]


def register(tools: Toolset) -> None:
    """Объявляет `get_task`."""
    runtime = tools.runtime

    @tools.tool(title="Get task", annotations=READ_ONLY)
    async def get_task(key: TaskKeyArg, brief: BriefArg = False) -> TaskPackageView:
        """Returns everything about one task in a single call: `state` first, card, parent
        and children, links from both sides, the project decisions it relies on, computed
        features, latest summary, open questions, unresolved remarks, case index and
        transition targets.

        `state` is computed on read: last transition with its reason, parts of the latest
        summary, entries after it, open questions and remarks, blockers, children by status
        and the decisions filed after the sections were last edited. `brief=true` returns
        `state`, a short `task` header, `parent`, `features` and `transitions`; the sections
        that set the work come without it.

        `parent` and `children` are fields of their own and are absent from `links`,
        which holds `blocks`, `blocked_by` and `relates`, each named by this task's
        role. `parent` carries the parent's `goal`, cut when long (`goal_truncated`); the full
        text, its summary and decisions are in the parent's own case.

        The summary covers the case up to its own `no`; entries with a greater `no` are
        returned by `read_entries` with `after_no`. The index carries titles only, and
        entry bodies come from `read_entries`.

        A remark in `remarks` changes nothing in the task: it does not block
        `in_progress`, does not change the status and does not unlock the sections. It
        stays in `remarks` and in `open_remarks` until `resolve` gives it an outcome.

        `transitions` lists the targets of the transition table from the current status,
        not moves checked in advance: sections, summary, verdicts, blockers, `blocking`
        questions and children are checked by the `transition` call itself. Whether
        `in_progress` is open shows in the `blocked` and `open_blocking_questions`
        features.
        """
        async with runtime.call() as (session, actor):
            package = await tasks_service.read_task_package(session, key, actor=actor)
            if brief:
                return brief_package(package)  # type: ignore[return-value]
            return task_package(package)
