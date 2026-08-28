"""Журнал изменений и outbox: запись, чтение, обработка воркером.

## Запись идёт в той же транзакции, что и изменение

Функции `record_*` вызываются из сценариев задач и ничего не фиксируют — границу
транзакции держит вход в приложение. В этом весь смысл outbox: событие появляется
тогда и только тогда, когда изменение зафиксировано. Откат транзакции уносит и
изменение, и запись журнала, и событие; рассылка при этом ещё не начиналась, потому
что её делает отдельный процесс.

Прямая рассылка из обработчика запроса — та самая ошибка, ради которой outbox и
существует: вебхук ушёл, уведомление доставлено, а транзакция откатилась.

## Полезная нагрузка самодостаточна

В событии лежит состояние объекта **после** изменения и список «было → стало».
Подписчику незачем идти в базу за контекстом, и дело не в экономии запросов: пока
событие лежало в очереди, задачу успели изменить ещё раз, и база отдала бы не то
состояние, о котором событие.

## Обработка

`process_next_event` берёт одно событие, раздаёт подписчикам и обновляет его состояние.
Одно событие за вызов, потому что воркер оборачивает каждый вызов в свою транзакцию:
падение на третьем событии не должно откатывать обработку первых двух.

## След автоматики приклеивается к событию, а не передаётся параметром

Правило автоматики меняет задачу теми же сценариями, что и обычный запрос, и каждый из
них публикует событие. Чтобы следующее правило могло понять, что изменение сделано
автоматикой, и на какой глубине цепочки оно находится, эта отметка обязана попасть в
полезную нагрузку — единственный канал между изменением и его последствием.

Передавать её параметром пришлось бы через каждый сценарий, который правилу разрешено
звать: задачи, комментарии, связи, чеклист, спринты. Пять сигнатур сегодня и все
будущие — ради значения, которое на всём протяжении вызова одно и то же. Поэтому здесь
стоит контекстная переменная, а движок автоматики оборачивает в неё выполнение правила
(`automation_cause`). Это ровно тот случай, для которого `contextvars` и существует:
значение принадлежит не вызову, а времени жизни задачи asyncio.

Явности от этого не теряется: отметка видна в самом событии, а не подразумевается.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.sentinels import UNSET, UnsetType, is_set
from app.db.models.actor import Actor
from app.db.models.board import Board, Sprint
from app.db.models.catalog import Status
from app.db.models.checklist import ChecklistItem
from app.db.models.comment import Comment
from app.db.models.event import ChangelogEntry, OutboxEvent
from app.db.models.issue import Issue
from app.db.models.link import IssueLink
from app.db.models.project import Portfolio, Project
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import ChangelogRepository, OutboxRepository
from app.domain.automation import AUTOMATION_PAYLOAD_KEY, AutomationCause
from app.domain.checklists import CHECKLIST_CHANGE_FIELD
from app.domain.comments import COMMENT_EXCERPT_LENGTH, COMMENTS_CHANGE_FIELD
from app.domain.events import (
    EventType,
    ObjectType,
    OutboxStatus,
    changed_fields,
    encode_changes,
    event_type_for,
)
from app.domain.issues import IssueChange
from app.domain.links import LINKS_CHANGE_FIELD, visible_type
from app.domain.projects import PlanningKind
from app.services.event_bus import (
    MAX_ERROR_LENGTH,
    DeliveryOutcome,
    EventEnvelope,
    SubscriberRegistry,
    deliver,
)
from app.services.event_bus import registry as default_registry
from app.services.permissions import ensure_allowed

#: Правило автоматики, от имени которого сейчас идут изменения. `None` — обычный
#: запрос человека или агента. Читается только при публикации события.
_automation_cause: ContextVar[AutomationCause | None] = ContextVar(
    "automation_cause",
    default=None,
)


@contextmanager
def automation_cause(cause: AutomationCause) -> Iterator[None]:
    """Помечает все события, опубликованные внутри блока, как сделанные правилом.

    Вложенность допустима и складывается правильно: движок передаёт уже увеличенную
    глубину, а прежнее значение восстанавливается токеном, а не присваиванием `None`.
    Обнуление сломало бы макрос, запущенный изнутри другого правила: цепочка после
    возврата считалась бы начатой заново.
    """
    token = _automation_cause.set(cause)
    try:
        yield
    finally:
        _automation_cause.reset(token)


def current_automation_cause() -> AutomationCause | None:
    """Правило, от имени которого сейчас идут изменения, если оно есть."""
    return _automation_cause.get()


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Сколько раз и с какой паузой повторять доставку.

    Пауза удваивается с каждой попыткой и упирается в потолок. Постоянная пауза здесь
    не годится: подписчик падает либо мгновенно (ошибка в коде — повторы бесполезны),
    либо из-за недоступного внешнего сервиса, которому нужно время. Растущая пауза
    обслуживает оба случая одним правилом.
    """

    max_attempts: int
    base_delay: timedelta
    max_delay: timedelta

    @classmethod
    def from_settings(cls) -> RetryPolicy:
        settings = get_settings()
        return cls(
            max_attempts=settings.outbox_max_attempts,
            base_delay=timedelta(seconds=settings.outbox_retry_delay),
            max_delay=timedelta(seconds=settings.outbox_max_retry_delay),
        )

    def delay_after(self, attempts: int) -> timedelta:
        """Пауза перед попыткой номер `attempts + 1`."""
        grown = self.base_delay * (2 ** max(attempts - 1, 0))
        return min(grown, self.max_delay)


@dataclass(frozen=True, slots=True)
class ProcessedEvent:
    """Итог обработки одного события: что раздавали, кому и чем кончилось."""

    envelope: EventEnvelope
    outcome: DeliveryOutcome
    status: OutboxStatus
    attempts: int


# --- Запись: задачи ---------------------------------------------------------------


async def record_issue_created(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
) -> ChangelogEntry:
    """Запись «задача создана» и событие `issue.created`.

    Список изменений пуст: у создания нет «было», а состояние новой задачи целиком
    уезжает в полезную нагрузку. Псевдоизменения «было пусто, стало значение» по
    каждому полю удвоили бы карточку задачи в её же истории и ничего не добавили.
    """
    entry = await _write_changelog(
        session,
        issue=issue,
        actor=initiator,
        event_type=EventType.ISSUE_CREATED,
        changes=(),
    )
    await _publish_issue_event(
        session,
        issue=issue,
        actor=initiator,
        event_type=EventType.ISSUE_CREATED,
        changes=(),
    )
    return entry


async def record_issue_changed(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    action: str,
    changes: tuple[IssueChange, ...],
) -> ChangelogEntry | None:
    """Запись об изменении задачи и событие соответствующего типа.

    Пустой список изменений — законный результат единой точки применения изменений
    (клиент прислал то, что уже стоит), и записи он не даёт: иначе журнал заполнился бы
    строками «сменил приоритет с normal на normal», а автоматика срабатывала бы на
    изменение, которого не было. Отсюда `None` в возвращаемом типе.

    Тип события выводится из действия и набора изменённых полей
    (`app/domain/events.py`), а не передаётся вызывающим: словарь действий и словарь
    событий должны оставаться одним словарём.
    """
    if not changes:
        return None

    event_type = event_type_for(action, changed_fields(changes))
    entry = await _write_changelog(
        session,
        issue=issue,
        actor=initiator,
        event_type=event_type,
        changes=changes,
    )
    await _publish_issue_event(
        session,
        issue=issue,
        actor=initiator,
        event_type=event_type,
        changes=changes,
    )
    return entry


async def record_issue_deleted(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
) -> OutboxEvent:
    """Событие `issue.deleted`. Записи журнала не даёт, и это не упущение.

    История удаляемой задачи уезжает вместе с ней (`ON DELETE CASCADE`), поэтому
    запись, сделанная перед удалением, была бы удалена в той же транзакции. Факт
    удаления живёт событием: у него ссылки на задачу нет, а полезная нагрузка содержит
    полный снимок — по нему видно, что именно исчезло.

    Зовётся **до** удаления: после него собрать снимок уже не из чего.
    """
    return await _publish_issue_event(
        session,
        issue=issue,
        actor=initiator,
        event_type=EventType.ISSUE_DELETED,
        changes=(),
    )


async def record_issues_moved(
    session: AsyncSession,
    *,
    initiator: Actor,
    source: Status,
    target: Status,
    resolution_after: str | None,
    queue: Queue | None,
    issues: list[tuple[uuid.UUID, str, str | None]],
) -> list[ChangelogEntry]:
    """Массовый перенос задач: запись журнала на каждую задачу, событие — одно на всех.

    Асимметрия намеренная, и вот её причина.

    Журнал ведётся по задаче, и дыра в нём недопустима: концепция проекта ставит
    историю изменений первой механикой, а задача, у которой статус поменялся и в
    истории об этом ничего нет, необъяснима для того, кто её потом читает.

    Событие — другое дело. Шина кормит автоматику, уведомления и вебхуки, и сотня
    одинаковых `issue.status_changed` там означала бы сотню уведомлений об
    административной операции и сотню срабатываний правил, каждое из которых породит
    новые события. Поэтому перенос даёт одно событие `status.issues_moved` со списком
    ключей: подписчик, которому нужны отдельные задачи, разберёт список сам, а
    подписчик, которому нужны настоящие изменения статуса, не захлебнётся.

    Оборотная сторона, о которой обязан знать автор правила автоматики: триггер на
    `issue.status_changed` массовый перенос **не поймает**. Это цена, выбранная
    сознательно, а не забытая ветка.
    """
    if not issues:
        return []

    status_change = IssueChange(field="status", before=source.ref, after=target.ref)
    entries: list[ChangelogEntry] = []
    for issue_id, _, resolution_before in issues:
        changes = [status_change]
        if resolution_before != resolution_after:
            changes.append(
                IssueChange(
                    field="resolution",
                    before=resolution_before,
                    after=resolution_after,
                )
            )
        entries.append(
            ChangelogEntry(
                issue_id=issue_id,
                actor_id=initiator.id,
                event_type=EventType.ISSUE_STATUS_CHANGED.value,
                changes=encode_changes(changes),
            )
        )
    await ChangelogRepository(session).add_all(entries)

    # Ключи перечислены целиком, а не срезаны до первых N: срезанный список неотличим
    # от полного, и подписчик молча пропустил бы часть задач. Размер нагрузки при этом
    # растёт вместе с переносом — это известное ограничение, а не недосмотр.
    await _publish(
        session,
        event_type=EventType.STATUS_ISSUES_MOVED,
        object_type=ObjectType.STATUS,
        object_id=source.id,
        object_key=source.ref,
        actor=initiator,
        payload={
            "status": {"from": source.ref, "to": target.ref},
            "queue": None if queue is None else queue.key,
            "count": len(issues),
            "issues": [key for _, key, _ in issues],
        },
    )
    return entries


# --- Запись: связи ----------------------------------------------------------------


async def record_link_created(
    session: AsyncSession,
    link: IssueLink,
    *,
    initiator: Actor,
) -> list[ChangelogEntry]:
    """Запись «связь заведена» в историю **обеих** задач и одно событие `link.created`.

    Асимметрия ровно обратная массовому переносу статусов: там сто записей журнала и
    одно событие, здесь две записи журнала и одно событие. Причина общая — журнал
    ведётся по задаче, а событие по факту.

    Две записи, потому что связь одинаково значима для обеих сторон, а история читается
    по одной задаче: без записи у второй стороны блокировка появлялась бы у неё
    ниоткуда. Формулировки при этом разные — каждая сторона видит связь своим именем
    (`depends_on` у одной, `blocks` у другой), и это то же самое вычисление, что в API.

    Событие одно, потому что факт один. Два события про одну связь заставили бы каждого
    подписчика их склеивать, а забывший склеить прислал бы два уведомления об одном.
    """
    return await _record_link_change(session, link, initiator=initiator, removed=False)


async def record_link_deleted(
    session: AsyncSession,
    link: IssueLink,
    *,
    initiator: Actor,
) -> list[ChangelogEntry]:
    """То же самое для удаления связи. Зовётся **до** удаления строки.

    После удаления собрать записи уже не из чего: обе стороны и автор читаются из самой
    связи, а `ON DELETE CASCADE` в задачах уносит её без всякого следа.
    """
    return await _record_link_change(session, link, initiator=initiator, removed=True)


# --- Запись: обсуждение и чеклист -------------------------------------------------


async def record_comment_created(
    session: AsyncSession,
    comment: Comment,
    *,
    issue: Issue,
    initiator: Actor,
) -> ChangelogEntry:
    """Запись «комментарий добавлен» в историю задачи и событие `comment.created`."""
    return await _record_comment_change(
        session,
        comment,
        issue=issue,
        initiator=initiator,
        action="comment.create",
        before=None,
        previous=None,
    )


async def record_comment_updated(
    session: AsyncSession,
    comment: Comment,
    *,
    issue: Issue,
    initiator: Actor,
    previous_body: str,
    previous_mentions: list[str],
) -> ChangelogEntry:
    """Запись о правке комментария и событие `comment.updated`.

    Прежний текст передаёт сценарий, а не читает эта функция: к моменту вызова
    комментарий уже изменён, и «было» из него не достать. Полный прежний текст уходит
    в событие — подписчик, ведущий свою копию ленты, обязан знать, что именно
    заменилось, — а в журнал попадает только отрывок.
    """
    return await _record_comment_change(
        session,
        comment,
        issue=issue,
        initiator=initiator,
        action="comment.update",
        before=_comment_value(comment, body=previous_body),
        previous={"body": previous_body, "mentions": list(previous_mentions)},
    )


async def record_comment_deleted(
    session: AsyncSession,
    comment: Comment,
    *,
    issue: Issue,
    initiator: Actor,
    previous_body: str,
    previous_mentions: list[str],
) -> ChangelogEntry:
    """Запись об удалении комментария и событие `comment.deleted`.

    Удаление мягкое, но в журнале «стало» пусто: текста в ленте больше нет, и это то
    самое изменение, о котором читатель истории спрашивает. Сам комментарий при этом
    остаётся плашкой — дыры в обсуждении не образуется.
    """
    return await _record_comment_change(
        session,
        comment,
        issue=issue,
        initiator=initiator,
        action="comment.delete",
        before=_comment_value(comment, body=previous_body),
        after=None,
        previous={"body": previous_body, "mentions": list(previous_mentions)},
    )


async def record_checklist_change(
    session: AsyncSession,
    item: ChecklistItem,
    *,
    issue: Issue,
    initiator: Actor,
    action: str,
    before: dict[str, Any] | None,
    removed: bool = False,
) -> ChangelogEntry:
    """Запись об изменении пункта чеклиста и событие соответствующего типа.

    Одна функция на все шесть действий с пунктом, а не шесть почти одинаковых: тип
    события выводится из действия таблицей `ACTION_EVENTS`, а форма записи у всех
    случаев общая — снимок пункта до и после. Отдельные обёртки лишь повторяли бы
    друг друга и однажды разошлись бы формой значения.

    Снимок «до» собирает сценарий **перед** изменением (`checklist_value`): после
    присваивания прежнее состояние взять уже неоткуда.
    """
    event_type = event_type_for(action)
    after = None if removed else checklist_value(item)
    entry = await _write_changelog(
        session,
        issue=issue,
        actor=initiator,
        event_type=event_type,
        changes=(IssueChange(field=CHECKLIST_CHANGE_FIELD, before=before, after=after),),
    )
    await _publish(
        session,
        event_type=event_type,
        object_type=ObjectType.CHECKLIST_ITEM,
        object_id=item.id,
        object_key=f"{issue.key}:{item.id}",
        actor=initiator,
        payload={
            "item": checklist_snapshot(item, issue=issue),
            # Состояние до изменения целиком: подписчик, которому нужен переход
            # «не выполнен → выполнен», иначе полез бы за ним в базу и прочитал бы
            # состояние на момент доставки, а не на момент события.
            "previous": before,
            "issue": issue_snapshot(issue),
        },
    )
    return entry


# --- Запись: проекты и портфели ---------------------------------------------------


async def record_planning_change(
    session: AsyncSession,
    entity: Project | Portfolio,
    *,
    initiator: Actor,
    action: str,
    changes: tuple[IssueChange, ...] = (),
) -> OutboxEvent:
    """Событие о проекте или портфеле. Записи в журнал изменений при этом **нет**.

    Это не упущение, а следствие устройства журнала: `changelog_entries.issue_id` —
    обязательная колонка, потому что история читается по задаче и адресуется её ключом.
    Проект задачей не является, и приписывать его правки какой-нибудь из его задач было
    бы враньём в чужой истории.

    Обратная сторона названа прямо, чтобы её не «чинили»: истории у проекта в v1 нет,
    и восстановить, кто и когда сдвинул срок, можно только по потоку событий. Заводить
    ради этого вторую таблицу истории — работа отдельной задачи, а не побочный эффект
    этой.

    Что при этом **попадает** в историю задачи: добавление её в проект и удаление из
    него. Это правка поля `project` самой задачи, она идёт через
    `apply_issue_changes` и даёт обычную запись `issue.updated`.
    """
    kind = PlanningKind.PORTFOLIO if isinstance(entity, Portfolio) else PlanningKind.PROJECT
    return await _publish(
        session,
        event_type=event_type_for(action),
        object_type=ObjectType.PORTFOLIO if kind is PlanningKind.PORTFOLIO else ObjectType.PROJECT,
        object_id=entity.id,
        object_key=entity.key,
        actor=initiator,
        payload={
            kind.value: planning_snapshot(entity),
            "changes": encode_changes(changes),
            "fields": list(changed_fields(changes)),
        },
    )


def planning_snapshot(entity: Project | Portfolio) -> dict[str, Any]:
    """Проект или портфель в JSON-виде для полезной нагрузки события.

    Прогресса здесь нет, и это осознанно. Прогресс — производная от задач, он меняется
    без всякого касания к проекту, и снимок с ним означал бы цифру, устаревшую к
    моменту доставки. Подписчик, которому нужен прогресс, спрашивает его у API в тот
    момент, когда собирается показать.

    Форма повторяет ответ API, но живёт здесь по общему правилу: `services` не имеет
    права зависеть от `api`, а событие обязано выглядеть одинаково и для подписчика
    внутри процесса, и для вебхука наружу.
    """
    parent = entity.parent if isinstance(entity, Portfolio) else entity.portfolio
    return {
        "id": str(entity.id),
        "key": entity.key,
        "name": entity.name,
        "description": entity.description,
        "status": entity.status.value,
        "lead": entity.lead.key,
        "members": [member.key for member in entity.members],
        "start_date": _day(entity.start_date),
        "end_date": _day(entity.end_date),
        "tags": list(entity.tags),
        "portfolio": None if parent is None else parent.key,
        "is_archived": entity.is_archived,
        "archived_at": _moment(entity.archived_at),
        "created_at": _moment(entity.created_at),
        "updated_at": _moment(entity.updated_at),
    }


# --- Запись: доски и спринты ------------------------------------------------------


async def record_board_change(
    session: AsyncSession,
    board: Board,
    *,
    initiator: Actor,
    action: str,
    changes: tuple[IssueChange, ...] = (),
) -> OutboxEvent:
    """Событие о доске. Записи в журнал изменений задачи при этом **нет**.

    По той же причине, что у проекта: `changelog_entries.issue_id` обязателен, история
    читается по задаче, и приписывать правку доски какой-нибудь из её задач было бы
    враньём в чужой истории. Правка колонок сюда же — она меняет настройки доски.

    Исключение — перемещение карточки между колонками: оно меняет **статус задачи**,
    идёт через `apply_issue_changes` и потому даёт обычную запись `issue.status_changed`
    в истории самой задачи. В событие доски оно не превращается вовсе.
    """
    return await _publish(
        session,
        event_type=event_type_for(action),
        object_type=ObjectType.BOARD,
        object_id=board.id,
        object_key=str(board.id),
        actor=initiator,
        payload={
            "board": board_snapshot(board),
            "changes": encode_changes(changes),
            "fields": list(changed_fields(changes)),
        },
    )


async def record_issue_ranked(
    session: AsyncSession,
    board: Board,
    issue: Issue,
    *,
    initiator: Actor,
    position: int,
) -> OutboxEvent:
    """Карточку переставили на доске.

    Объект события — доска, а не задача: ранг принадлежит доске, и подписчик,
    держащий открытым один экран, обязан отбирать эти события по её идентификатору.
    Строку задачи перестановка не меняет, поэтому ни версии, ни записи в истории у неё
    не появляется — это и есть разница между «переставить карточку» и «перетащить её в
    другую колонку», которая является переходом воркфлоу.

    Позиция в нагрузке — внутреннее число разреженной шкалы, и полагаться на конкретное
    значение нельзя: перенумерация доски меняет их все, сохраняя порядок. Подписчику
    она нужна ровно затем, чтобы понять, куда встала карточка относительно соседей,
    перечитав страницу.
    """
    return await _publish(
        session,
        event_type=event_type_for("board.rank"),
        object_type=ObjectType.BOARD,
        object_id=board.id,
        object_key=str(board.id),
        actor=initiator,
        payload={
            "board": board_snapshot(board),
            "issue": issue_snapshot(issue),
            "position": position,
        },
    )


async def record_sprint_change(
    session: AsyncSession,
    sprint: Sprint,
    *,
    initiator: Actor,
    action: str,
    changes: tuple[IssueChange, ...] = (),
    issues: Sequence[str] = (),
) -> OutboxEvent:
    """Событие о спринте.

    `issues` заполняется только у завершения: ключи задач, которые ушли из спринта, и
    то, куда они ушли, лежат в `changes`. Без списка подписчик знал бы, что спринт
    закрыт, но не знал бы, что именно переехало, — а перечитать это потом уже неоткуда:
    состав спринта нигде не хранится отдельно от самих задач.
    """
    return await _publish(
        session,
        event_type=event_type_for(action),
        object_type=ObjectType.SPRINT,
        object_id=sprint.id,
        object_key=str(sprint.id),
        actor=initiator,
        payload={
            "sprint": sprint_snapshot(sprint),
            "changes": encode_changes(changes),
            "fields": list(changed_fields(changes)),
            "issues": list(issues),
        },
    )


def board_snapshot(board: Board) -> dict[str, Any]:
    """Доска в JSON-виде для полезной нагрузки события.

    Колонки входят целиком: их число ограничено доменом, а подписчику, который держит
    открытый экран, без них нечего перерисовывать. Задач здесь нет и быть не может —
    доска собирает их фильтром, и снимок сотен карточек не пролез бы ни в одно событие.
    """
    return {
        "id": str(board.id),
        "name": board.name,
        "description": board.description,
        "saved_filter": str(board.saved_filter_id),
        "columns": [
            {
                "id": str(column.id),
                "name": column.name,
                "statuses": sorted(link.status.ref for link in column.status_links),
                "wip_limit": column.wip_limit,
            }
            for column in board.columns
        ],
        "created_at": _moment(board.created_at),
        "updated_at": _moment(board.updated_at),
    }


def sprint_snapshot(sprint: Sprint) -> dict[str, Any]:
    """Спринт в JSON-виде для полезной нагрузки события."""
    return {
        "id": str(sprint.id),
        "board": str(sprint.board_id),
        "name": sprint.name,
        "goal": sprint.goal,
        "start_date": _day(sprint.start_date),
        "end_date": _day(sprint.end_date),
        "state": sprint.state.value,
        "started_at": _moment(sprint.started_at),
        "completed_at": _moment(sprint.completed_at),
        "created_at": _moment(sprint.created_at),
        "updated_at": _moment(sprint.updated_at),
    }


# --- Чтение -----------------------------------------------------------------------


async def list_changelog(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[ChangelogEntry]:
    """История изменений задачи страницами, от старого к новому."""
    ensure_allowed(initiator, "issue.changelog", target=issue)
    return await ChangelogRepository(session).list_page(
        issue_id=issue.id,
        limit=limit,
        cursor=cursor,
    )


# --- Обработка --------------------------------------------------------------------


async def process_next_event(
    session: AsyncSession,
    *,
    registry: SubscriberRegistry | None = None,
    policy: RetryPolicy | None = None,
    now: datetime | None = None,
) -> ProcessedEvent | None:
    """Берёт одно необработанное событие и раздаёт его подписчикам.

    Возвращает `None`, когда брать нечего, — воркер по этому признаку уходит спать.

    Событие считается обработанным, только когда отработали **все** подписчики: строка
    помечается доставленной, а имена отработавших копятся в `delivered_to`. Повтор идёт
    только по оставшимся — подписчик, сделавший свою работу, не должен делать её второй
    раз из-за соседа, который упал.

    Транзакцию функция не фиксирует. Это и есть механизм переживания перезапуска:
    строка события заблокирована `FOR UPDATE` до конца транзакции, и убитый посреди
    работы процесс откатывает её целиком — событие снова становится необработанным.
    """
    moment = now or datetime.now(UTC)
    retry = policy or RetryPolicy.from_settings()
    subscribers = registry or default_registry

    event = await OutboxRepository(session).claim_next(now=moment)
    if event is None:
        return None

    envelope = _envelope(event)
    already_done = set(event.delivered_to)
    pending = [
        subscriber
        for subscriber in subscribers.matching(event.event_type)
        if subscriber.name not in already_done
    ]
    outcome = await deliver(session, envelope, pending)

    # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации внутри
    # значения, и UPDATE просто не уйдёт. Присваивается всегда новый список.
    event.delivered_to = [*event.delivered_to, *outcome.delivered]

    if outcome.failed:
        event.attempts += 1
        event.last_error = "; ".join(
            f"{failure.name}: {failure.error}" for failure in outcome.failures
        )[:MAX_ERROR_LENGTH]
        if event.attempts >= retry.max_attempts:
            # Попытки исчерпаны: событие помечено «не доставлено» и само больше не
            # повторится. Молча удалять или бесконечно повторять его нельзя — первое
            # прячет проблему, второе занимает воркер мёртвым подписчиком навсегда.
            event.status = OutboxStatus.FAILED
            event.processed_at = moment
        else:
            event.available_at = moment + retry.delay_after(event.attempts)
    else:
        event.status = OutboxStatus.DELIVERED
        event.processed_at = moment
        event.last_error = None

    await session.flush()
    return ProcessedEvent(
        envelope=envelope,
        outcome=outcome,
        status=event.status,
        attempts=event.attempts,
    )


# --- Внутреннее -------------------------------------------------------------------


def issue_snapshot(issue: Issue) -> dict[str, Any]:
    """Задача в JSON-виде для полезной нагрузки события.

    Повторяет форму ответа API (`app/api/schemas/issues.py`), но живёт здесь, а не там:
    `services` не имеет права зависеть от `api`, а событие обязано выглядеть одинаково
    и для подписчика внутри процесса, и для вебхука наружу.

    Время — строкой ISO 8601, ссылки справочников — строками, акторы — ключами: в JSONB
    объекты `datetime` не кладутся, а ORM-объект не переживает транзакцию, в которой
    событие родилось.
    """
    return {
        "id": str(issue.id),
        "key": issue.key,
        "queue": issue.queue.key,
        "issue_type": issue.issue_type.ref,
        "status": issue.status.ref,
        "resolution": None if issue.resolution is None else issue.resolution.ref,
        "priority": issue.priority.value,
        "summary": issue.summary,
        "description": issue.description,
        "author": issue.author.key,
        "assignee": None if issue.assignee is None else issue.assignee.key,
        "followers": [follower.key for follower in issue.followers],
        "deadline": _moment(issue.deadline),
        "tags": list(issue.tags),
        # Проект — ключом, как очередь и акторы: подписчику нужен адрес, а не строка
        # таблицы, которая к моменту доставки могла измениться.
        "project": None if issue.project is None else issue.project.key,
        # Спринт — идентификатором строкой: ключа у него нет, адресуют его именно так,
        # и название, положенное сюда, стало бы ссылкой, которая однажды укажет в никуда.
        "sprint": None if issue.sprint is None else str(issue.sprint_id),
        "values": dict(issue.values),
        "version": issue.version,
        "created_at": _moment(issue.created_at),
        "updated_at": _moment(issue.updated_at),
    }


def comment_snapshot(comment: Comment, *, issue: Issue) -> dict[str, Any]:
    """Комментарий в JSON-виде для полезной нагрузки события.

    Повторяет форму ответа API, но живёт здесь по общему правилу: `services` не имеет
    права зависеть от `api`, а событие обязано выглядеть одинаково для подписчика
    внутри процесса и для вебхука наружу.

    У удалённого комментария `body` пуст, а не отсутствует: строка остаётся плашкой в
    ленте, и подписчик должен видеть именно это состояние.
    """
    return {
        "id": str(comment.id),
        "issue": issue.key,
        "author": comment.author.key,
        "body": comment.body,
        "mentions": list(comment.mentions),
        "is_deleted": comment.is_deleted,
        "created_at": _moment(comment.created_at),
        "edited_at": _moment(comment.edited_at),
        "deleted_at": _moment(comment.deleted_at),
    }


def checklist_snapshot(item: ChecklistItem, *, issue: Issue) -> dict[str, Any]:
    """Пункт чеклиста в JSON-виде для полезной нагрузки события."""
    return {
        "id": str(item.id),
        "issue": issue.key,
        "text": item.text,
        "is_done": item.is_done,
        "checked_by": None if item.checked_by is None else item.checked_by.key,
        "checked_at": _moment(item.checked_at),
        "assignee": None if item.assignee is None else item.assignee.key,
        "deadline": _moment(item.deadline),
        "position": item.position,
    }


def checklist_value(item: ChecklistItem) -> dict[str, Any]:
    """Компактный снимок пункта для журнала изменений задачи.

    Журналу достаточно того, по чему читатель истории узнаёт изменение: что за пункт,
    что в нём написано, отмечен ли он и где стоит. Исполнитель и дедлайн пункта
    остаются в событии — в истории задачи они превратили бы одну строку про галочку в
    карточку подзадачи.
    """
    return {
        "item": str(item.id),
        "text": item.text,
        "done": item.is_done,
        "position": item.position,
    }


def _comment_value(comment: Comment, *, body: str) -> dict[str, Any]:
    """Компактный снимок комментария для журнала изменений задачи.

    В журнал идёт отрывок, а не весь текст: история задачи читается страницами, и
    несколько правок комментария на 64 килобайта сделали бы её неподъёмной. Полный
    текст при этом никуда не пропадает — он лежит в самой ленте (удаление мягкое) и
    целиком уходит в событие.
    """
    excerpt = body[:COMMENT_EXCERPT_LENGTH]
    if len(body) > COMMENT_EXCERPT_LENGTH:
        excerpt = f"{excerpt}…"
    return {"comment": str(comment.id), "excerpt": excerpt}


async def _record_comment_change(
    session: AsyncSession,
    comment: Comment,
    *,
    issue: Issue,
    initiator: Actor,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | UnsetType | None = UNSET,
    previous: dict[str, Any] | None,
) -> ChangelogEntry:
    """Общее тело записи для добавления, правки и удаления комментария.

    Различие ровно в двух вещах: снимок «до» и снимок «после». `after` по умолчанию
    считается из текущего состояния комментария — и только удаление передаёт `None`
    явно, потому что строка после него остаётся, а текста в ленте уже нет.
    """
    event_type = event_type_for(action)
    resolved_after = _comment_value(comment, body=comment.body) if not is_set(after) else after
    entry = await _write_changelog(
        session,
        issue=issue,
        actor=initiator,
        event_type=event_type,
        changes=(IssueChange(field=COMMENTS_CHANGE_FIELD, before=before, after=resolved_after),),
    )
    await _publish(
        session,
        event_type=event_type,
        object_type=ObjectType.COMMENT,
        object_id=comment.id,
        object_key=f"{issue.key}:{comment.id}",
        actor=initiator,
        payload={
            "comment": comment_snapshot(comment, issue=issue),
            # Прежний текст и прежний состав упоминаний. Нужны движку уведомлений:
            # упомянутый в старой редакции и упомянутый в новой — разные адресаты, и
            # разницу считает подписчик, а не мы за него.
            "previous": previous,
            "issue": issue_snapshot(issue),
        },
    )
    return entry


async def _write_changelog(
    session: AsyncSession,
    *,
    issue: Issue,
    actor: Actor,
    event_type: EventType,
    changes: tuple[IssueChange, ...],
) -> ChangelogEntry:
    entry = ChangelogEntry(
        issue_id=issue.id,
        actor_id=actor.id,
        event_type=event_type.value,
        changes=encode_changes(changes),
    )
    return await ChangelogRepository(session).add(entry)


async def _publish_issue_event(
    session: AsyncSession,
    *,
    issue: Issue,
    actor: Actor,
    event_type: EventType,
    changes: tuple[IssueChange, ...],
) -> OutboxEvent:
    return await _publish(
        session,
        event_type=event_type,
        object_type=ObjectType.ISSUE,
        object_id=issue.id,
        object_key=issue.key,
        actor=actor,
        payload={
            "issue": issue_snapshot(issue),
            "changes": encode_changes(changes),
            # Имена изменённых полей отдельным списком: подписчик почти всегда сначала
            # спрашивает «моё поле трогали?» и только потом лезет за значениями.
            "fields": list(changed_fields(changes)),
        },
    )


async def _record_link_change(
    session: AsyncSession,
    link: IssueLink,
    *,
    initiator: Actor,
    removed: bool,
) -> list[ChangelogEntry]:
    """Общее тело записи для заведения и удаления связи: различие ровно в направлении."""
    action = "link.delete" if removed else "link.create"
    event_type = event_type_for(action)

    entries: list[ChangelogEntry] = []
    for issue, other, from_source in (
        (link.source, link.target, True),
        (link.target, link.source, False),
    ):
        # Имя связи для каждой стороны своё: у одной `depends_on`, у другой `blocks`.
        # Считается тем же доменным правилом, что и в ответе API, — иначе история и
        # карточка задачи назвали бы одну связь по-разному.
        value = {
            "type": visible_type(link.link_type, from_source=from_source).value,
            "issue": other.key,
        }
        entries.append(
            ChangelogEntry(
                issue_id=issue.id,
                actor_id=initiator.id,
                event_type=event_type.value,
                changes=encode_changes(
                    (
                        IssueChange(
                            field=LINKS_CHANGE_FIELD,
                            before=value if removed else None,
                            after=None if removed else value,
                        ),
                    )
                ),
            )
        )
    await ChangelogRepository(session).add_all(entries)

    await _publish(
        session,
        event_type=event_type,
        object_type=ObjectType.LINK,
        object_id=link.id,
        object_key=_link_key(link),
        actor=initiator,
        payload={
            "link": {
                "id": str(link.id),
                "type": link.link_type.value,
                "source": link.source.key,
                "target": link.target.key,
                "author": link.author.key,
            },
            # Снимки обеих задач целиком — по общему правилу полезной нагрузки: пока
            # событие лежит в очереди, задачи успевают измениться, и поход подписчика
            # в базу вернул бы не то состояние, о котором событие. У связи «объект
            # события» один, а задач две, поэтому и снимка два.
            "issues": {
                "source": issue_snapshot(link.source),
                "target": issue_snapshot(link.target),
            },
        },
    )
    return entries


def _link_key(link: IssueLink) -> str:
    """Читаемый ключ связи для события: обе стороны и тип в каноническом направлении."""
    return f"{link.source.key}:{link.link_type.value}:{link.target.key}"


async def _publish(
    session: AsyncSession,
    *,
    event_type: EventType,
    object_type: ObjectType,
    object_id: uuid.UUID,
    object_key: str,
    actor: Actor,
    payload: dict[str, Any],
) -> OutboxEvent:
    cause = _automation_cause.get()
    if cause is not None:
        # Ключ добавляется только когда изменение сделало правило: его отсутствие —
        # это утверждение «сделал человек или агент», а не «неизвестно кто». Пустой
        # словарь в каждом событии стёр бы разницу между этими двумя состояниями.
        payload = {**payload, AUTOMATION_PAYLOAD_KEY: cause.to_payload()}
    event = OutboxEvent(
        event_type=event_type.value,
        object_type=object_type.value,
        object_id=object_id,
        object_key=object_key,
        actor_id=actor.id,
        actor_key=actor.key,
        payload=payload,
    )
    return await OutboxRepository(session).add(event)


def _envelope(event: OutboxEvent) -> EventEnvelope:
    """Строка outbox — в контракт подписчика.

    Полезная нагрузка копируется поверхностно: подписчик, дописавший что-то в словарь,
    не должен менять то, что лежит в базе.
    """
    return EventEnvelope(
        id=event.id,
        event_type=event.event_type,
        object_type=event.object_type,
        object_id=event.object_id,
        object_key=event.object_key,
        actor_key=event.actor_key,
        payload=dict(event.payload),
        created_at=event.created_at,
    )


def _moment(value: datetime | None) -> str | None:
    """Время в событии — строка ISO 8601 в UTC: тот же формат, что в API и в журнале."""
    return None if value is None else value.astimezone(UTC).isoformat()


def _day(value: date | None) -> str | None:
    """Календарная дата в событии — строка `YYYY-MM-DD`, без домысленного времени.

    Приводить её к моменту нельзя: полночь какого часового пояса имелась бы в виду,
    из значения не следует, а подстановка UTC сдвинула бы дату у половины читателей.
    """
    return None if value is None else value.isoformat()
