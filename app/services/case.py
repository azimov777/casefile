"""Дело: служебные записи и чтение записей.

Служебная запись подшивается **в той же транзакции**, что и изменение, и только отсюда:
тип записи выводится из сценария (`record_status_changed` пишет `status_changed`), а не
передаётся вызывающим кодом. Два независимых словаря имён разъехались бы, и новое
действие молча осталось бы без записи.

Автор служебной записи — автор действия из аутентификации (`Actor.author`), а не сам
трекер: преемнику важно, **кто** перевёл задачу и **кто** поправил раздел. Род `tracker`
остаётся тому, что трекер делает без запроса — первичной инициализации.

Записи агента (`summary`, `decision`, `question`, ...) приезжают сюда задачей 23.
Методов правки и удаления здесь нет и не будет.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.task import Task
from app.db.pagination import Page
from app.db.repositories import EntryRepository
from app.domain.case import EntryHeading, EntryType
from app.domain.tasks import TaskField, TaskStatus
from app.domain.tokens import TokenScope
from app.services.auth import Actor
from app.services.permissions import ensure_scope

# --- Чтение ---------------------------------------------------------------------------


async def list_entries(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Entry]:
    """Записи задачи страницами в порядке `no`, с телами и нагрузкой."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).list_page(task.id, limit=limit, cursor=cursor)


async def case_index(session: AsyncSession, task: Task, *, actor: Actor) -> list[EntryHeading]:
    """Опись дела: заголовки всех записей без тел. Часть пакета преемника."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).headings(task.id)


# --- Служебные записи -----------------------------------------------------------------
#
# Прав здесь не проверяют: это не точки входа, а продолжение сценария, который права уже
# проверил. Заголовки — на английском: служебный слой, а не пользовательские данные.


async def record_created(session: AsyncSession, task: Task, *, actor: Actor) -> Entry:
    """Первая страница дела: задача заведена. Нагрузки нет — карточка и есть содержание."""
    return await _append(session, task, actor=actor, type=EntryType.CREATED, title="Task created")


async def record_status_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    from_status: TaskStatus,
    to_status: TaskStatus,
    reason: str | None,
) -> Entry:
    """Переход статуса с причиной, если она была: по ней преемник понимает откат."""
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.STATUS_CHANGED,
        title=f"Status changed: {from_status.value} -> {to_status.value}",
        payload={"from": from_status.value, "to": to_status.value, "reason": reason},
    )


async def record_section_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    field: TaskField,
    before: Any,
    after: Any,
) -> Entry:
    """Правка названия, описания или раздела в `backlog`: «было / стало» целиком.

    Целиком, а не разницей: преемник читает запись, а не собирает текст из патчей, и
    тела разделов ограничены потолком, при котором копия не страшна.
    """
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.SECTION_CHANGED,
        title=f"Section changed: {field.value}",
        payload={"field": field.value, "before": before, "after": after},
    )


async def record_assignee_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    before: str | None,
    after: str | None,
) -> Entry:
    """Смена исполнителя — единственная правка обвязки, которая подшивается в дело."""
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.ASSIGNEE_CHANGED,
        title=f"Assignee changed: {before or 'nobody'} -> {after or 'nobody'}",
        payload={"before": before, "after": after},
    )


async def _append(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    type: EntryType,
    title: str,
    payload: dict[str, Any] | None = None,
    body: str = "",
    refs: Sequence[str] = (),
) -> Entry:
    """Подшивает запись: номер в задаче выдаётся под блокировкой строки задачи.

    Автор раскладывается по колонкам общей функцией `created_by_columns` и берётся
    только из структуры автора действия — второй раскладки в проекте нет.
    """
    repository = EntryRepository(session)
    no = await repository.allocate_no(task.id)
    entry = Entry(
        task_id=task.id,
        no=no,
        type=type,
        title=title,
        body=body,
        payload=dict(payload or {}),
        refs=list(refs),
        **created_by_columns(actor.author),
    )
    return await repository.add(entry)
