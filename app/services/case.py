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

## `action_id` — признак одного действия (TRK-118)

`_append` — точка, где он и присваивается: не передан вызывающим — генерируется
здесь, `uuid.uuid4()`. Одиночным подшивкам (`add_summary`, `ask`, `record_created` и
так далее вне пакетной подшивки) этого достаточно — вызов подшивает одну запись, и
у неё одно значение. Пакетным сценариям (`apply_task_changes`, `close_task` в
`app/services/tasks.py`, `_record_on_both_sides` в `app/services/links.py`)
достаточности нет: им нужно одно значение на **все** свои записи, и они генерируют
его сами, до первого вызова сюда, и передают явно в каждый — подробности в
`app/db/models/entry.py`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.pagination import Page
from app.db.repositories import EntryRepository, ParticipantRepository, TaskRepository
from app.db.wakeup import journal_wakeup
from app.domain.case import (
    AGENT_ENTRY_TYPES,
    CLOSING_SUMMARY_PART,
    EntryContext,
    EntryDraft,
    EntryHeading,
    EntryRef,
    EntryType,
    QuestionOrder,
    TaskRef,
    VerdictOutcome,
    build_entry,
    continuation_key,
    format_entry_ref,
    is_blocking_question,
    mark_outdated_verdicts,
)
from app.domain.errors import (
    ActorNotAddressableError,
    AddresseeWithAnyAddresseeError,
    EntryFieldsInvalidError,
    EntryNotFoundError,
)
from app.domain.fields import FieldProblems
from app.domain.links import LinkKind, other_side_phrase
from app.domain.tasks import (
    FIRST_CHECK_NUMBER,
    CheckGap,
    CheckGapReason,
    TaskFeatures,
    TaskField,
    TaskStatus,
    checks_without_verdict,
)
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


@dataclass(frozen=True, slots=True)
class AnsweredQuestion:
    """Вопрос из выдачи поперёк задач вместе с ответами на него.

    Ответы едут со страницей, а не отдельным запросом клиента на каждую задачу: история
    вопросов без них бессмысленна, а собирать их по делам — запрос на строку. Пустой
    список означает «ответа нет», то есть вопрос открыт.
    """

    entry: Entry
    task_key: str
    answers: list[Entry]


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
    """Опись дела: заголовки всех записей без тел. Часть пакета преемника.

    Устаревшие вердикты помечаются здесь, а не в запросе: признак считается по порядку
    записей — «вердикт подшит до того, как его проверку переписали», — и это правило
    домена, а не выборка из базы (`app/domain/case.py`, `mark_outdated_verdicts`).
    Опись и так приходит целиком и упорядоченной, второго запроса пометка не стоит.
    """
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return mark_outdated_verdicts(await EntryRepository(session).headings(task.id))


async def latest_entry_no(session: AsyncSession, task: Task, *, actor: Actor) -> int:
    """Номер последней записи дела — адрес того, что вызывающий только что в него подшил.

    Не общего назначения: годится сразу после подшивки, в той же транзакции, под общей
    блокировкой изменений (`app/db/locks.py`, `lock_changes`) — она не отпускает других
    писателей до конца вызова, и «последняя запись» здесь факт, а не гонка. Так `link` и
    `unlink` называют номер `link_added`/`link_removed`, подшитый в дело **другой**
    задачи, не читая его целиком и не протаскивая номер через сигнатуру `links_service`
    (`docs/notes/mcp.md`).
    """
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    no = await EntryRepository(session).latest_no(task.id)
    assert no is not None  # у любой задачи есть хотя бы `created`
    return no


async def last_summary(session: AsyncSession, task: Task, *, actor: Actor) -> Entry | None:
    """Последняя сводка задачи целиком: точка входа преемника (`CONCEPT.md`, 4.2)."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).last_summary(task.id)


async def open_questions(session: AsyncSession, task: Task, *, actor: Actor) -> list[Entry]:
    """Вопросы задачи без ответа целиком. Из них же считаются оба счётчика признаков."""
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).open_questions(task.id)


async def open_remarks(session: AsyncSession, task: Task, *, actor: Actor) -> list[Entry]:
    """Замечания задачи без резолюции целиком. Из них же считается признак `open_remarks`.

    Приезжают в пакете преемника рядом с открытыми вопросами (`CONCEPT.md`, 4.2): агент
    с чистым контекстом обязан увидеть «вышло не то» одним вызовом, а не найти его в
    описи среди двух десятков строк.
    """
    ensure_scope(actor, TokenScope.TASK, action="case.read")
    return await EntryRepository(session).open_remarks(task.id)


def features(
    questions: Sequence[Entry],
    summary: Entry | None,
    index: Sequence[EntryHeading],
    *,
    blocked: bool,
    remarks: Sequence[Entry] = (),
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
        open_remarks=len(remarks),
        last_summary_at=summary.created_at if summary is not None else None,
        last_entry_at=_last_entry_at(index),
    )


def _last_entry_at(index: Sequence[EntryHeading]) -> datetime | None:
    """Время последней записи агента или человека — из уже прочитанной описи.

    Питоновский двойник запроса `last_entry_at` в `app/db/repositories/entries.py`:
    карточка считает признак из описи, которую и так читает для пакета преемника,
    список — подзапросом. Учтённый набор типов у обоих один и тот же, `AGENT_ENTRY_TYPES`,
    и это единственное, что удерживает их от расхождения.

    Опись приходит целиком и по возрастанию номера, поэтому нужная запись — последняя
    учтённая с конца.
    """
    for heading in reversed(index):
        if heading.type in AGENT_ENTRY_TYPES:
            return heading.created_at
    return None


async def list_questions(
    session: AsyncSession,
    *,
    actor: Actor,
    addressee: str | None = None,
    project: Project | None = None,
    any_addressee: bool = False,
    blocking: bool | None = None,
    open_only: bool = True,
    order: QuestionOrder = QuestionOrder.OLDEST,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[AnsweredQuestion]:
    """«Входящая» и история: вопросы поперёк задач с фильтрами (`CONCEPT.md`, 3.6).

    Адресат по умолчанию — участник, чьим токеном сделан запрос. У общего агентского
    токена участника нет, и адресовать временного агента нельзя вовсе: пустой список
    в этом случае молча соврал бы, что вопросов не пришло, поэтому это отказ.
    `any_addressee` снимает условие адресата явно — тогда и отказывать не в чем; вместе
    с названным адресатом это противоречие, а не уточнение, и тоже отказ.

    Названный адресат ищется в реестре, а не подставляется в фильтр как есть: опечатка
    в имени иначе дала бы пустую «входящую», неотличимую от отсутствия вопросов.

    Каждый вопрос едет с ответами на него — вторым запросом на всю страницу; у выдачи
    одних открытых вопросов ответов нет, и этот запрос не делается.
    """
    ensure_scope(actor, TokenScope.TASK, action="question.list")
    name: str | None
    if any_addressee:
        if addressee is not None:
            raise AddresseeWithAnyAddresseeError(details={"addressee": addressee})
        name = None
    elif addressee is None:
        if actor.participant is None:
            raise ActorNotAddressableError(details={"signature": actor.author.signature})
        name = actor.participant.name
    else:
        name = (await participants_service.get_participant(session, addressee)).name
    repository = EntryRepository(session)
    page = await repository.questions_page(
        addressee=name,
        project_id=project.id if project is not None else None,
        blocking=blocking,
        open_only=open_only,
        order=order,
        limit=limit,
        cursor=cursor,
    )
    # У открытых вопросов ответов нет по определению открытости: второй запрос
    # «входящей» ничего бы не нашёл, и платить за него незачем.
    answers = {} if open_only else await repository.answers_to([e for e, _ in page.items])
    return Page(
        items=[
            AnsweredQuestion(
                entry=entry, task_key=key, answers=answers.get((entry.task_id, entry.no), [])
            )
            for entry, key in page.items
        ],
        next_cursor=page.next_cursor,
    )


async def list_remarks(
    session: AsyncSession,
    *,
    actor: Actor,
    author: str | None = None,
    project: Project | None = None,
    open_only: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[TaskEntry]:
    """Замечания поперёк задач с фильтрами (`CONCEPT.md`, 3.4).

    Умолчания у автора нет, в отличие от адресата у вопросов, и это решение, а не
    пропуск: вопрос ждёт того, кому задан, а замечание — того, кто ведёт задачу.
    «Показать мои» было бы неверной точкой зрения для агента, а «показать все» верна для
    обоих: человек уточняет автора, агент читает всё.

    Автор не разрешается по реестру, тоже намеренно: подписью бывает и метка временного
    агента, которой в реестре нет, — требовать существования значило бы запретить отбор
    по половине законных авторов. Строка канонизируется так же, как имена и метки, —
    иначе `Owner` и `owner` дали бы разные выдачи на одних данных.
    """
    ensure_scope(actor, TokenScope.TASK, action="remark.list")
    page = await EntryRepository(session).remarks_page(
        author=None if author is None else author.strip().lower(),
        project_id=project.id if project is not None else None,
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


# --- Что подшивают одним вызовом ------------------------------------------------------
#
# Формы входа, а не записи: значения лежат здесь такими, какими их прислал клиент, и
# проверяет их домен в `build_entry` — как и у одиночных обёрток ниже. Нужны они
# закрытию (`app/services/tasks.py`, `close_task`): оно подшивает несколько записей и
# переводит статус одной транзакцией, и оба интерфейса собирают его вход из этих трёх
# форм, а не каждый из своих.


@dataclass(frozen=True, slots=True)
class EntryFiling:
    """Запись без нагрузки: тип, заголовок, тело и ссылки."""

    type: Any
    title: Any
    body: Any = ""
    refs: Sequence[Any] = ()


@dataclass(frozen=True, slots=True)
class VerdictFiling:
    """Исход одной обзорной проверки и доказательство к нему."""

    check_no: Any
    outcome: Any
    evidence: Any = ""


@dataclass(frozen=True, slots=True)
class SummaryFiling:
    """Части закрывающей сводки. Заголовка нет: его выводит домен из `done`.

    Форма одна на всё закрытие, и `unmeasured` в ней обязателен наравне с остальными:
    значение по умолчанию сделало бы «ничего не измерено» невидимым пропуском.
    """

    done: Any
    remaining: Any
    blockers: Any
    next_step: Any
    unmeasured: Any


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
    closing: bool = False,
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Подшивает запись агента: форма проверяется доменом, существование — здесь.

    Единственная точка входа для всех типов записей агента. Обёртки ниже (`add_summary`,
    `ask`, `answer`, `add_verdict`, `add_entry`) существуют ради инструментов MCP,
    у которых один инструмент — один вид действия; своей логики в них нет.

    `closing` доезжает до домена как часть контекста: от него зависит состав частей
    сводки. Снаружи его не задают — он приходит от сценария закрытия, который один и
    знает, что подшивает последнюю запись работы.

    `action_id` доезжает до `_append` как есть: не передан — тот сгенерирует его сам.
    """
    ensure_scope(actor, TokenScope.TASK, action="case.append")
    draft = build_entry(
        EntryContext(task_key=task.key, checks=task.checks, closing=closing),
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
        action_id=action_id,
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
    unmeasured: Any = None,
    closing: bool = False,
    body: Any = "",
    refs: Any = (),
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Справка при передаче: сделано, осталось, что мешает, следующий шаг.

    Заголовка не принимает: он равен первой строке `done`, и второй способ задать
    опись развёл бы её с содержанием. Именно `done`: в описи сводка обязана говорить о
    случившемся, как и все соседние строки.

    При закрытии добавляется `unmeasured` — какую часть цели не измерила ни одна
    проверка. Ключ кладётся в нагрузку **всегда**, когда сводка закрывающая, даже с
    пустым значением: иначе непереданная часть уехала бы в домен как отсутствующая
    и вместо «required» получила бы молчание. Вне закрытия ключа нет — и присланный
    домен отвергнет, а не выбросит молча.
    """
    payload: dict[str, Any] = {
        "done": done,
        "remaining": remaining,
        "blockers": blockers,
        "next_step": next_step,
    }
    if closing or unmeasured is not None:
        payload[CLOSING_SUMMARY_PART] = unmeasured
    return await append_entry(
        session,
        task,
        actor=actor,
        type=EntryType.SUMMARY,
        body=body,
        refs=refs,
        payload=payload,
        closing=closing,
        action_id=action_id,
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
    action_id: uuid.UUID | None = None,
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
        action_id=action_id,
    )


async def answer(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    question_no: Any,
    body: Any = "",
    refs: Any = (),
    action_id: uuid.UUID | None = None,
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
        action_id=action_id,
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
    action_id: uuid.UUID | None = None,
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
        action_id=action_id,
    )


async def resolve(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    remark_no: Any,
    outcome: Any,
    continuation: Any = None,
    body: Any = "",
    refs: Any = (),
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Резолюция по замечанию: чем разобрано и куда ушла работа.

    Разбирает замечание любой исход, в том числе `needs_detail` (`CONCEPT.md`, 3.4).
    Ключ задачи-продолжения принимается только с исходом `accepted` и тогда обязателен —
    это правило домена, здесь оно только передаётся дальше под именем `task`, под каким
    и ляжет в нагрузку.
    """
    return await append_entry(
        session,
        task,
        actor=actor,
        type=EntryType.RESOLUTION,
        body=body,
        refs=refs,
        payload={"remark_no": remark_no, "outcome": outcome, "task": continuation},
        action_id=action_id,
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
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Запись без нагрузки: `decision`, `attempt`, `finding`, `artifact`, `remark`, `note`."""
    return await append_entry(
        session,
        task,
        actor=actor,
        type=type,
        title=title,
        body=body,
        refs=refs,
        action_id=action_id,
    )


# --- Служебные записи -----------------------------------------------------------------
#
# Прав здесь не проверяют: это не точки входа, а продолжение сценария, который права уже
# проверил. Заголовки — на английском: служебный слой, а не пользовательские данные.


async def record_created(
    session: AsyncSession, task: Task, *, actor: Actor, action_id: uuid.UUID | None = None
) -> Entry:
    """Первая страница дела: задача заведена. Нагрузки нет — карточка и есть содержание."""
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.CREATED,
        title="Task created",
        action_id=action_id,
    )


async def record_status_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    from_status: TaskStatus,
    to_status: TaskStatus,
    reason: str | None,
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Переход статуса с причиной, если она была: по ней преемник понимает откат.

    Нагрузка этой записи — не только история: по `payload.to` считается последний вход
    в `in_progress` — граница, от которой проверки перехода ищут и сводку, и вердикты
    этого захода. Менять её имена нельзя, не поправив
    `EntryRepository.last_entry_into_status`.
    """
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.STATUS_CHANGED,
        title=f"Status changed: {from_status.value} -> {to_status.value}",
        payload={"from": from_status.value, "to": to_status.value, "reason": reason},
        action_id=action_id,
    )


async def record_section_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    field: TaskField,
    before: Any,
    after: Any,
    check_no: int | None = None,
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Правка названия, описания или раздела в `backlog`: «было / стало» целиком.

    Целиком, а не разницей: преемник читает запись, а не собирает текст из патчей, и
    тела разделов ограничены потолком, при котором копия не страшна.

    `check_no` заполнен у точечной правки проверки, и тогда «целиком» — это тексты самой
    проверки, а не всего списка. Он же попадает в заголовок и в опись: «раздел `checks`
    изменён» не говорит читающему, какой из вердиктов после этого перестал относиться к
    делу, а номер — говорит.
    """
    named = field.value if check_no is None else f"{field.value}[{check_no}]"
    payload: dict[str, Any] = {"field": field.value, "before": before, "after": after}
    if check_no is not None:
        # Только у точечной правки: `check_no: null` у правки названия или цели был бы
        # полем без смысла в каждой второй записи дела, и стоил бы места в каждой.
        payload["check_no"] = check_no
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.SECTION_CHANGED,
        title=f"Section changed: {named}",
        payload=payload,
        action_id=action_id,
    )


async def record_field_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    field: TaskField,
    before: Any,
    after: Any,
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Правка обвязки задачи: то, что меняется в любом незакрытом статусе.

    Сегодня это только `priority`. Отдельно от `section_changed` не ради симметрии:
    тот про задание — договор с агентом, неизменяемый от `open` и дальше, — а это
    обвязка, которую перекладывают когда угодно. Один тип на оба означал бы «section»
    у приоритета.

    Запись нужна не делу, а ленте: изменение, не оставившее записи, не доходит до
    открытого экрана вовсе (`CONCEPT.md`, 4.1). Читателю дела она стоит одной строки:
    служебные записи сжимаются в ленте и не входят в `last_entry_at`.
    """
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.FIELD_CHANGED,
        title=f"Field changed: {field.value}",
        payload={"field": field.value, "before": before, "after": after},
        action_id=action_id,
    )


async def record_assignee_changed(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    before: str | None,
    after: str | None,
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Смена исполнителя — единственная правка обвязки, которая подшивается в дело."""
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.ASSIGNEE_CHANGED,
        title=f"Assignee changed: {before or 'nobody'} -> {after or 'nobody'}",
        payload={"before": before, "after": after},
        action_id=action_id,
    )


async def record_link_change(
    session: AsyncSession,
    task: Task,
    *,
    actor: Actor,
    added: bool,
    kind: LinkKind,
    other_key: str,
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Появление или снятие связи — в дело **этой** стороны, её собственным видом связи.

    Один сценарий подшивает две такие записи, по одной в каждую задачу: связь — событие
    обеих, и дыра в деле одной из них означала бы, что преемник не узнает, откуда взялся
    его блокер. Вид связи у записей поэтому разный: у `A` — `blocks`, у `B` —
    `blocked_by`; ключ в `other` — всегда ключ **другой** стороны.

    Порядок двух вызовов важен и задаётся вызывающим: `allocate_no` держит строку задачи
    до конца транзакции, и две подшивки в разном порядке взаимно заблокировались бы
    (`docs/notes/links.md`). Обе стороны одной связи делят один `action_id`, который
    вызывающий (`_record_on_both_sides`) генерирует один раз и передаёт в оба вызова.
    """
    action = "added" if added else "removed"
    return await _append(
        session,
        task,
        actor=actor,
        type=EntryType.LINK_ADDED if added else EntryType.LINK_REMOVED,
        # Заголовок называет роль другой стороны фразой (TRK-135); вид в `payload` —
        # по-прежнему роль своей задачи, как в `links` карточки.
        title=f"Link {action}: {other_side_phrase(kind, other_key)}",
        payload={"kind": kind.value, "other": other_key},
        action_id=action_id,
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
    await _check_remark_no(session, task, draft, problems)
    await _check_continuation(session, draft, problems)
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


async def _check_remark_no(
    session: AsyncSession, task: Task, draft: EntryDraft, problems: FieldProblems
) -> None:
    """`remark_no` указывает на запись `remark` **этой** задачи — как `question_no` у ответа.

    Тип проверяется наравне с существованием: резолюция по сводке закрыла бы неизвестно
    что, а признак `open_remarks` при этом не сдвинулся бы — расхождение, которое потом
    не объяснить.
    """
    if draft.type is not EntryType.RESOLUTION:
        return
    remark_no = draft.payload["remark_no"]
    remark = await EntryRepository(session).get_by_no(task.id, remark_no)
    if remark is None:
        problems.add("remark_no", "unknown_entry", key=task.key, no=remark_no)
    elif remark.type is not EntryType.REMARK:
        problems.add(
            "remark_no",
            "not_a_remark",
            key=task.key,
            no=remark_no,
            got=remark.type.value,
        )


async def _check_continuation(
    session: AsyncSession, draft: EntryDraft, problems: FieldProblems
) -> None:
    """Задача-продолжение существует. Её статус не проверяется вовсе.

    Работа могла уйти в задачу, которую уже успели закрыть, — резолюция описывает
    прошлое и от чужого статуса не зависит. Отбор `remarks_in_work` этот статус
    учитывает сам, в момент запроса.
    """
    key = continuation_key(draft.payload)
    if draft.type is not EntryType.RESOLUTION or key is None:
        return
    if not await TaskRepository(session).get_by_keys([key]):
        problems.add("task", "unknown_task", key=key)


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
    action_id: uuid.UUID | None = None,
) -> Entry:
    """Подшивает запись: номер в задаче выдаётся под блокировкой строки задачи.

    Автор раскладывается по колонкам общей функцией `created_by_columns` и берётся
    только из структуры автора действия — второй раскладки в проекте нет.

    `action_id` — признак одного действия (TRK-118, `app/db/models/entry.py`): не
    передан вызывающим — генерируется здесь и достаётся только этой записи. Пакетная
    подшивка (`apply_task_changes`, `close_task`, `_record_on_both_sides`) передаёт
    сюда одно и то же значение на все свои записи — так оно и не оказалось бы вычислено
    заново на каждой.

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
        action_id=action_id if action_id is not None else uuid.uuid4(),
        **created_by_columns(actor.author),
    )
    await repository.add(entry)
    await journal_wakeup.announce(session, entry.seq)
    return entry


async def verdict_gaps(session: AsyncSession, task: Task) -> list[CheckGap]:
    """Проверки, у которых в **этом заходе** нет положительного вердикта, с причиной.

    Этот заход — всё, что подшито после последнего входа задачи в `in_progress`
    (`CONCEPT.md`, 3.3). Вердикты прошлых заходов остаются в деле как история, но в
    валидации не участвуют: после возврата `in_progress → open` работа переделывается, а
    после возврата в `backlog` могут быть переписаны и сами `checks`, и старое `passed`
    относилось бы к другой работе или к другой проверке.

    Причина у каждой проверки своя: `no_verdict` — вердикта после границы нет вовсе,
    `failed` — последний вердикт провальный. Отказ перехода несёт её в `details.checks`:
    по одному номеру проверки читающий не понял бы, что именно не так.

    Записи о входе в `in_progress` нет — значит, и вердиктов этого захода нет, и
    непройденными числятся все проверки. Такое дело испорчено (вход в `in_progress`
    всегда подшивает `status_changed`), и молча считать его успехом нельзя — то же
    правило, что у `has_summary_since`.

    Считается для проверки перехода `in_progress → done` (`app/domain/tasks.py`),
    поэтому живёт здесь, рядом с делом, а не в сценарии задачи: домен в базу не ходит, а
    знание о том, что вердикт — это запись дела, за пределы этого модуля не уезжает.
    """
    repository = EntryRepository(session)
    entered = await repository.last_entry_into_status(task.id, TaskStatus.IN_PROGRESS)
    if entered is None:
        return checks_without_verdict(task.checks)
    outcomes = await repository.last_verdict_outcomes(task.id, after_no=entered)
    gaps: list[CheckGap] = []
    for check_no in range(FIRST_CHECK_NUMBER, FIRST_CHECK_NUMBER + len(task.checks)):
        outcome = outcomes.get(check_no)
        if outcome is VerdictOutcome.PASSED:
            continue
        reason = CheckGapReason.NO_VERDICT if outcome is None else CheckGapReason.FAILED
        gaps.append(CheckGap(check_no=check_no, reason=reason))
    return gaps


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
