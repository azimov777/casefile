"""Инструмент `get_task`: пакет преемника — всё о задаче одним вызовом.

Пакет совпадает с `GET /api/v1/tasks/{key}` поле в поле; связи здесь — со стороны этой
задачи, опись дела — строками из `app/mcp/tools/case/views.py`.
"""

from datetime import datetime

from pydantic import BaseModel

from app.mcp.arguments import TaskKeyArg
from app.mcp.enums import LinkKindSchema, TaskStatusSchema
from app.mcp.tools.tasks.views import FeaturesView, TaskView, features, task
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import AuthorView, EntryView, HeadingView, author, entry, heading
from app.services import tasks as tasks_service
from app.services.links import TaskLink
from app.services.tasks import TaskPackage


class LinkOtherView(BaseModel):
    """Task on the other side of a link."""

    key: str
    title: str
    status: TaskStatusSchema


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


# Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.
class TaskPackageView(BaseModel):
    """Everything about one task: card, parent and children, links, features, latest
    summary, open questions, unresolved remarks, transition targets and case index.
    """

    task: TaskView
    #: Родитель и дети — полями, а не видами в `links` (TRK-135): имя поля и есть ответ
    #: на «кто родитель», направление разбирать не нужно.
    parent: LinkOtherView | None
    children: list[LinkOtherView]
    links: list[LinkView]
    features: FeaturesView
    summary: EntryView | None
    questions: list[EntryView]
    remarks: list[EntryView]
    transitions: list[TaskStatusSchema]
    index: list[HeadingView]


def task_package(package: TaskPackage) -> TaskPackageView:
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.

    Совпадает с `GET /api/v1/tasks/{key}` поле в поле, и это проверяется тестом. Не
    ради красоты: агент и человек обязаны видеть одну и ту же задачу, иначе разбор
    «почему агент решил иначе, чем показывал интерфейс» упирается в два разных ответа.
    """
    key = package.task.key
    return TaskPackageView(
        task=task(package.task),
        parent=None if package.parent is None else link_other(package.parent),
        children=[link_other(item) for item in package.children],
        links=[link(item) for item in package.links],
        features=features(package.features),
        summary=None if package.summary is None else entry(package.summary, task_key=key),
        questions=[entry(question, task_key=key) for question in package.questions],
        remarks=[entry(remark, task_key=key) for remark in package.remarks],
        transitions=list(package.transitions),
        index=[heading(item) for item in package.index],
    )


def register(tools: Toolset) -> None:
    """Объявляет `get_task` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=READ_ONLY)
    async def get_task(key: TaskKeyArg) -> TaskPackageView:
        """Returns everything about one task in a single call: card, parent and children,
        links from both sides, computed features, latest summary, open questions,
        unresolved remarks, case index and transition targets.

        `parent` and `children` are fields of their own and are absent from `links`,
        which holds `blocks`, `blocked_by` and `relates`, each named by this task's
        role. The parent's summary and decisions are in the parent's own case.

        The summary covers the case up to its own `no`; entries with a greater `no` are
        returned by `read_entries` with `after_no`. The index carries titles only, and
        entry bodies come from `read_entries`.

        A remark in `remarks` changes nothing in the task: it does not block
        `in_progress`, does not change the status and does not unlock the sections. It
        stays in `remarks` and in `open_remarks` until `resolve` gives it an outcome.

        `transitions` lists the targets of the transition table from the current status,
        not moves checked in advance: sections, summary, verdicts, blockers and children
        are checked by the `transition` call itself. Whether `in_progress` is open shows
        in the `blocked` feature.
        """
        async with runtime.call() as (session, actor):
            return task_package(await tasks_service.read_task_package(session, key, actor=actor))
