"""Записи знания дела проекта — решения и заметки: статус при чтении, замена, ссылки задач
на решения.

Решение проекта — запись `decision` дела проекта (`CONCEPT.md`, 3.2), заметка — запись
`finding` того же дела; замена у них одна (решение TRK#48, раздел 2). Отдельной таблицы и
хранимого статуса нет: запись действует, пока ни одна более поздняя запись того же типа и
того же дела не назвала её в `supersedes`, и статус считается здесь при каждом чтении,
как признак `blocked` у задачи. Замена поэтому не пишет ни строчки ни в дело заменённой,
ни в дела задач, которые на решение ссылаются, и не будит их (`CONCEPT.md`, 4.3).

## Одно правило, несколько потребителей

Преемника считает одна функция домена — `successors` (`app/domain/decisions.py`):

- пакет задачи (`get_task`): решения, на которые ссылается задача, со статусом и
  преемником — `cited_decisions`;
- чтение проекта: все решения проекта со статусом — `project_decisions`;
- чтение дела проекта: статус и преемник у каждой записи знания и отбор `in_force` —
  `case_standings`;
- проверки записи: новая ссылка задачи (`check_cited`) называет только действующее
  решение, замена (`check_superseded`) — только действующую запись своего типа.

Все читают записи знания дела целиком: статус записи зависит от всех более поздних, и
выборка «только названных» дала бы неверный ответ.

## Проверки — под очередью изменений

`check_cited` и `check_superseded` зовут сценарии, которые уже заняли очередь изменений
(`app/db/locks.py`): «запись ещё действует» — факт, который соседняя транзакция могла бы
изменить между проверкой и фиксацией, и тогда у записи оказалось бы два преемника.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.repositories import EntryRepository, ProjectRepository, TaskRepository
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


@dataclass(frozen=True, slots=True)
class ProjectDecision:
    """Решение проекта со статусом, посчитанным при чтении.

    `superseded_by` — запись решения, которое заменило это, или `None`, пока оно
    действует. Преемник прямой, а не конец цепочки: цепочка замен видна шаг за шагом, и
    статус преемника считается тем же правилом.
    """

    entry: Entry
    project_key: str
    supersedes: tuple[int, ...]
    superseded_by: Entry | None

    @property
    def ref(self) -> str:
        return format_entry_ref(self.project_key, self.entry.no)

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
class Standing:
    """Статус записи знания в чтении дела проекта и номер её прямого преемника.

    Преемник прямой, а не конец цепочки — как у `ProjectDecision.superseded_by`: его
    статус читается тем же правилом, и цепочка видна шаг за шагом.
    """

    status: DecisionStatus
    superseded_by: int | None


class CaseStandings:
    """Статусы записей знания одного дела проекта, посчитанные разом.

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
        """Статус записи дела проекта; `None` — у записи нет статуса: она не решение и не
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
) -> list[ProjectDecision]:
    """Все решения проекта в порядке номеров, каждое со статусом и преемником."""
    found = await _decisions_of(session, {project.id: project.key})
    return sorted(found.get(project.key, {}).values(), key=lambda item: item.entry.no)


async def in_force(
    session: AsyncSession, project: Project, *, actor: Actor
) -> list[ProjectDecision]:
    """Действующие решения проекта: то, что по договору задаёт работу (`CONCEPT.md`, 5.2)."""
    return [
        decision
        for decision in await project_decisions(session, project, actor=actor)
        if decision.superseded_by is None
    ]


async def case_standings(session: AsyncSession, project: Project) -> CaseStandings:
    """Статусы всех решений и заметок дела проекта: для чтения дела и отбора `in_force`."""
    rows = await EntryRepository(session).project_replaceables(project.id)
    return CaseStandings(
        (no, entry_type, superseded_numbers(payload)) for no, entry_type, payload in rows
    )


async def standing_of(session: AsyncSession, project: Project, entry: Entry) -> Standing | None:
    """Статус одной записи дела проекта; `None` — у записи нет статуса: она не решение и
    не заметка. Чтение одной записи по номеру (`GET /projects/{key}/entries/{no}`)."""
    if entry.type not in REPLACEABLE_ENTRY_TYPES:
        return None
    return (await case_standings(session, project)).of(entry)


async def citing_task_counts(
    session: AsyncSession, decisions: Sequence[ProjectDecision], *, actor: Actor
) -> dict[str, int]:
    """Сколько задач ссылается на каждое решение: ссылка → число, нулей в словаре нет."""
    return await TaskRepository(session).decision_counts([item.ref for item in decisions])


async def cited_decisions(
    session: AsyncSession, refs: Sequence[str], *, actor: Actor
) -> list[CitedDecision]:
    """Решения, на которые ссылается задача, в порядке поля — со статусом и преемником.

    Ссылка в поле задачи проверена при постановке, а записи дела не удаляются, поэтому
    ненайденное решение — испорченные данные, а не рабочее состояние: оно не замалчивается.
    """
    if not refs:
        return []
    keys = {split_decision_ref(ref)[0] for ref in refs}
    projects = await ProjectRepository(session).get_by_keys(keys)
    found = await _decisions_of(session, {project.id: key for key, project in projects.items()})
    cited: list[CitedDecision] = []
    for ref in refs:
        key, no = split_decision_ref(ref)
        decision = found.get(key, {}).get(no)
        if decision is None:
            raise RuntimeError(f"Task cites {ref}, which is not a decision of a project case")
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
    """Есть ли по канонической ссылке `TRK#15` запись `decision` дела проекта — любого
    статуса: отбор `decision:` ищет и по заменённому решению (`CONCEPT.md`, 4.4)."""
    key, no = split_decision_ref(ref)
    project = await ProjectRepository(session).get_by_key(key)
    if project is None:
        return False
    entry = await EntryRepository(session).get_by_project_no(project.id, no)
    return entry is not None and entry.type is EntryType.DECISION


# --- Проверки записи ---------------------------------------------------------------------


async def check_cited(
    session: AsyncSession,
    *,
    before: Sequence[str],
    after: Sequence[str],
    key: str | None = None,
) -> None:
    """Новые ссылки задачи ведут на действующие решения проектов (`CONCEPT.md`, 3.3).

    Проверяются только ссылки, которых в поле ещё не было. Ссылка, которая уже стоит,
    остаётся и после замены решения: задача делалась по нему, и это её история.

    Отказы двух уровней. Ссылка не на решение — нет проекта, нет записи, запись не
    `decision` — это `task_fields_invalid`, все замечания разом. Ссылка на заменённое
    решение — `decision_not_in_force` с преемником: форма верна, но решение уже не в силе.
    """
    added = [ref for ref in after if ref not in set(before)]
    if not added:
        return
    keys = {split_decision_ref(ref)[0] for ref in added}
    projects = await ProjectRepository(session).get_by_keys(keys)
    found = await _decisions_of(session, {project.id: key for key, project in projects.items()})
    problems = FieldProblems()
    superseded: list[ProjectDecision] = []
    for ref in added:
        project_key, no = split_decision_ref(ref)
        project = projects.get(project_key)
        if project is None:
            problems.add(TaskField.DECISIONS.value, "unknown_project", ref=ref)
            continue
        decision = found.get(project_key, {}).get(no)
        if decision is not None:
            if decision.superseded_by is not None:
                superseded.append(decision)
            continue
        await _not_of_type(
            session,
            project,
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
    session: AsyncSession, project: Project, entry_type: EntryType, numbers: Sequence[int]
) -> None:
    """Записи, которые заменяет новая запись знания проекта, есть в его деле, того же типа
    и действуют (`CONCEPT.md`, 3.2; TRK#48, раздел 2).

    Номер не из дела проекта и запись другого типа — `entry_fields_invalid` полем
    `supersedes` (`unknown_entry`, `not_a_decision`, `not_a_finding`); уже заменённая —
    `decision_not_in_force` или `finding_not_in_force` с преемником: у записи не бывает
    двух преемников, и цепочка замен остаётся линейной.
    """
    if not numbers:
        return
    standings = await case_standings(session, project)
    problems = FieldProblems()
    superseded: list[tuple[str, str | None]] = []
    for no in numbers:
        ref = format_entry_ref(project.key, no)
        if standings.type_of(no) is not entry_type:
            await _not_of_type(
                session,
                project,
                no,
                expected=entry_type,
                ref=ref,
                field=SUPERSEDES_FIELD,
                problems=problems,
            )
            continue
        standing = standings.of_number(no)
        if standing.superseded_by is not None:
            superseded.append((ref, format_entry_ref(project.key, standing.superseded_by)))
    problems.raise_as(EntryFieldsInvalidError, key=project.key)
    if superseded:
        error, _ = _NOT_IN_FORCE[entry_type]
        raise error(details=_not_in_force_details(entry_type, superseded, key=project.key))


# --- Внутреннее --------------------------------------------------------------------------


async def _decisions_of(
    session: AsyncSession, keys_by_id: dict[uuid.UUID, str]
) -> dict[str, dict[int, ProjectDecision]]:
    """Решения названных проектов: ключ проекта → номер → решение со статусом."""
    entries = await EntryRepository(session).project_decisions(list(keys_by_id))
    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        assert entry.project_id is not None
        grouped[keys_by_id[entry.project_id]].append(entry)
    return {key: _with_status(key, group) for key, group in grouped.items()}


def _with_status(project_key: str, entries: Iterable[Entry]) -> dict[int, ProjectDecision]:
    by_no = {entry.no: entry for entry in entries}
    replaced = {no: tuple(superseded_numbers(entry.payload)) for no, entry in by_no.items()}
    successor_of = successors((no, by_no[no].type, numbers) for no, numbers in replaced.items())
    return {
        no: ProjectDecision(
            entry=entry,
            project_key=project_key,
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
    project: Project,
    no: int,
    *,
    expected: EntryType,
    ref: str,
    field: str,
    problems: FieldProblems,
) -> None:
    """Почему адрес — не запись нужного типа: записи нет (`unknown_entry`) или она другого
    типа (`not_a_decision`, `not_a_finding` — по ожидаемому)."""
    entry = await EntryRepository(session).get_by_project_no(project.id, no)
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


def _successor_ref(decision: ProjectDecision) -> str | None:
    if decision.superseded_by is None:
        return None
    return format_entry_ref(decision.project_key, decision.superseded_by.no)


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
