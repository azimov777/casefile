"""Сценарии по задачам: создать, прочитать, частично обновить, перевести статус.

## Единая точка мутаций

Всё, что меняет задачу, проходит через `apply_task_changes`. Она принимает «что
меняем» (`TaskChanges` и, если это переход, `Transition`), «кто меняет» (`Actor`) и
возвращает список **фактических** изменений — поле, было, стало. К этой точке
подключены проверка прав, оптимистичная блокировка, правила «что можно править в этом
статусе», проверки перехода и служебные записи дела. Мутация, сделанная мимо неё, не
попадёт в дело — и обнаружится это как пропавшая страница, далеко от места ошибки.

«Фактических» — не формальность. Поле, переданное со значением, равным текущему,
записи не даёт и версию не поднимает: иначе дело заполнилось бы страницами «раздел
изменён с A на A».

## Что не передано и что передано как null

Признак «не передано» — общий на проект (`app/core/sentinels.py`). У задачи это не
украшение: исполнитель очищается именно передачей `null`, и склеить «очистить» с «не
трогать» значило бы либо не дать снять исполнителя, либо затирать его при каждом
частичном обновлении.

## Оптимистичная блокировка

У задачи есть `version`. Клиент присылает ту, которую видел; расхождение — `409
version_conflict`. Проверка двойная: сравнение в Python до записи даёт понятные
подробности, а `version_id_col` у модели ловит гонку, которая случилась между чтением
и `UPDATE`. Отсутствие версии в запросе — не согласие на перезапись, а режим для
вызовов, где гонки нет: инструмент MCP, работающий с только что прочитанной задачей.

## Версии мало: факты перехода лежат вне задачи

Блокеры и дети — чужие строки, и их появление `version` задачи не двигает. Поэтому
мутирующий сценарий первым делом занимает очередь изменений (`app/db/locks.py`) и
перечитывает под ней задачу: пока он держит очередь, соседняя транзакция не поставит
связь и не родит ребёнка между чтением фактов и фиксацией.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.sentinels import UNSET, is_set
from app.db.locks import lock_changes
from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.repositories import TaskRepository
from app.domain.case import EntryHeading
from app.domain.errors import (
    TaskClosedError,
    TaskFieldLockedError,
    TaskNotFoundError,
    TaskVersionConflictError,
)
from app.domain.tasks import (
    BACKLOG_ONLY_FIELDS,
    DEFAULT_PRIORITY,
    INITIAL_STATUS,
    CheckGap,
    TaskFeatures,
    TaskField,
    TaskPriority,
    TaskStatus,
    TransitionFacts,
    allowed_transitions,
    editable_fields,
    ensure_transition_allowed,
    format_task_key,
    is_closed,
    normalize_fields,
    normalize_reason,
    normalize_task_key,
    parse_status,
    section_values,
)
from app.domain.tokens import TokenScope
from app.services import case as case_service
from app.services import links as links_service
from app.services import queues as queues_service
from app.services.auth import Actor
from app.services.permissions import ensure_scope


@dataclass(frozen=True, slots=True)
class TaskChanges:
    """Что меняем в задаче. Не переданное поле остаётся `UNSET` и не трогается.

    `assignee` объявлен как `str | None`: `null` осмыслен и снимает исполнителя.
    У остальных полей `null` смысла не имеет, и передавать его нельзя.

    Статуса здесь нет: он меняется только переходом (`Transition`), у которого свои
    проверки и своя запись в деле.
    """

    title: str = UNSET
    description: str = UNSET
    goal: str = UNSET
    context: str = UNSET
    constraints: str = UNSET
    output: str = UNSET
    checks: Sequence[str] = UNSET
    assignee: str | None = UNSET
    tags: Sequence[str] = UNSET
    priority: TaskPriority | str = UNSET

    def given(self) -> dict[TaskField, Any]:
        """Только переданные поля, по именам домена."""
        return {
            TaskField(item.name): getattr(self, item.name)
            for item in fields(self)
            if is_set(getattr(self, item.name))
        }


@dataclass(frozen=True, slots=True)
class Transition:
    """Куда перевести задачу и почему. `to` — строка из MCP или член перечисления из REST."""

    to: TaskStatus | str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TaskChange:
    """Одно фактическое изменение: какое поле, что было, что стало — уже в JSON-виде."""

    field: str
    before: Any
    after: Any


@dataclass(frozen=True, slots=True)
class TaskMutation:
    """Результат применения изменений: сама задача и то, что реально изменилось.

    Пустой список — законный результат: клиент прислал то, что уже стоит. Версия при
    этом не растёт, и повторный запрос с той же версией не упрётся в конфликт.
    """

    task: Task
    changes: tuple[TaskChange, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.changes)


@dataclass(frozen=True, slots=True)
class TaskPackage:
    """Всё, что нужно агенту с чистым контекстом, одним вызовом (`CONCEPT.md`, 4.2).

    Полно хранится, по оглавлению читается: карточка, связи, вычисляемые признаки,
    последняя сводка, открытые вопросы и неразобранные замечания приезжают **целиком**,
    а остальные записи — строками описи. Тела читаются точечно (`list_entries`,
    `read_entry`).

    Инструмент MCP `get_task` (задача 28) отдаёт эту же структуру.
    """

    task: Task
    links: list[links_service.TaskLink]
    features: TaskFeatures
    summary: Entry | None
    questions: list[Entry]
    #: Замечания без резолюции целиком: «вышло не то» обязано попасться на глаза
    #: читателю с любым контекстом, а не лежать строкой описи (`CONCEPT.md`, 3.4).
    remarks: list[Entry]
    transitions: tuple[TaskStatus, ...]
    index: list[EntryHeading]


# --- Чтение ---------------------------------------------------------------------------


async def get_task(session: AsyncSession, key: str) -> Task:
    """Задача по ключу или `task_not_found`. Адресация мягкая: `trk-1` находит `TRK-1`.

    Ключ разбирается доменом, а не сравнивается строкой: `TRK-007` и `TRK-1-2` — не
    ключи задач, и молча искать по ним нечего. Прав не проверяет: точка входа
    интерфейса — `read_task`.
    """
    canonical = normalize_task_key(key)
    task = await TaskRepository(session).get_by_key(canonical)
    if task is None:
        raise TaskNotFoundError(details={"key": canonical})
    return task


async def read_task(session: AsyncSession, key: str, *, actor: Actor) -> Task:
    ensure_scope(actor, TokenScope.TASK, action="task.read")
    return await get_task(session, key)


async def read_task_package(session: AsyncSession, key: str, *, actor: Actor) -> TaskPackage:
    """Собирает пакет преемника: карточка, связи, признаки, сводка, вопросы, опись, переходы.

    Признаки не хранятся, а считаются из уже прочитанного: связи, список открытых
    вопросов, последняя сводка и опись нужны пакету целиком, а `blocked`, счётчики,
    `last_summary_at` и `last_entry_at` — это их производные. Отдельных запросов ради
    признаков здесь нет.
    """
    task = await read_task(session, key, actor=actor)
    links = await links_service.list_links(session, task, actor=actor)
    summary = await case_service.last_summary(session, task, actor=actor)
    questions = await case_service.open_questions(session, task, actor=actor)
    remarks = await case_service.open_remarks(session, task, actor=actor)
    # Опись читается до признаков: `last_entry_at` считается из неё, и отдельного
    # запроса ради признака здесь по-прежнему нет ни одного.
    index = await case_service.case_index(session, task, actor=actor)
    return TaskPackage(
        task=task,
        links=links,
        features=case_service.features(
            questions, summary, index, blocked=links_service.blocked(links), remarks=remarks
        ),
        summary=summary,
        questions=questions,
        remarks=remarks,
        transitions=allowed_transitions(task.status),
        index=index,
    )


# --- Создание -------------------------------------------------------------------------


async def create_task(
    session: AsyncSession,
    *,
    actor: Actor,
    queue: Queue,
    title: str,
    description: str,
    goal: str = "",
    context: str = "",
    constraints: str = "",
    output: str = "",
    checks: Sequence[str] = (),
    assignee: str | None = None,
    tags: Sequence[str] = (),
    priority: TaskPriority | str = DEFAULT_PRIORITY,
) -> Task:
    """Заводит задачу в `backlog`. Статус не принимается: новая задача рождается только там.

    Порядок шагов важен: сначала проверяется всё, что может отказать, и только потом
    выдаётся номер. Номер выдаётся атомарным `UPDATE ... RETURNING` и при откате
    транзакции теряется навсегда (`docs/notes/db.md`), а неудачные запросы у агентов —
    обычное дело. Новую проверку ставить **до** выдачи номера.

    Очередь изменений занимается раньше строки очереди задач: единый порядок захвата
    (`app/db/locks.py`) — то, чем два одновременных создания не встают друг о друга.
    """
    ensure_scope(actor, TokenScope.TASK, action="task.create")
    await lock_changes(session)

    stored = normalize_fields(
        {
            TaskField.TITLE: title,
            TaskField.DESCRIPTION: description,
            TaskField.GOAL: goal,
            TaskField.CONTEXT: context,
            TaskField.CONSTRAINTS: constraints,
            TaskField.OUTPUT: output,
            TaskField.CHECKS: checks,
            TaskField.ASSIGNEE: assignee,
            TaskField.TAGS: tags,
            TaskField.PRIORITY: priority,
        }
    )

    # Номер — последним, после всех проверок: см. строку документации выше.
    number = await queues_service.next_task_number(session, queue, actor=actor)

    # Очередь передаётся объектом, а не идентификатором: у только что созданной задачи
    # связь иначе не загружена, и сборка ответа полезла бы за ней в базу вне
    # async-контекста — падение `MissingGreenlet` далеко от места ошибки.
    task = Task(
        key=format_task_key(queue.key, number),
        queue=queue,
        status=INITIAL_STATUS,
        version=1,
        **{field.value: value for field, value in stored.items()},
        **created_by_columns(actor.author),
    )
    await TaskRepository(session).add(task)
    # Первая страница дела — в той же транзакции: откат уносит обе разом, и ленты
    # никогда не увидит задачу, которой не появилось.
    await case_service.record_created(session, task, actor=actor)
    return task


# --- Изменение ------------------------------------------------------------------------


async def update_task(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    changes: TaskChanges,
    expected_version: int | None = None,
) -> TaskMutation:
    """Частичное обновление: применяются только переданные поля.

    Ключ и статус в изменения не входят: ключ неизменяем, статус меняется переходом.
    """
    return await apply_task_changes(
        session,
        task,
        actor=actor,
        changes=changes,
        expected_version=expected_version,
        action="task.update",
    )


async def transition_task(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    to: TaskStatus | str,
    reason: str | None = None,
    expected_version: int | None = None,
) -> TaskMutation:
    """Переводит задачу по таблице переходов с проверками из домена."""
    return await apply_task_changes(
        session,
        task,
        actor=actor,
        changes=TaskChanges(),
        transition=Transition(to=to, reason=reason),
        expected_version=expected_version,
        action="task.transition",
    )


async def apply_task_changes(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    changes: TaskChanges,
    transition: Transition | None = None,
    expected_version: int | None = None,
    action: str = "task.update",
) -> TaskMutation:
    """Единая точка изменения задачи. Возвращает список фактических изменений.

    Порядок шагов: права, очередь изменений, версия, право менять эти поля в этом
    статусе, форма значений, применение полей, переход, запись в базу с проверкой
    версии, служебные записи. Переход проверяется **после** применения полей, чтобы
    проверки видели будущее состояние разделов, если правка и переход однажды придут
    одним вызовом.

    Очередь изменений — вторым шагом, до всех проверок: задача приезжает сюда
    прочитанной роутером или инструментом, то есть снимком **до** блокировки. Под
    очередью она перечитывается, и дальше и версия, и статус, и факты перехода
    относятся к одному и тому же моменту, в котором больше никто не пишет.
    """
    ensure_scope(actor, TokenScope.TASK, action=action)
    await lock_changes(session, task)
    _ensure_version(task, expected_version)

    given = changes.given()
    if given:
        _ensure_editable(task, given)
    recorded: list[TaskChange] = []
    for field, after in normalize_fields(given).items():
        before = getattr(task, field.value)
        if _same(before, after):
            continue
        recorded.append(TaskChange(field=field.value, before=_json(before), after=_json(after)))
        # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации внутри
        # значения. `normalize_fields` всегда отдаёт новый список, поэтому присваивание
        # безопасно и для `checks`, и для `tags`.
        setattr(task, field.value, after)

    status_change: tuple[TaskStatus, TaskStatus, str | None] | None = None
    if transition is not None:
        to_status = parse_status(transition.to)
        reason = normalize_reason(transition.reason)
        ensure_transition_allowed(await _transition_facts(session, task, to_status, reason))
        status_change = (task.status, to_status, reason)
        recorded.append(
            TaskChange(
                field=TaskField.STATUS.value, before=task.status.value, after=to_status.value
            )
        )
        task.status = to_status

    if not recorded:
        # Нечего записывать — значит, нечего и подшивать: клиент прислал то, что уже
        # стоит. Версия не растёт, дело не пополняется.
        return TaskMutation(task=task)

    await _flush_checking_version(session, task, expected_version)

    # Служебные записи — после записи задачи и в той же транзакции. Тип записи выбирает
    # сценарий дела по полю, и поле без записи остаться не может: изменение, не
    # оставившее записи, не доходит до ленты и до открытого экрана (`CONCEPT.md`, 4.1).
    for change in recorded:
        field = TaskField(change.field)
        if field is TaskField.STATUS:
            assert status_change is not None
            from_status, to_status, reason = status_change
            await case_service.record_status_changed(
                session,
                task,
                actor=actor,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
            )
        elif field is TaskField.ASSIGNEE:
            await case_service.record_assignee_changed(
                session, task, actor=actor, before=change.before, after=change.after
            )
        elif field in BACKLOG_ONLY_FIELDS:
            await case_service.record_section_changed(
                session, task, actor=actor, field=field, before=change.before, after=change.after
            )
        else:
            # Обвязка: `tags` и `priority`. Ветка без условия намеренно — новое поле
            # карточки получит запись само, а не окажется тихо немым в ленте.
            await case_service.record_field_changed(
                session, task, actor=actor, field=field, before=change.before, after=change.after
            )
    return TaskMutation(task=task, changes=tuple(recorded))


# --- Внутреннее -----------------------------------------------------------------------


async def _transition_facts(
    session: AsyncSession,
    task: Task,
    to_status: TaskStatus,
    reason: str | None,
) -> TransitionFacts:
    """Собирает факты для проверок перехода из состояния задачи, дела и связей.

    Точка подключения новой проверки: факт, которому нужна база, считается здесь
    запросом и кладётся в новое поле `TransitionFacts`.

    Все факты читаются под уже занятой очередью изменений (`apply_task_changes`), и
    новый обязан читаться там же: факт, посчитанный до неё, устаревал бы прямо между
    проверкой и фиксацией — ровно так закрытый родитель получал бы открытого ребёнка.

    Каждый факт считается **только когда он нужен** — по `task.status` и `to_status`.
    Иначе любой переход в `backlog` платил бы запросами за сводку, вердикты, блокеры и
    детей, которых его проверки даже не смотрят. Незаполненный факт при этом запрещает
    переход, а не пропускает его, — за это отвечают значения по умолчанию в
    `TransitionFacts`.
    """
    from_status = task.status
    has_summary = False
    if from_status is TaskStatus.IN_PROGRESS:
        has_summary = await case_service.has_summary_since(session, task, TaskStatus.IN_PROGRESS)
    pending_checks: list[CheckGap] | None = None
    if from_status is TaskStatus.IN_PROGRESS and to_status is TaskStatus.DONE:
        pending_checks = await case_service.verdict_gaps(session, task)
    blockers: list[str] | None = None
    if to_status is TaskStatus.IN_PROGRESS:
        blockers = await links_service.open_blockers(session, task)
    children: list[str] | None = None
    if to_status is TaskStatus.DONE:
        children = await links_service.unclosed_children(session, task)
    return TransitionFacts(
        key=task.key,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        sections=section_values(
            {
                TaskField.GOAL: task.goal,
                TaskField.CONTEXT: task.context,
                TaskField.CONSTRAINTS: task.constraints,
                TaskField.OUTPUT: task.output,
            }
        ),
        checks=tuple(task.checks),
        has_summary_since_in_progress=has_summary,
        checks_without_passed_verdict=pending_checks,
        open_blockers=blockers,
        unclosed_children=children,
    )


def _ensure_version(task: Task, expected_version: int | None) -> None:
    """Оптимистичная блокировка до записи. `None` означает «клиент версию не прислал»."""
    if expected_version is not None and expected_version != task.version:
        raise TaskVersionConflictError(
            details={"key": task.key, "expected": expected_version, "actual": task.version},
        )


async def _flush_checking_version(
    session: AsyncSession,
    task: Task,
    expected_version: int | None,
) -> None:
    """Записывает задачу; `UPDATE ... WHERE version = :seen` ловит гонку с чужой правкой.

    `StaleDataError` означает, что между нашим чтением и записью строку изменил кто-то
    другой: сравнение в Python это не поймало, потому что смотрело на уже устаревший
    объект. `IntegrityError` пропускается наверх как есть — его переводит в `conflict`
    обработчик ошибок.
    """
    try:
        await session.flush()
    except StaleDataError as exc:
        raise TaskVersionConflictError(
            details={
                "key": task.key,
                "expected": expected_version if expected_version is not None else task.version,
                "reason": "concurrent_update",
            },
        ) from exc
    except IntegrityError:
        raise


def _ensure_editable(task: Task, given: dict[TaskField, Any]) -> None:
    """Закрытая задача не меняется; название, описание и разделы — только в `backlog`.

    Проверяется факт запроса, а не факт изменения: правка `goal` в `open` отклоняется,
    даже если прислали то же значение. Иначе клиент получил бы `200` на действие,
    которое в другой раз получит `409`, и не понял бы правила.
    """
    if is_closed(task.status):
        raise TaskClosedError(
            details={
                "key": task.key,
                "status": task.status.value,
                "fields": [field.value for field in given],
            },
        )
    allowed = editable_fields(task.status)
    locked = [field.value for field in given if field not in allowed]
    if locked:
        raise TaskFieldLockedError(
            details={
                "key": task.key,
                "status": task.status.value,
                "fields": locked,
                "editable_in": [TaskStatus.BACKLOG.value],
            },
        )


def _same(before: Any, after: Any) -> bool:
    """Списки сравниваются по порядку: перестановка проверок или тегов — тоже изменение."""
    if isinstance(before, list | tuple) and isinstance(after, list | tuple):
        return list(before) == list(after)
    return before == after


def _json(value: Any) -> Any:
    """«Было» и «стало» в том виде, в каком уедут в `payload`: перечисление — строкой."""
    if isinstance(value, TaskPriority | TaskStatus):
        return value.value
    if isinstance(value, list | tuple):
        return list(value)
    return value
