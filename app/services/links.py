"""Сценарии по связям: поставить, снять, прочитать, посчитать `blocked`.

## Никакой автоматики

Связь ничего не двигает. Она запрещает взять задачу в работу поверх открытого блокера и
закрыть родителя с незакрытыми детьми — и на этом всё: статусы по связям не
распространяются, дети сами не отменяются, блокер сам не открывает то, что блокировал
(`CONCEPT.md`, 3.5). Проверки живут не здесь, а в списке проверок перехода
(`app/domain/tasks.py`); отсюда в них приезжают только факты.

## Направление зависимостей

Модуль **не** импортирует `app/services/tasks.py`: задачи обеих сторон приходят
объектами от вызывающего, который их и так прочитал. Обратная зависимость есть —
пакет преемника берёт отсюда связи и признак `blocked`, — и импорт в обе стороны сделал
бы её кольцевой.

## Две записи в дело на одну связь

Связь — событие обеих задач, поэтому запись подшивается в оба дела. Порядок подшивок
задаётся ключом задачи, а не порядком аргументов: `allocate_no` держит строку задачи до
конца транзакции, и два одновременных запроса, ставящих связь между теми же задачами с
разных сторон, взаимно заблокировали бы друг друга (`docs/notes/links.md`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.author import created_by_columns
from app.db.models.link import Link
from app.db.models.task import Task
from app.db.repositories import LinkRepository
from app.domain.authors import Author
from app.domain.errors import (
    LinkCycleError,
    LinkExistsError,
    LinkNotFoundError,
    TaskClosedError,
)
from app.domain.links import (
    LinkKind,
    canonical_form,
    ensure_not_self,
    is_acyclic,
    parse_link_kind,
    visible_kind,
)
from app.domain.tasks import is_closed
from app.domain.tokens import TokenScope
from app.services import case as case_service
from app.services.auth import Actor
from app.services.permissions import ensure_scope


@dataclass(frozen=True, slots=True)
class TaskLink:
    """Связь со стороны одной задачи: под своим именем и с задачей на другом конце.

    Не строка таблицы: у строки нет «своей» стороны, а у карточки есть. `kind` здесь
    уже посчитан для той задачи, чью карточку собирают, — у `A` это `blocks`, у `B` по
    той же строке `blocked_by`.
    """

    kind: LinkKind
    other: Task
    author: Author
    created_at: datetime


# --- Чтение -----------------------------------------------------------------------------


async def list_links(session: AsyncSession, task: Task, *, actor: Actor) -> list[TaskLink]:
    """Все связи задачи с обеих сторон, каждая — под именем со стороны этой задачи."""
    ensure_scope(actor, TokenScope.TASK, action="link.read")
    links = await LinkRepository(session).list_for_task(task.id)
    return [_seen_from(link, task) for link in links]


def blocked(links: Sequence[TaskLink]) -> bool:
    """Есть ли у задачи открытый блокер — признак `blocked` (`CONCEPT.md`, 4.3).

    Чистая функция от уже прочитанных связей, а не запрос: карточка читает их целиком,
    и второй поход в базу за тем же самым отличался бы от первого только моментом
    времени. Открытый блокер — связь `blocked_by` на задачу не в `done` и не в
    `cancelled`; закрытый блокер связь не снимает и признак не поднимает.
    """
    return any(
        link.kind is LinkKind.BLOCKED_BY and not is_closed(link.other.status) for link in links
    )


async def open_blockers(session: AsyncSession, task: Task) -> list[str]:
    """Ключи незакрытых блокеров — факт для проверки перехода в `in_progress`.

    Прав не проверяет: это не точка входа интерфейса, а продолжение сценария перехода,
    который права уже проверил, — как и `verdict_gaps` в деле.
    """
    return await LinkRepository(session).open_blocker_keys(task.id)


async def unclosed_children(session: AsyncSession, task: Task) -> list[str]:
    """Ключи детей не в `done` и не в `cancelled` — факт для перехода в `done`."""
    return await LinkRepository(session).unclosed_child_keys(task.id)


# --- Изменение --------------------------------------------------------------------------


async def add_link(
    session: AsyncSession,
    task: Task,
    other: Task,
    *,
    actor: Actor,
    kind: LinkKind | str,
) -> TaskLink:
    """Ставит связь `task <kind> other` и подшивает `link_added` в оба дела.

    Порядок проверок — от дешёвых к дорогим и от формы к состоянию: вид связи, связь с
    самой собой, закрытые задачи, дубликат, кольцо. Кольцо последним не случайно: это
    единственная проверка с обходом графа, и платить за неё на заведомо неверном
    запросе незачем.
    """
    ensure_scope(actor, TokenScope.TASK, action="link.add")
    requested = parse_link_kind(kind)
    ensure_not_self(task.key, other.key)
    _ensure_open(task, other, kind=requested)

    source, target, stored_kind = _canonical_pair(task, other, requested)
    repository = LinkRepository(session)
    existing = await repository.find(source_id=source.id, target_id=target.id, kind=stored_kind)
    if existing is not None:
        raise LinkExistsError(details=_sides(task, other, requested))
    if is_acyclic(stored_kind) and await repository.reaches(
        kind=stored_kind, from_id=target.id, to_id=source.id
    ):
        # Ребро идёт `source → target`, поэтому кольцо замкнётся ровно тогда, когда
        # источник уже достижим из цели по рёбрам **этого** вида. Виды не смешиваются:
        # родитель, заблокированный своими детьми, — законное «жду декомпозицию».
        raise LinkCycleError(details=_sides(task, other, requested) | {"stored": stored_kind.value})

    link = await repository.add(
        Link(
            source=source,
            target=target,
            kind=stored_kind,
            **created_by_columns(actor.author),
        )
    )
    await _record_on_both_sides(session, link, actor=actor, added=True)
    return _seen_from(link, task)


async def remove_link(
    session: AsyncSession,
    task: Task,
    other: Task,
    *,
    actor: Actor,
    kind: LinkKind | str,
) -> None:
    """Снимает связь и подшивает `link_removed` в оба дела.

    Снять можно с любой стороны и любым её именем: `A blocks B` удаляется и запросом
    «снять с A связь `blocks` с B», и «снять с B связь `blocked_by` с A» — это одна
    строка, а не две.
    """
    ensure_scope(actor, TokenScope.TASK, action="link.remove")
    requested = parse_link_kind(kind)
    ensure_not_self(task.key, other.key)
    _ensure_open(task, other, kind=requested)

    source, target, stored_kind = _canonical_pair(task, other, requested)
    repository = LinkRepository(session)
    link = await repository.find(source_id=source.id, target_id=target.id, kind=stored_kind)
    if link is None:
        raise LinkNotFoundError(details=_sides(task, other, requested))
    # Записи — до удаления: после него у строки не осталось бы сторон, а имена связи
    # для обоих дел считаются именно из неё.
    await _record_on_both_sides(session, link, actor=actor, added=False)
    await repository.delete(link)


# --- Внутреннее -------------------------------------------------------------------------


def _seen_from(link: Link, task: Task) -> TaskLink:
    """Строка связи — в том виде, в каком её показывают в карточке этой задачи."""
    kind, other = link.seen_from(task.id)
    return TaskLink(kind=kind, other=other, author=link.created_by, created_at=link.created_at)


def _canonical_pair(task: Task, other: Task, kind: LinkKind) -> tuple[Task, Task, LinkKind]:
    """Кто ложится в `source`, кто в `target` и каким видом — решение домена."""
    canonical = canonical_form(kind, source_key=task.key, target_key=other.key)
    source, target = (other, task) if canonical.swapped else (task, other)
    return source, target, canonical.kind


def _ensure_open(task: Task, other: Task, *, kind: LinkKind) -> None:
    """Связи закрытой задачи не меняются — ни с её стороны, ни с чужой.

    Проверяются обе стороны: связь принадлежит обеим, и поставить её закрытой задаче
    «снаружи» значило бы обойти правило с той стороны, где его не проверяют. Отказ
    называет ту задачу, которая закрыта, — иначе агент чинил бы не тот ключ.
    """
    for side, opposite in ((task, other), (other, task)):
        if is_closed(side.status):
            raise TaskClosedError(
                details={
                    "key": side.key,
                    "status": side.status.value,
                    "kind": kind.value,
                    "other": opposite.key,
                },
            )


def _sides(task: Task, other: Task, kind: LinkKind) -> dict[str, Any]:
    """Подробности отказа: связь так, как её попросили, — вид со стороны своей задачи."""
    return {"key": task.key, "kind": kind.value, "other": other.key}


async def _record_on_both_sides(
    session: AsyncSession,
    link: Link,
    *,
    actor: Actor,
    added: bool,
) -> None:
    """Подшивает запись о связи в дела обеих задач, в порядке их ключей.

    Порядок по ключу — защита от взаимной блокировки: `allocate_no` берёт `SELECT ...
    FOR UPDATE` на строку задачи и держит её до конца транзакции. Два запроса, ставящих
    связь между теми же задачами с разных сторон, пошли бы по строкам во встречном
    порядке и остановились бы друг о друга. Один и тот же порядок у всех запросов это
    исключает.
    """
    sides = (
        (link.source, visible_kind(link.kind, from_source=True), link.target),
        (link.target, visible_kind(link.kind, from_source=False), link.source),
    )
    for side, kind, opposite in sorted(sides, key=lambda side: side[0].key):
        await case_service.record_link_change(
            session,
            side,
            actor=actor,
            added=added,
            kind=kind,
            other_key=opposite.key,
        )
