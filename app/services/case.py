"""Дело: записи агента, служебные записи и чтение.

## Одна точка подшивки

Любая запись — и агентская, и служебная — попадает в дело через `_append`. Тип
служебной записи выводится из сценария (`record_status_changed` пишет
`status_changed`), а не передаётся вызывающим кодом: два независимых словаря имён
разъехались бы, и новое действие молча осталось бы без записи.

Автор записи — автор действия из аутентификации (`Actor.author`), а не сам трекер:
преемнику важно, **кто** перевёл задачу и **кто** поправил раздел. Род `tracker`
остаётся тому, что трекер делает без запроса — первичной инициализации.

Методов правки и удаления здесь нет и не будет.

## Что проверяет домен, а что сценарий

Форму записи (тип, заголовок, части сводки, номер проверки, разбор ссылок) проверяет
`app/domain/case.py` — без базы, одинаково для REST и MCP. Сценарию остаётся то, на что
нужен запрос: есть ли такие участники, существует ли запись, на которую ссылаются, и
вопрос ли это. Замечания обеих проверок приходят одним кодом `entry_fields_invalid` и
одним списком `details.fields`: клиенту незачем знать, на каком шаге его остановили.

## Записи в закрытую задачу подшиваются

`done` и `cancelled` запрещают менять поля и связи, но не дело (`CONCEPT.md`, 3.3):
человек и сторонний агент дописывают в закрытую задачу `note`, `finding` и `answer`.
Поэтому проверки статуса здесь нет — и это не забытая проверка.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.pagination import Page
from app.db.repositories import EntryRepository, ParticipantRepository, TaskRepository
from app.db.wakeup import journal_wakeup
from app.domain.case import (
    EntryContext,
    EntryDraft,
    EntryHeading,
    EntryRef,
    EntryType,
    TaskRef,
    VerdictOutcome,
    build_entry,
    format_entry_ref,
    is_blocking_question,
)
from app.domain.errors import (
    ActorNotAddressableError,
    EntryFieldsInvalidError,
    EntryNotFoundError,
)
from app.domain.fields import FieldProblems
from app.domain.links import LinkKind
from app.domain.tasks import TaskFeatures, TaskField, TaskStatus
from app.domain.tokens import TokenScope
from app.services import participants as participants_service
from app.services.auth import Actor
from app.services.permissions import ensure_scope

# --- Чтение ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskEntry:
    """Запись вместе с ключом её задачи.

    У записи связи с задачей нет, только `task_id`: читающему вопрос во «входящей»
    нужен адрес, по которому идти за делом, и собирать его из второго запроса на
    каждую строку страницы значило бы платить N+1 за поле из четырёх символов.
    """

    entry: Entry
    task_key: str


async def list_entries(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    nos: Sequence[int] | None = None,
    types: Sequence[EntryType] | None = None,
    after_no: int | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Entry]:
    """Записи задачи страницами в порядке `no`, с телами и нагрузкой.

    Фильтры сужают выборку вместе: `types` без `after_no` даёт все сводки дела,
    `after_no` без `types` — всё, что случилось после названной записи.
    """
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).list_page(
        task.id, nos=nos, types=types, after_no=after_no, limit=limit, cursor=cursor
    )


async def read_entry(session: AsyncSession, task: Task, no: int, *, actor: Actor) -> Entry:
    """Одна запись по номеру внутри задачи — адрес из ссылки `TRK-42#12`."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    entry = await EntryRepository(session).get_by_no(task.id, no)
    if entry is None:
        raise EntryNotFoundError(details={"key": task.key, "no": no})
    return entry


async def case_index(session: AsyncSession, task: Task, *, actor: Actor) -> list[EntryHeading]:
    """Опись дела: заголовки всех записей без тел. Часть пакета преемника."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).headings(task.id)


async def last_summary(session: AsyncSession, task: Task, *, actor: Actor) -> Entry | None:
    """Последняя сводка задачи целиком: точка входа преемника (`CONCEPT.md`, 4.2)."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).last_summary(task.id)


async def open_questions(session: AsyncSession, task: Task, *, actor: Actor) -> list[Entry]:
    """Вопросы задачи без ответа целиком. Из них же считаются оба счётчика признаков."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).open_questions(task.id)


def features(
    questions: Sequence[Entry],
    summary: Entry | None,
    *,
    blocked: bool,
) -> TaskFeatures:
    """Вычисляемые признаки из уже прочитанного, без новых запросов.

    Чистая функция, а не ещё один поход в базу: и список открытых вопросов, и последняя
    сводка уже прочитаны для пакета преемника, а счётчики — это их длина и время.

    `blocked` приезжает готовым и **без значения по умолчанию**: считается он из связей,
    которых дело не знает, а умолчание `False` сделало бы забытый аргумент признаком,
    который врёт. Кто его считает — `app/services/links.py`, `blocked`.

    Признак «вопрос блокирующий» берётся из домена (`is_blocking_question`), а не
    проверяется здесь по месту: тот же признак поиск считает запросом, и третьей формы
    одного определения быть не должно.
    """
    return TaskFeatures(
        blocked=blocked,
        open_questions=len(questions),
        open_blocking_questions=sum(
            1 for question in questions if is_blocking_question(question.payload)
        ),
        last_summary_at=summary.created_at if summary is not None else None,
    )


async def list_questions(
    session: AsyncSession,
    *,
    actor: Actor,
    addressee: str | None = None,
    queue: Queue | None = None,
    blocking: bool | None = None,
    open_only: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[TaskEntry]:
    """«Входящая»: вопросы поперёк задач с фильтрами (`CONCEPT.md`, 3.6).

    Адресат по умолчанию — участник, чьим токеном сделан запрос. У общего агентского
    токена участника нет, и адресовать временного агента нельзя вовсе: пустой список
    в этом случае молча соврал бы, что вопросов не пришло, поэтому это отказ.

    Названный адресат ищется в реестре, а не подставляется в фильтр как есть: опечатка
    в имени иначе дала бы пустую «входящую», неотличимую от отсутствия вопросов.
    """
    ensure_scope(actor, TokenScope.TASK, action="question.list")
    if addressee is None:
        if actor.participant is None:
            raise ActorNotAddressableError(details={"signature": actor.author.signature})
        name = actor.participant.name
    else:
        name = (await participants_service.get_participant(session, addressee)).name
    page = await EntryRepository(session).questions_page(
        addressee=name,
        queue_id=queue.id if queue is not None else None,
        blocking=blocking,
        open_only=open_only,
        limit=limit,
        cursor=cursor,
    )
    return Page(
        items=[TaskEntry(entry=entry, task_key=key) for entry, key in page.items],
        next_cursor=page.next_cursor,
    )


async def count_open_questions(session: AsyncSession, *, participant: Participant) -> int:
    """Сколько открытых вопросов адресовано участнику.

    Прав не проверяет и адресата не разрешает: принимает уже прочитанного участника,
    потому что зовут её оттуда, где он уже на руках, — с первого экрана
    (`app/services/bootstrap.py`). Отдельный сценарий с собственной проверкой набора
    завёл бы вторую точку входа к тому же числу.
    """
    return await EntryRepository(session).count_questions(addressee=participant.name)


# --- Записи агента --------------------------------------------------------------------


async def append_entry(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    type: Any,
    title: Any = None,
    body: Any = "",
    payload: dict[str, Any] | None = None,
    refs: Any = (),
) -> Entry:
    """Подшивает запись агента: форма проверяется доменом, существование — здесь.

    Единственная точка входа для всех типов записей агента. Обёртки ниже (`add_summary`,
    `ask`, `answer`, `add_verdict`, `add_entry`) существуют ради инструментов MCP,
    у которых один инструмент — один вид действия; своей логики в них нет.
    """
    ensure_scope(actor, TokenScope.TASK, action="case.append")
    draft = build_entry(
        EntryContext(task_key=task.key, checks=task.checks),
        type=type,
        title=title,
        body=body,
        payload=payload,
        refs=refs,
    )
    await _ensure_targets_exist(session, task, draft)
    return await _append(
        session,
        task,
        actor=actor,
        type=draft.type,
        title=draft.title,
        body=draft.body,
        payload=draft.payload,
        refs=draft.refs,
    )


async def add_summary(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    done: Any,
    remaining: Any,
    blockers: Any,
    next_step: Any,
    body: Any = "",
    refs: Any = (),
) -> Entry:
    """Справка при передаче: сделано, осталось, что мешает, следующий шаг.

    Заголовка не принимает: он равен первой строке `next_step`, и второй способ задать
    опись развёл бы её с содержанием.
    """
    return await append_entry(
        session,
        task,
        actor=actor,
        type=EntryType.SUMMARY,
        body=body,
        refs=refs,
        payload={
            "done": done,
            "remaining": remaining,
            "blockers": blockers,
            "next_step": next_step,
        },
    )


async def ask(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    addressees: Any,
    title: Any,
    body: Any = "",
    blocking: Any = None,
    refs: Any = (),
) -> Entry:
    """Вопрос участникам реестра. `blocking` обязателен и значения по умолчанию не имеет."""
    return await append_entry(
        session,
        task,
        actor=actor,
        type=EntryType.QUESTION,
        title=title,
        body=body,
        refs=refs,
        payload={"addressees": addressees, "blocking": blocking},
    )


async def answer(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    question_no: Any,
    body: Any = "",
    refs: Any = (),
) -> Entry:
    """Ответ на вопрос той же задачи. Ответить может кто угодно, ответов может быть много."""
    return await append_entry(
        session,
        task,
        actor=actor,
        type=EntryType.ANSWER,
        body=body,
        refs=refs,
        payload={"question_no": question_no},
    )


async def add_verdict(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    check_no: Any,
    outcome: Any,
    evidence: Any = "",
    refs: Any = (),
) -> Entry:
    """Исход одной обзорной проверки. Доказательство — тело записи."""
    return await append_entry(
        session,
        task,
        actor=actor,
        type=EntryType.VERDICT,
        body=evidence,
        refs=refs,
        payload={"check_no": check_no, "outcome": outcome},
    )


async def add_entry(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    type: Any,
    title: Any,
    body: Any = "",
    refs: Any = (),
) -> Entry:
    """Запись без нагрузки: `decision`, `attempt`, `finding`, `artifact`, `note`."""
    return await append_entry(
        session, task, actor=actor, type=type, title=title, body=body, refs=refs
    )


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
    """Переход статуса с причиной, если она была: по ней преемник понимает откат.

    Нагрузка этой записи — не только история: по `payload.to` считается последний вход
    в `in_progress`, от которого проверка перехода ищет сводку. Менять её имена нельзя,
    не поправив `EntryRepository.last_entry_into_status`.
    """
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


async def record_link_change(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    added: bool,
    kind: LinkKind,
    other_key: str,
) -> Entry:
    """Появление или снятие связи — в дело **этой** стороны, её собственным видом связи.

    Один сценарий подшивает две такие записи, по одной в каждую задачу: связь — событие
    обеих, и дыра в деле одной из них означала бы, что преемник не узнает, откуда взялся
    его блокер. Вид связи у записей поэтому разный: у `A` — `blocks`, у `B` —
    `blocked_by`; ключ в `other` — всегда ключ **другой** стороны.

    Порядок двух вызовов важен и задаётся вызывающим: `allocate_no` держит строку задачи
    до конца транзакции, и две подшивки в разном порядке взаимно заблокировались бы
    (`docs/notes/links.md`).
    """
    action = "added" if added else "removed"
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.LINK_ADDED if added else EntryType.LINK_REMOVED,
        title=f"Link {action}: {kind.value} {other_key}",
        payload={"kind": kind.value, "other": other_key},
    )


# --- Внутреннее -----------------------------------------------------------------------


async def _ensure_targets_exist(session: AsyncSession, task: Task, draft: EntryDraft) -> None:
    """Проверки, которым нужна база: адресаты, ссылки, номер вопроса.

    Все замечания собираются вместе и уезжают одним ответом — по тому же правилу, что и
    замечания к форме: агент чинит запрос за одну попытку.
    """
    problems = FieldProblems()
    await _check_addressees(session, draft, problems)
    await _check_question_no(session, task, draft, problems)
    await _check_refs(session, task, draft, problems)
    problems.raise_as(EntryFieldsInvalidError, key=task.key)


async def _check_addressees(
    session: AsyncSession, draft: EntryDraft, problems: FieldProblems
) -> None:
    """Адресовать можно только участника реестра (`CONCEPT.md`, 3.6).

    Временных агентов адресовать нельзя намеренно: у них нет строки в реестре, и
    доставки вопросов в трекере всё равно нет — агент с вопросом собирает контекст сам.
    """
    addressees: list[str] = draft.payload.get("addressees", [])
    if not addressees:
        return
    known = await ParticipantRepository(session).existing_names(addressees)
    for name in addressees:
        if name not in known:
            problems.add("addressees", "unknown_participant", name=name)


async def _check_question_no(
    session: AsyncSession, task: Task, draft: EntryDraft, problems: FieldProblems
) -> None:
    """`question_no` указывает на запись `question` **этой** задачи.

    Проверяются оба условия сразу: запись другой задачи сюда не попадёт по построению
    (номер ищется в этой), а запись не того типа — вполне, и ответ на сводку сделал бы
    вопрос закрытым неизвестно чем.
    """
    if draft.type is not EntryType.ANSWER:
        return
    question_no = draft.payload["question_no"]
    question = await EntryRepository(session).get_by_no(task.id, question_no)
    if question is None:
        problems.add("question_no", "unknown_entry", key=task.key, no=question_no)
    elif question.type is not EntryType.QUESTION:
        problems.add(
            "question_no",
            "not_a_question",
            key=task.key,
            no=question_no,
            got=question.type.value,
        )


async def _check_refs(
    session: AsyncSession, task: Task, draft: EntryDraft, problems: FieldProblems
) -> None:
    """Ссылки на задачи и записи существуют; адреса не проверяются вовсе.

    Задачи собираются в один запрос, записи — по одному запросу на задачу: ссылок в
    записи единицы, и разбор их по задачам дешевле, чем `IN` по парам.
    """
    if not draft.tracker_refs:
        return
    keys = {ref.key for ref in draft.tracker_refs}
    # Сама задача уже прочитана: запрашивать её второй раз ради ссылки на соседнюю
    # запись значило бы платить лишним запросом за каждый `refs: ["TRK-1#3"]`.
    tasks = {task.key: task}
    tasks.update(await TaskRepository(session).get_by_keys(sorted(keys - {task.key})))

    entries = EntryRepository(session)
    wanted: dict[str, set[int]] = {}
    for ref in draft.tracker_refs:
        if ref.key not in tasks:
            problems.add("refs", "unknown_task", ref=_ref_text(ref))
        elif isinstance(ref, EntryRef):
            wanted.setdefault(ref.key, set()).add(ref.no)
    for key, nos in wanted.items():
        existing = await entries.existing_nos(tasks[key].id, sorted(nos))
        for no in sorted(nos - existing):
            problems.add("refs", "unknown_entry", ref=_ref_text(EntryRef(key=key, no=no)))


def _ref_text(ref: TaskRef | EntryRef) -> str:
    """Ссылка в каноническом виде — та же строка, что уедет в `refs` записи."""
    return format_entry_ref(ref.key, ref.no) if isinstance(ref, EntryRef) else ref.key


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

    Здесь же, и только здесь, журнал получает две вещи, без которых лента (задача 26)
    неверна. Порядок обязателен и объяснён в самих методах:

    1. `lock_changes` — очередь изменений, из-за которой порядок `seq` совпадает с
       порядком фиксации. Берётся **до** блокировки строки задачи: обратный порядок
       даёт взаимную блокировку. Мутирующий сценарий занял её ещё до чтения фактов, но
       повторный захват в той же транзакции законен и ничего не стоит, — а подшивка,
       которая полагалась бы на чужой захват, однажды пришла бы из сценария, где его
       забыли сделать.
    2. `announce` — оповещение ждущих ленту. После `add`, потому что номер выдаёт база;
       внутри транзакции, потому что доставить его PostgreSQL обязан при фиксации, а не
       раньше строки.
    """
    repository = EntryRepository(session)
    await lock_changes(session)
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
    await repository.add(entry)
    await journal_wakeup.announce(session, entry.seq)
    return entry


async def verdict_gaps(session: AsyncSession, task: Task) -> list[int]:
    """Номера проверок, у которых последний по времени вердикт не `passed`.

    Считается для проверки перехода `review → done` (`app/domain/tasks.py`), поэтому
    живёт здесь, рядом с делом, а не в сценарии задачи: домен в базу не ходит, а знание
    о том, что вердикт — это запись дела, за пределы этого модуля не уезжает.
    """
    outcomes = await EntryRepository(session).last_verdict_outcomes(task.id)
    return [
        check_no
        for check_no in range(1, len(task.checks) + 1)
        if outcomes.get(check_no) is not VerdictOutcome.PASSED
    ]


async def has_summary_since(session: AsyncSession, task: Task, status: TaskStatus) -> bool:
    """Есть ли сводка, подшитая после последнего входа задачи в этот статус.

    Записи о входе нет — значит, и сводки после неё нет: непосчитанный факт обязан
    запрещать переход, а не пропускать его. Такое состояние означает испорченное дело
    (вход в `in_progress` всегда подшивает `status_changed`), и молча считать его
    успехом нельзя.
    """
    repository = EntryRepository(session)
    entered = await repository.last_entry_into_status(task.id, status)
    if entered is None:
        return False
    return await repository.has_entry_after(task.id, EntryType.SUMMARY, after_no=entered)
