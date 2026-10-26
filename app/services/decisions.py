"""Записи знания дела проекта и дела области — решения и заметки: статус при чтении,
замена, ссылки задач на решения.

Решение — запись `decision` дела проекта (TRK#88) или дела области, заметка —
запись `finding` того же дела; замена у них одна (решение TRK#48, раздел 2) и одна у обоих
владельцев (решение TRK#57, раздел 5). Отдельной таблицы и хранимого статуса нет: запись
действует, пока ни одна более поздняя запись того же типа и того же дела не назвала её в
`supersedes`, и статус считается здесь при каждом чтении, как признак `blocked` у задачи.
Замена поэтому не пишет ни строчки ни в дело заменённой, ни в дела задач, которые на
решение ссылаются, и не будит их (TRK#160).

## Один расчёт на проект и область

Владелец дела со знанием — проект или область (`CaseOwner`). Чем они различаются здесь —
только выборкой (`project_id` или `area_id`) и адресом в ссылке (`TRK#7` или
`TRK/mcp#3`); правило статуса, проверки замены и ссылки задачи — одни и те же функции, а
не вторая копия для области (TRK#12). Владелец объявлен здесь, а не в
`app/services/case.py`: дело импортирует этот модуль, а не наоборот.

## Одно правило, несколько потребителей

Преемника считает одна функция домена — `successors` (`app/domain/decisions.py`):

- пакет задачи (`get_task`): решения, на которые ссылается задача, со статусом и
  преемником — `cited_decisions`;
- чтение проекта в REST: все решения проекта со статусом — `project_decisions`;
- чтение проекта и области в MCP: действующие решения и заметки ссылкой и заголовком и
  число записей знания по типам — `case_knowledge`;
- чтение дела проекта и области: статус и преемник у каждой записи знания и отбор
  `in_force` — `case_standings`;
- проверки записи: новая ссылка задачи (`check_cited`) называет только действующее
  решение, замена (`check_superseded`) — только действующую запись своего типа и своего
  дела.

Все читают записи знания дела целиком: статус записи зависит от всех более поздних, и
выборка «только названных» дала бы неверный ответ.

## Проверки — под очередью изменений

`check_cited` и `check_superseded` зовут сценарии, которые уже заняли очередь изменений
(`app/db/locks.py`): «запись ещё действует» — факт, который соседняя транзакция могла бы
изменить между проверкой и фиксацией, и тогда у записи оказалось бы два преемника.
"""

import uuid
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.area import Area
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.pagination import decode_sort_cursor, encode_sort_cursor, resolve_limit
from app.db.project_scope import require_open
from app.db.repositories import AreaRepository, EntryRepository, ProjectRepository, TaskRepository
from app.db.repositories.entries import DecisionFact
from app.domain import state as state_domain
from app.domain.areas import is_area_address, parse_area_address
from app.domain.authors import Author, AuthorKind
from app.domain.case import (
    REPLACEABLE_ENTRY_TYPES,
    SUPERSEDES_FIELD,
    EntryType,
    format_entry_ref,
    superseded_numbers,
)
from app.domain.decisions import (
    DecisionStatus,
    Review,
    ReviewOutcome,
    ReviewState,
    confirmations,
    review_of_payload,
    review_state_of,
    status_of,
    successors,
    withdrawals,
)
from app.domain.errors import (
    DecisionAlreadyConfirmedError,
    DecisionNotInForceError,
    EntryFieldsInvalidError,
    FindingNotInForceError,
    TaskFieldsInvalidError,
)
from app.domain.fields import FieldProblems
from app.domain.project_access import is_open
from app.domain.tasks import TaskField, split_decision_ref
from app.services import freeze
from app.services.accounts import active_account_of
from app.services.auth import Actor

#: Владелец дела без хода работы: проект или область (TRK#128, TRK#57). У обоих
#: одни типы записей, атрибуты, архив и знание — решения и заметки с заменой.
type CaseOwner = Project | Area


def owner_name(owner: CaseOwner) -> str:
    """Ключ проекта или адрес области: им владелец назван в ссылках и отказах."""
    return owner.address if isinstance(owner, Area) else owner.key


@dataclass(frozen=True, slots=True)
class CaseDecision:
    """Решение проекта или области со статусом, посчитанным при чтении.

    `owner` — ключ проекта или адрес области: голова ссылки (`TRK#15`, `TRK/mcp#3`).
    `superseded_by` — запись решения, которое заменило это, или `None`, пока оно
    действует. Преемник прямой, а не конец цепочки: цепочка замен видна шаг за шагом, и
    статус преемника считается тем же правилом. `withdrawn` — исход проверки человека,
    выведший решение из силы (`rejected` или `removed`), или `None`; преемника у такого
    решения нет. `review_state` и `review_entry` — проверено ли решение человеком и
    номер записи подтверждения (TRK-755).
    """

    entry: Entry
    owner: str
    supersedes: tuple[int, ...]
    superseded_by: Entry | None
    withdrawn: ReviewOutcome | None = None
    review_state: ReviewState = ReviewState.UNCONFIRMED
    review_entry: int | None = None

    @property
    def ref(self) -> str:
        return format_entry_ref(self.owner, self.entry.no)

    @property
    def status(self) -> DecisionStatus:
        if self.superseded_by is not None:
            return DecisionStatus.SUPERSEDED
        if self.withdrawn is ReviewOutcome.REJECTED:
            return DecisionStatus.REJECTED
        if self.withdrawn is ReviewOutcome.REMOVED:
            return DecisionStatus.REMOVED
        return DecisionStatus.IN_FORCE


@dataclass(frozen=True, slots=True)
class DecisionRef:
    """Решение, названное ссылкой: адрес, заголовок и статус."""

    ref: str
    title: str
    status: DecisionStatus


@dataclass(frozen=True, slots=True)
class CitedDecision(DecisionRef):
    """Решение, на которое ссылается задача, и его преемник, если оно заменено."""

    superseded_by: DecisionRef | None


@dataclass(frozen=True, slots=True)
class KnowledgeRef:
    """Действующая запись знания в чтении проекта или области: адрес и заголовок, без тела."""

    ref: str
    title: str


@dataclass(frozen=True, slots=True)
class CaseKnowledge:
    """Записи знания дела проекта или области для его чтения (решение TRK#57, раздел 6).

    `decisions` и `findings` — действующие решения и заметки в порядке номеров. `totals` —
    сколько в деле записей каждого из двух типов вместе с заменёнными: опись чтения их не
    несёт, и число говорит читателю, что они есть и сколько их. Оба типа в словаре
    всегда, ноль тоже.
    """

    decisions: list[KnowledgeRef]
    findings: list[KnowledgeRef]
    totals: dict[EntryType, int]


@dataclass(frozen=True, slots=True)
class Standing:
    """Статус записи знания в чтении дела и номер её прямого преемника.

    Преемник прямой, а не конец цепочки — как у `CaseDecision.superseded_by`: его
    статус читается тем же правилом, и цепочка видна шаг за шагом. `review_state` и
    `review_entry` — только у решения; у заметки оба `None`.
    """

    status: DecisionStatus
    superseded_by: int | None
    review_state: ReviewState | None = None
    review_entry: int | None = None


class CaseStandings:
    """Статусы записей знания одного дела проекта или области, посчитанные разом.

    Собирается из всех решений и заметок дела (`case_standings`), проверок человека и
    номеров решений, подписанных человеком, и отвечает на два вопроса чтения дела: какой
    статус у записи (`of`) и какие номера не действуют (`not_in_force`) — по ним выборка
    отбирает `in_force`, не считая статус второй раз.
    """

    __slots__ = ("_confirmed_by", "_human", "_successor_of", "_type_of", "_withdrawn")

    def __init__(
        self,
        entries: Iterable[tuple[int, EntryType, Sequence[int]]],
        reviews: Iterable[Review] = (),
        human_decisions: Iterable[int] = (),
    ) -> None:
        listed = list(entries)
        self._type_of = {no: entry_type for no, entry_type, _ in listed}
        self._successor_of = successors(listed)
        decision_nos = {
            no for no, entry_type in self._type_of.items() if entry_type is EntryType.DECISION
        }
        checked = list(reviews)
        self._withdrawn = withdrawals(checked, decision_nos)
        self._confirmed_by = confirmations(checked, decision_nos)
        self._human = frozenset(human_decisions) & decision_nos

    @property
    def not_in_force(self) -> frozenset[int]:
        """Номера записей, которые не действуют: заменённые, отклонённые и удалённые."""
        return frozenset(self._successor_of) | frozenset(self._withdrawn)

    def type_of(self, no: int) -> EntryType | None:
        """Тип записи знания с этим номером; `None` — такого решения или заметки в деле нет."""
        return self._type_of.get(no)

    def of(self, entry: Entry) -> Standing | None:
        """Статус записи дела; `None` — у записи нет статуса: она не решение и не
        заметка. Запись не из этого дела — дефект вызывающего, а не «нет статуса»."""
        if entry.type not in REPLACEABLE_ENTRY_TYPES:
            return None
        if self._type_of.get(entry.no) is not entry.type:
            raise RuntimeError(f"Entry {entry.no} is not a decision or finding of this case")
        return self.of_number(entry.no)

    def of_number(self, no: int) -> Standing:
        """Статус решения или заметки дела по номеру; номер — из `type_of`."""
        status = status_of(no, self._successor_of, self._withdrawn)
        successor = self._successor_of.get(no)
        if self._type_of.get(no) is not EntryType.DECISION:
            return Standing(status=status, superseded_by=successor)
        state, review_entry = review_state_of(no, self._confirmed_by, self._human)
        return Standing(
            status=status,
            superseded_by=successor,
            review_state=state,
            review_entry=review_entry,
        )


# --- Чтение ------------------------------------------------------------------------------


async def project_decisions(
    session: AsyncSession, project: Project, *, actor: Actor
) -> list[CaseDecision]:
    """Все решения проекта в порядке номеров, каждое со статусом и преемником."""
    found = await _decisions_of(session, {project.key: project})
    return sorted(found.get(project.key, {}).values(), key=lambda item: item.entry.no)


async def case_knowledge(session: AsyncSession, owner: CaseOwner, *, actor: Actor) -> CaseKnowledge:
    """Действующие решения и заметки проекта или области ссылкой и заголовком и число
    записей знания по типам — для чтения (`get_project`), одним запросом без тел.

    Действующие решения — то, что по договору задаёт работу (TRK#185; у области
    — работу в ней, TRK#57, раздел 5); заметки стоят рядом в той же форме. Статус — тем же
    `CaseStandings`, что у чтения дела.
    """
    rows = await _replaceables(session, owner)
    standings = await _standings(session, owner, rows)
    prefix = owner_name(owner)
    listed: dict[EntryType, list[KnowledgeRef]] = {kind: [] for kind in _KNOWLEDGE_TYPES}
    for no, entry_type, title, _ in rows:
        if standings.of_number(no).status is DecisionStatus.IN_FORCE:
            listed[entry_type].append(KnowledgeRef(ref=format_entry_ref(prefix, no), title=title))
    return CaseKnowledge(
        decisions=listed[EntryType.DECISION],
        findings=listed[EntryType.FINDING],
        totals={kind: sum(1 for row in rows if row[1] is kind) for kind in _KNOWLEDGE_TYPES},
    )


async def project_decisions_after_card(
    session: AsyncSession, task: Task, *, actor: Actor
) -> list[str]:
    """Действующие решения проекта задачи, подшитые после последней правки её разделов, —
    ссылками `TRK#7` для блока `state` (TRK#156).

    Статус считает тот же `CaseStandings`, что у чтения проекта: заменённое, отклонённое и
    удалённое решение в поле не входит. Решения областей — дела других сущностей, их здесь
    нет (TRK-643).
    """
    entries = EntryRepository(session)
    project_key = task.key.rsplit("-", 1)[0]
    standings = _build_standings(
        await entries.project_replaceables(task.project_id),
        await entries.project_review_facts(task.project_id),
    )
    return state_domain.project_decisions_after_card(
        project_key,
        await entries.project_decision_seqs(task.project_id),
        cut_seq=await entries.card_edit_seq(task.id),
        superseded=standings.not_in_force,
    )


async def case_standings(session: AsyncSession, owner: CaseOwner) -> CaseStandings:
    """Статусы всех решений и заметок дела проекта или области: для чтения дела и отбора
    `in_force`."""
    return await _standings(session, owner, await _replaceables(session, owner))


async def standing_of(session: AsyncSession, owner: CaseOwner, entry: Entry) -> Standing | None:
    """Статус одной записи дела проекта или области; `None` — у записи нет статуса: она не
    решение и не заметка. Чтение одной записи по номеру (`.../entries/{no}` в REST)."""
    if entry.type not in REPLACEABLE_ENTRY_TYPES:
        return None
    return (await case_standings(session, owner)).of(entry)


async def citing_task_counts(
    session: AsyncSession, decisions: Sequence[CaseDecision], *, actor: Actor
) -> dict[str, int]:
    """Сколько задач ссылается на каждое решение: ссылка → число, нулей в словаре нет."""
    return await TaskRepository(session).decision_counts([item.ref for item in decisions])


async def cited_decisions(
    session: AsyncSession, refs: Sequence[str], *, actor: Actor
) -> list[CitedDecision]:
    """Решения проектов и областей, на которые ссылается задача, в порядке поля — со
    статусом и преемником.

    Ссылка в поле задачи проверена при постановке, а записи дела не удаляются, поэтому
    ненайденное решение — испорченные данные, а не рабочее состояние: оно не замалчивается.
    """
    if not refs:
        return []
    owners = await _owners(session, {split_decision_ref(ref)[0] for ref in refs})
    found = await _decisions_of(session, owners)
    cited: list[CitedDecision] = []
    for ref in refs:
        key, no = split_decision_ref(ref)
        owner = owners[key]
        # Решение закрытого агенту проекта задача цитирует (человек или другой агент поставил
        # ссылку), но его адрес и название вызову не положены: из карточки оно уходит (TRK-753).
        if not is_open(
            actor.project_access, (owner if isinstance(owner, Project) else owner.project).id
        ):
            continue
        decision = found.get(key, {}).get(no)
        if decision is None:
            raise RuntimeError(f"Task cites {ref}, which is not a decision of a project or area")
        successor = None
        if decision.superseded_by is not None:
            next_decision = found[key][decision.superseded_by.no]
            successor = DecisionRef(
                ref=next_decision.ref,
                title=next_decision.entry.title,
                status=next_decision.status,
            )
        cited.append(
            CitedDecision(
                ref=decision.ref,
                title=decision.entry.title,
                status=decision.status,
                superseded_by=successor,
            )
        )
    return cited


async def is_decision(session: AsyncSession, ref: str) -> bool:
    """Есть ли по канонической ссылке `TRK#15` или `TRK/mcp#3` запись `decision` дела
    проекта или области — любого статуса: отбор `decision:` ищет и по заменённому решению
    (TRK#166)."""
    key, no = split_decision_ref(ref)
    owner = (await _owners(session, {key})).get(key)
    if owner is None:
        return False
    entry = await _entry_of(session, owner, no)
    return entry is not None and entry.type is EntryType.DECISION


# --- Список решений поперёк проектов и областей ------------------------------------------


@dataclass(frozen=True, slots=True)
class ListedDecision:
    """Строка списка решений: решение дела проекта или области со статусом и проверкой.

    `ref` — адрес решения (`TRK#15`, `TRK/mcp#3`), `area` — адрес области или `None` у
    решения проекта. `supersedes` и `superseded_by` — ссылки в деле того же владельца;
    `refs` — ссылки самого решения (откуда оно). `tasks` — сколько задач на него ссылается.
    """

    ref: str
    area: str | None
    title: str
    author: Author
    created_at: datetime
    status: DecisionStatus
    review_state: ReviewState
    review_entry: int | None
    supersedes: list[str]
    superseded_by: str | None
    refs: list[str]
    tasks: int


@dataclass(frozen=True, slots=True)
class DecisionListing:
    """Страница списка решений и число непроверенных действующих решений в той же области
    видимости (проект или вся установка), не зависящее от отборов."""

    items: list[ListedDecision]
    next_cursor: str | None
    unconfirmed: int


async def list_decisions(
    session: AsyncSession,
    *,
    actor: Actor,
    project: Project | None = None,
    status: DecisionStatus | None = None,
    review_state: ReviewState | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> DecisionListing:
    """Решения проекта вместе с его неархивными областями или всех неархивных проектов
    установки, открытых доступу вызова; старые первыми (TRK-755).

    Статус и состояние проверки считаются при чтении теми же правилами, что в деле:
    `CaseStandings` на владельца. Читаются записи без тел — одним запросом на всю область
    видимости. Страница режется по `seq` решения; число `unconfirmed` считается по всей
    области видимости, а не по отбору.
    """
    shown = await _decision_rows(
        session, actor=actor, project_id=None if project is None else project.id
    )
    unconfirmed = sum(
        1
        for row in shown
        if row.standing.status is DecisionStatus.IN_FORCE
        and row.standing.review_state is ReviewState.UNCONFIRMED
    )
    chosen = [
        row
        for row in shown
        if (status is None or row.standing.status is status)
        and (review_state is None or row.standing.review_state is review_state)
    ]
    size = resolve_limit(limit)
    if cursor is not None:
        (after_seq,), _ = decode_sort_cursor(cursor, arity=1)
        chosen = [row for row in chosen if row.fact.seq > after_seq]
    page = chosen[:size]
    next_cursor = (
        encode_sort_cursor([page[-1].fact.seq], page[-1].fact.id) if len(chosen) > size else None
    )
    refs = [format_entry_ref(row.fact.owner, row.fact.no) for row in page]
    counts = await TaskRepository(session).decision_counts(refs)
    items = [
        ListedDecision(
            ref=ref,
            area=row.fact.area,
            title=row.fact.title,
            author=row.fact.author,
            created_at=row.fact.created_at,
            status=row.standing.status,
            review_state=row.standing.review_state or ReviewState.UNCONFIRMED,
            review_entry=row.standing.review_entry,
            supersedes=[
                format_entry_ref(row.fact.owner, number)
                for number in superseded_numbers(row.fact.payload)
            ],
            superseded_by=(
                None
                if row.standing.superseded_by is None
                else format_entry_ref(row.fact.owner, row.standing.superseded_by)
            ),
            refs=row.fact.refs,
            tasks=counts.get(ref, 0),
        )
        for ref, row in zip(refs, page, strict=True)
    ]
    return DecisionListing(items=items, next_cursor=next_cursor, unconfirmed=unconfirmed)


async def count_unconfirmed(
    session: AsyncSession,
    *,
    actor: Actor,
    project_id: uuid.UUID | None = None,
    area: Area | None = None,
) -> int:
    """Сколько действующих решений человек ещё не проверял: область — её решения,
    проект (`project_id`) — его и его неархивных областей, без названия — всей установки (неархивные
    проекты, открытые доступу вызова). Число карточек проекта и области, `bootstrap` и
    поля `unconfirmed` списка решений — одно и то же правило."""
    rows = await _decision_rows(
        session, actor=actor, project_id=area.project_id if area is not None else project_id
    )
    return sum(
        1
        for row in rows
        if row.standing.status is DecisionStatus.IN_FORCE
        and row.standing.review_state is ReviewState.UNCONFIRMED
        and (area is None or row.fact.owner_id == area.id)
    )


@dataclass(frozen=True, slots=True)
class _DecisionRow:
    fact: DecisionFact
    standing: Standing


async def _decision_rows(
    session: AsyncSession, *, actor: Actor, project_id: uuid.UUID | None
) -> list[_DecisionRow]:
    """Все решения области видимости со статусом, по `seq`."""
    facts = await EntryRepository(session).decision_facts(
        project_id=project_id, access=actor.project_access
    )
    by_owner: dict[uuid.UUID, list[DecisionFact]] = defaultdict(list)
    for fact in facts:
        by_owner[fact.owner_id].append(fact)
    rows: list[_DecisionRow] = []
    for group in by_owner.values():
        decisions = [fact for fact in group if fact.type is EntryType.DECISION]
        reviews = [
            review
            for fact in group
            if fact.type is EntryType.DECISION_REVIEW
            and (review := review_of_payload(fact.no, fact.payload)) is not None
        ]
        standings = CaseStandings(
            ((fact.no, fact.type, superseded_numbers(fact.payload)) for fact in decisions),
            reviews,
            [fact.no for fact in decisions if fact.author.kind is AuthorKind.HUMAN],
        )
        rows.extend(_DecisionRow(fact, standings.of_number(fact.no)) for fact in decisions)
    return sorted(rows, key=lambda row: row.fact.seq)


# --- Проверка решения человеком ----------------------------------------------------------


async def review_decision(
    session: AsyncSession,
    owner: CaseOwner,
    no: int,
    *,
    actor: Actor,
    outcome: ReviewOutcome,
    reason: str | None = None,
) -> Entry:
    """Человек подтверждает, отклоняет или удаляет действующее решение проекта или
    области — подшивается запись `decision_review` (TRK-755).

    Порядок отказов: не человек с учётной записью — `permission_denied`
    (`details.reason: account_required`, как при выпуске ключа); архивный проект или
    область — `project_archived`, `area_archived`; решения нет или оно не действует
    (заменено, отклонено, удалено) — `decision_not_in_force`, у заменённого с
    преемником; повторное `confirmed` — `decision_already_confirmed`. Состояние читается
    под очередью изменений, как у замены: две проверки одного решения не разойдутся.
    «Удалить» — отмена без замены, запись остаётся в деле: записи неизменяемы.
    """
    from app.services import case as case_service  # дело импортирует этот модуль

    if await active_account_of(session, actor) is None:
        raise PermissionDeniedError(
            message="Only a person signed in with an account can review decisions",
            details={"action": "decision.review", "reason": "account_required"},
        )
    if isinstance(owner, Area):
        await freeze.lock_unfrozen(session, area=owner)
    else:
        await freeze.lock_unfrozen(session, project=owner)
    standings = await case_standings(session, owner)
    prefix = owner_name(owner)
    ref = format_entry_ref(prefix, no)
    if standings.type_of(no) is not EntryType.DECISION:
        raise DecisionNotInForceError(
            details={"decisions": [{"ref": ref, "superseded_by": None}], "key": prefix}
        )
    standing = standings.of_number(no)
    if standing.status is not DecisionStatus.IN_FORCE:
        successor = (
            None
            if standing.superseded_by is None
            else format_entry_ref(prefix, standing.superseded_by)
        )
        raise DecisionNotInForceError(
            details=_not_in_force_details(
                EntryType.DECISION, [(ref, successor, standing.status)], key=prefix
            )
        )
    if outcome is ReviewOutcome.CONFIRMED and standing.review_state is ReviewState.CONFIRMED:
        raise DecisionAlreadyConfirmedError(
            details={"ref": ref, "review_entry": standing.review_entry, "key": prefix}
        )
    return await case_service.record_decision_review(
        session, owner, actor=actor, no=no, outcome=outcome.value, reason=(reason or "").strip()
    )


# --- Проверки записи ---------------------------------------------------------------------


async def check_cited(
    session: AsyncSession,
    *,
    before: Sequence[str],
    after: Sequence[str],
    key: str | None = None,
) -> None:
    """Новые ссылки задачи ведут на действующие решения проектов и областей (TRK#108;
    TRK#57, раздел 5).

    Проверяются только ссылки, которых в поле ещё не было. Ссылка, которая уже стоит,
    остаётся и после замены решения: задача делалась по нему, и это её история.

    Отказы двух уровней. Ссылка не на решение — нет проекта или области, нет записи,
    запись не `decision` — это `task_fields_invalid`, все замечания разом. Ссылка на
    заменённое решение — `decision_not_in_force` с преемником: форма верна, но решение уже
    не в силе.
    """
    added = [ref for ref in after if ref not in set(before)]
    if not added:
        return
    owners = await _owners(session, {split_decision_ref(ref)[0] for ref in added})
    found = await _decisions_of(session, owners)
    problems = FieldProblems()
    superseded: list[CaseDecision] = []
    for ref in added:
        owner_key, no = split_decision_ref(ref)
        owner = owners.get(owner_key)
        if owner is None:
            reason = await _missing_owner_reason(session, owner_key)
            problems.add(TaskField.DECISIONS.value, reason, ref=ref)
            continue
        # Ссылка на решение закрытого агенту проекта — запись в закрытый проект (TRK~28#6).
        require_open(session, owner if isinstance(owner, Project) else owner.project)
        decision = found.get(owner_key, {}).get(no)
        if decision is not None:
            if decision.status is not DecisionStatus.IN_FORCE:
                superseded.append(decision)
            continue
        await _not_of_type(
            session,
            owner,
            no,
            expected=EntryType.DECISION,
            ref=ref,
            field=TaskField.DECISIONS.value,
            problems=problems,
        )
    problems.raise_as(TaskFieldsInvalidError)
    if superseded:
        raise DecisionNotInForceError(
            details=_not_in_force_details(
                EntryType.DECISION,
                [(item.ref, _successor_ref(item), item.status) for item in superseded],
                key=key,
            )
        )


async def check_superseded(
    session: AsyncSession, owner: CaseOwner, entry_type: EntryType, numbers: Sequence[int]
) -> None:
    """Записи, которые заменяет новая запись знания проекта или области, есть в его деле,
    того же типа и действуют (TRK#91; TRK#48, раздел 2; TRK#57, раздел 5).

    Номер не из этого дела и запись другого типа — `entry_fields_invalid` полем
    `supersedes` (`unknown_entry`, `not_a_decision`, `not_a_finding`); уже заменённая —
    `decision_not_in_force` или `finding_not_in_force` с преемником: у записи не бывает
    двух преемников, и цепочка замен остаётся линейной.
    """
    if not numbers:
        return
    standings = await case_standings(session, owner)
    prefix = owner_name(owner)
    problems = FieldProblems()
    superseded: list[tuple[str, str | None, DecisionStatus]] = []
    for no in numbers:
        ref = format_entry_ref(prefix, no)
        if standings.type_of(no) is not entry_type:
            await _not_of_type(
                session,
                owner,
                no,
                expected=entry_type,
                ref=ref,
                field=SUPERSEDES_FIELD,
                problems=problems,
            )
            continue
        standing = standings.of_number(no)
        if standing.status is not DecisionStatus.IN_FORCE:
            successor = (
                None
                if standing.superseded_by is None
                else format_entry_ref(prefix, standing.superseded_by)
            )
            superseded.append((ref, successor, standing.status))
    problems.raise_as(EntryFieldsInvalidError, key=prefix)
    if superseded:
        error, _ = _NOT_IN_FORCE[entry_type]
        raise error(details=_not_in_force_details(entry_type, superseded, key=prefix))


# --- Внутреннее --------------------------------------------------------------------------

#: Типы записей знания по имени — порядок ключей в `CaseKnowledge.totals`.
_KNOWLEDGE_TYPES = tuple(sorted(REPLACEABLE_ENTRY_TYPES))


def _build_standings(
    rows: Iterable[tuple[int, EntryType, str, dict[str, Any]]],
    facts: Iterable[tuple[int, EntryType, dict[str, Any]]],
) -> CaseStandings:
    """`CaseStandings` из строк знания дела и фактов проверки (`*_review_facts`)."""
    reviews: list[Review] = []
    human: list[int] = []
    for no, entry_type, payload in facts:
        if entry_type is EntryType.DECISION_REVIEW:
            review = review_of_payload(no, payload)
            if review is not None:
                reviews.append(review)
        else:
            human.append(no)
    return CaseStandings(
        ((no, entry_type, superseded_numbers(payload)) for no, entry_type, _, payload in rows),
        reviews,
        human,
    )


async def _standings(
    session: AsyncSession,
    owner: CaseOwner,
    rows: Iterable[tuple[int, EntryType, str, dict[str, Any]]],
) -> CaseStandings:
    entries = EntryRepository(session)
    facts = await (
        entries.area_review_facts(owner.id)
        if isinstance(owner, Area)
        else entries.project_review_facts(owner.id)
    )
    return _build_standings(rows, facts)


async def _replaceables(
    session: AsyncSession, owner: CaseOwner
) -> list[tuple[int, EntryType, str, dict[str, Any]]]:
    """Решения и заметки дела владельца без тел: выборка по `area_id` или `project_id`."""
    entries = EntryRepository(session)
    if isinstance(owner, Area):
        return await entries.area_replaceables(owner.id)
    return await entries.project_replaceables(owner.id)


async def _entry_of(session: AsyncSession, owner: CaseOwner, no: int) -> Entry | None:
    """Запись дела владельца по номеру."""
    entries = EntryRepository(session)
    if isinstance(owner, Area):
        return await entries.get_by_area_no(owner.id, no)
    return await entries.get_by_project_no(owner.id, no)


async def _owners(session: AsyncSession, keys: Collection[str]) -> dict[str, CaseOwner]:
    """Владельцы решений по головам ссылок: ключ проекта → проект, адрес → область.

    Проекты — одним запросом; области — по запросу на адрес: задача называет решения
    немногих областей. Ненайденного владельца в ответе нет — почему, скажет
    `_missing_owner_reason`.
    """
    project_keys = {key for key in keys if not is_area_address(key)}
    found: dict[str, CaseOwner] = dict(await ProjectRepository(session).get_by_keys(project_keys))
    areas = AreaRepository(session)
    for key in sorted(set(keys) - project_keys):
        address = parse_area_address(key)
        area = await areas.get_by_address(address.project_key, address.key)
        if area is not None:
            found[key] = area
    return found


async def _missing_owner_reason(session: AsyncSession, key: str) -> str:
    """Почему владельца ссылки нет: нет проекта (`unknown_project`) или в проекте нет такой
    области (`unknown_area`) — те же причины, что у ссылок записи в `refs`."""
    if is_area_address(key):
        project_key = parse_area_address(key).project_key
        if await ProjectRepository(session).get_by_key(project_key) is not None:
            return "unknown_area"
    return "unknown_project"


async def _decisions_of(
    session: AsyncSession, owners: Mapping[str, CaseOwner]
) -> dict[str, dict[int, CaseDecision]]:
    """Решения названных владельцев: ключ или адрес → номер → решение со статусом."""
    projects = {owner.id: key for key, owner in owners.items() if isinstance(owner, Project)}
    areas = {owner.id: key for key, owner in owners.items() if isinstance(owner, Area)}
    entries = EntryRepository(session)
    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entry in await entries.project_decisions(list(projects)):
        assert entry.project_id is not None
        grouped[projects[entry.project_id]].append(entry)
    for entry in await entries.area_decisions(list(areas)):
        assert entry.area_id is not None
        grouped[areas[entry.area_id]].append(entry)
    reviews: dict[str, list[Review]] = defaultdict(list)
    for review_entry in await entries.project_decision_reviews(list(projects)):
        assert review_entry.project_id is not None
        found = review_of_payload(review_entry.no, review_entry.payload)
        if found is not None:
            reviews[projects[review_entry.project_id]].append(found)
    for review_entry in await entries.area_decision_reviews(list(areas)):
        assert review_entry.area_id is not None
        found = review_of_payload(review_entry.no, review_entry.payload)
        if found is not None:
            reviews[areas[review_entry.area_id]].append(found)
    return {key: _with_status(key, group, reviews.get(key, ())) for key, group in grouped.items()}


def _with_status(
    owner: str, entries: Iterable[Entry], reviews: Iterable[Review] = ()
) -> dict[int, CaseDecision]:
    by_no = {entry.no: entry for entry in entries}
    replaced = {no: tuple(superseded_numbers(entry.payload)) for no, entry in by_no.items()}
    successor_of = successors((no, by_no[no].type, numbers) for no, numbers in replaced.items())
    withdrawn = withdrawals(reviews, by_no.keys())
    confirmed_by = confirmations(reviews, by_no.keys())
    human = {no for no, entry in by_no.items() if entry.created_by_kind is AuthorKind.HUMAN}
    result: dict[int, CaseDecision] = {}
    for no, entry in by_no.items():
        state, review_entry = review_state_of(no, confirmed_by, human)
        result[no] = CaseDecision(
            entry=entry,
            owner=owner,
            supersedes=replaced[no],
            superseded_by=by_no[successor_of[no]] if no in successor_of else None,
            withdrawn=withdrawn.get(no),
            review_state=state,
            review_entry=review_entry,
        )
    return result


async def _not_of_type(
    session: AsyncSession,
    owner: CaseOwner,
    no: int,
    *,
    expected: EntryType,
    ref: str,
    field: str,
    problems: FieldProblems,
) -> None:
    """Почему адрес — не запись нужного типа: записи нет (`unknown_entry`) или она другого
    типа (`not_a_decision`, `not_a_finding` — по ожидаемому)."""
    entry = await _entry_of(session, owner, no)
    if entry is None:
        problems.add(field, "unknown_entry", ref=ref)
    else:
        problems.add(
            field,
            f"not_a_{expected.value}",
            ref=ref,
            got=entry.type.value,
            expected=expected.value,
        )


#: Отказ замены заменённой записи и ключ его подробностей — по типу записи: код называет
#: сущность (решение задачи TRK-656, запись `decision` в её деле).
_NOT_IN_FORCE: dict[
    EntryType, tuple[type[DecisionNotInForceError] | type[FindingNotInForceError], str]
] = {
    EntryType.DECISION: (DecisionNotInForceError, "decisions"),
    EntryType.FINDING: (FindingNotInForceError, "findings"),
}


def _successor_ref(decision: CaseDecision) -> str | None:
    if decision.superseded_by is None:
        return None
    return format_entry_ref(decision.owner, decision.superseded_by.no)


def _not_in_force_details(
    entry_type: EntryType,
    superseded: Sequence[tuple[str, str | None, DecisionStatus]],
    *,
    key: str | None,
) -> dict[str, Any]:
    """Подробности `decision_not_in_force` и `finding_not_in_force`: каждая названная
    запись и её преемник — в `decisions` или `findings`. У отклонённого и удалённого
    человеком решения преемника нет (`superseded_by: null`), и отказ называет его
    статус в `status`; у заменённой записи ключа `status` нет — форма прежняя."""
    _, field = _NOT_IN_FORCE[entry_type]
    details: dict[str, Any] = {
        field: [
            {"ref": ref, "superseded_by": successor}
            | ({} if status is DecisionStatus.SUPERSEDED else {"status": status.value})
            for ref, successor, status in superseded
        ]
    }
    if key is not None:
        details["key"] = key
    return details
