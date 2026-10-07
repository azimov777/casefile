"""Записи знания дела проекта и дела области — решения и заметки: статус при чтении,
замена, ссылки задач на решения.

Решение — запись `decision` дела проекта (`CONCEPT.md`, 3.2) или дела области, заметка —
запись `finding` того же дела; замена у них одна (решение TRK#48, раздел 2) и одна у обоих
владельцев (решение TRK#57, раздел 5). Отдельной таблицы и хранимого статуса нет: запись
действует, пока ни одна более поздняя запись того же типа и того же дела не назвала её в
`supersedes`, и статус считается здесь при каждом чтении, как признак `blocked` у задачи.
Замена поэтому не пишет ни строчки ни в дело заменённой, ни в дела задач, которые на
решение ссылаются, и не будит их (`CONCEPT.md`, 4.3).

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

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import AreaRepository, EntryRepository, ProjectRepository, TaskRepository
from app.domain import state as state_domain
from app.domain.areas import is_area_address, parse_area_address
from app.domain.case import (
    REPLACEABLE_ENTRY_TYPES,
    SUPERSEDES_FIELD,
    EntryType,
    format_entry_ref,
    superseded_numbers,
)
from app.domain.decisions import DecisionStatus, status_of, successors
from app.domain.errors import (
    DecisionNotInForceError,
    EntryFieldsInvalidError,
    FindingNotInForceError,
    TaskFieldsInvalidError,
)
from app.domain.fields import FieldProblems
from app.domain.tasks import TaskField, split_decision_ref
from app.services.auth import Actor

#: Владелец дела без хода работы: проект или область (`CONCEPT.md`, 3.4 и 3.7). У обоих
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
    статус преемника считается тем же правилом.
    """

    entry: Entry
    owner: str
    supersedes: tuple[int, ...]
    superseded_by: Entry | None

    @property
    def ref(self) -> str:
        return format_entry_ref(self.owner, self.entry.no)

    @property
    def status(self) -> DecisionStatus:
        return DecisionStatus.IN_FORCE if self.superseded_by is None else DecisionStatus.SUPERSEDED


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
    статус читается тем же правилом, и цепочка видна шаг за шагом.
    """

    status: DecisionStatus
    superseded_by: int | None


class CaseStandings:
    """Статусы записей знания одного дела проекта или области, посчитанные разом.

    Собирается из всех решений и заметок дела (`case_standings`) и отвечает на два
    вопроса чтения дела: какой статус у записи (`of`) и какие номера заменены
    (`superseded`) — по ним выборка отбирает `in_force`, не считая статус второй раз.
    """

    __slots__ = ("_successor_of", "_type_of")

    def __init__(self, entries: Iterable[tuple[int, EntryType, Sequence[int]]]) -> None:
        listed = list(entries)
        self._type_of = {no: entry_type for no, entry_type, _ in listed}
        self._successor_of = successors(listed)

    @property
    def superseded(self) -> frozenset[int]:
        """Номера заменённых записей дела."""
        return frozenset(self._successor_of)

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
        return Standing(
            status=status_of(no, self._successor_of), superseded_by=self._successor_of.get(no)
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

    Действующие решения — то, что по договору задаёт работу (`CONCEPT.md`, 5.2; у области
    — работу в ней, TRK#57, раздел 5); заметки стоят рядом в той же форме. Статус — тем же
    `CaseStandings`, что у чтения дела.
    """
    rows = await _replaceables(session, owner)
    standings = _standings(rows)
    prefix = owner_name(owner)
    listed: dict[EntryType, list[KnowledgeRef]] = {kind: [] for kind in _KNOWLEDGE_TYPES}
    for no, entry_type, title, _ in rows:
        if standings.of_number(no).superseded_by is None:
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
    ссылками `TRK#7` для блока `state` (`CONCEPT.md`, 4.2).

    Статус считает тот же `CaseStandings`, что у чтения проекта: заменённое решение в поле
    не входит. Решения областей — дела других сущностей, их здесь нет (TRK-643).
    """
    entries = EntryRepository(session)
    project_key = task.key.rsplit("-", 1)[0]
    standings = _standings(await entries.project_replaceables(task.project_id))
    return state_domain.project_decisions_after_card(
        project_key,
        await entries.project_decision_seqs(task.project_id),
        cut_seq=await entries.card_edit_seq(task.id),
        superseded=standings.superseded,
    )


async def case_standings(session: AsyncSession, owner: CaseOwner) -> CaseStandings:
    """Статусы всех решений и заметок дела проекта или области: для чтения дела и отбора
    `in_force`."""
    return _standings(await _replaceables(session, owner))


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
    (`CONCEPT.md`, 4.4)."""
    key, no = split_decision_ref(ref)
    owner = (await _owners(session, {key})).get(key)
    if owner is None:
        return False
    entry = await _entry_of(session, owner, no)
    return entry is not None and entry.type is EntryType.DECISION


# --- Проверки записи ---------------------------------------------------------------------


async def check_cited(
    session: AsyncSession,
    *,
    before: Sequence[str],
    after: Sequence[str],
    key: str | None = None,
) -> None:
    """Новые ссылки задачи ведут на действующие решения проектов и областей (`CONCEPT.md`,
    3.3; TRK#57, раздел 5).

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
        decision = found.get(owner_key, {}).get(no)
        if decision is not None:
            if decision.superseded_by is not None:
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
                [(item.ref, _successor_ref(item)) for item in superseded],
                key=key,
            )
        )


async def check_superseded(
    session: AsyncSession, owner: CaseOwner, entry_type: EntryType, numbers: Sequence[int]
) -> None:
    """Записи, которые заменяет новая запись знания проекта или области, есть в его деле,
    того же типа и действуют (`CONCEPT.md`, 3.2; TRK#48, раздел 2; TRK#57, раздел 5).

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
    superseded: list[tuple[str, str | None]] = []
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
        if standing.superseded_by is not None:
            superseded.append((ref, format_entry_ref(prefix, standing.superseded_by)))
    problems.raise_as(EntryFieldsInvalidError, key=prefix)
    if superseded:
        error, _ = _NOT_IN_FORCE[entry_type]
        raise error(details=_not_in_force_details(entry_type, superseded, key=prefix))


# --- Внутреннее --------------------------------------------------------------------------

#: Типы записей знания по имени — порядок ключей в `CaseKnowledge.totals`.
_KNOWLEDGE_TYPES = tuple(sorted(REPLACEABLE_ENTRY_TYPES))


def _standings(rows: Iterable[tuple[int, EntryType, str, dict[str, Any]]]) -> CaseStandings:
    return CaseStandings(
        (no, entry_type, superseded_numbers(payload)) for no, entry_type, _, payload in rows
    )


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
    return {key: _with_status(key, group) for key, group in grouped.items()}


def _with_status(owner: str, entries: Iterable[Entry]) -> dict[int, CaseDecision]:
    by_no = {entry.no: entry for entry in entries}
    replaced = {no: tuple(superseded_numbers(entry.payload)) for no, entry in by_no.items()}
    successor_of = successors((no, by_no[no].type, numbers) for no, numbers in replaced.items())
    return {
        no: CaseDecision(
            entry=entry,
            owner=owner,
            supersedes=replaced[no],
            superseded_by=(
                None
                if status_of(no, successor_of) is DecisionStatus.IN_FORCE
                else by_no[successor_of[no]]
            ),
        )
        for no, entry in by_no.items()
    }


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
    entry_type: EntryType, superseded: Sequence[tuple[str, str | None]], *, key: str | None
) -> dict[str, Any]:
    """Подробности `decision_not_in_force` и `finding_not_in_force`: каждая названная
    запись и её преемник — в `decisions` или `findings`."""
    _, field = _NOT_IN_FORCE[entry_type]
    details: dict[str, Any] = {
        field: [{"ref": ref, "superseded_by": successor} for ref, successor in superseded]
    }
    if key is not None:
        details["key"] = key
    return details
