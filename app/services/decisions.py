"""Решения проекта: статус при чтении, ссылки задач на решения и замена решения.

Решение проекта — запись `decision` дела проекта (`CONCEPT.md`, 3.2). Отдельной таблицы и
хранимого статуса нет: решение действует, пока ни одно более позднее решение того же
проекта не назвало его в `supersedes`, и статус считается здесь при каждом чтении, как
признак `blocked` у задачи. Замена решения поэтому не пишет ни строчки в дела задач,
которые на него ссылаются, и не будит их (`CONCEPT.md`, 4.3).

## Три потребителя одного расчёта

- пакет задачи (`get_task`): решения, на которые ссылается задача, со статусом и
  преемником — `cited_decisions`;
- чтение проекта: все решения проекта со статусом — `project_decisions`;
- проверки записи: новая ссылка задачи (`check_cited`) и замена решения
  (`check_superseded`) называют только действующее решение.

Все трое читают решения проекта целиком (`EntryRepository.project_decisions`): статус
одного решения зависит от всех более поздних, и выборка «только названных» дала бы
неверный ответ.

## Проверки — под очередью изменений

`check_cited` и `check_superseded` зовут сценарии, которые уже заняли очередь изменений
(`app/db/locks.py`): «решение ещё действует» — факт, который соседняя транзакция могла бы
изменить между проверкой и фиксацией, и тогда у решения оказалось бы два преемника.
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
from app.domain.case import SUPERSEDES_FIELD, EntryType, format_entry_ref, superseded_numbers
from app.domain.decisions import DecisionStatus, status_of, successors
from app.domain.errors import (
    DecisionNotInForceError,
    EntryFieldsInvalidError,
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
        await _not_a_decision(
            session, project, no, ref=ref, field=TaskField.DECISIONS.value, problems=problems
        )
    problems.raise_as(TaskFieldsInvalidError)
    if superseded:
        raise DecisionNotInForceError(details=_not_in_force_details(superseded, key=key))


async def check_superseded(session: AsyncSession, project: Project, numbers: Sequence[int]) -> None:
    """Решения, которые заменяет новое решение проекта, есть в его деле и действуют.

    Номер не из дела проекта и запись не `decision` — `entry_fields_invalid` полем
    `supersedes`; уже заменённое решение — `decision_not_in_force`: у решения не бывает
    двух преемников, и цепочка замен остаётся линейной (`CONCEPT.md`, 3.2).
    """
    if not numbers:
        return
    decisions = (await _decisions_of(session, {project.id: project.key})).get(project.key, {})
    problems = FieldProblems()
    superseded: list[ProjectDecision] = []
    for no in numbers:
        decision = decisions.get(no)
        if decision is None:
            await _not_a_decision(
                session,
                project,
                no,
                ref=format_entry_ref(project.key, no),
                field=SUPERSEDES_FIELD,
                problems=problems,
            )
        elif decision.superseded_by is not None:
            superseded.append(decision)
    problems.raise_as(EntryFieldsInvalidError, key=project.key)
    if superseded:
        raise DecisionNotInForceError(details=_not_in_force_details(superseded, key=project.key))


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
    successor_of = successors(replaced.items())
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


async def _not_a_decision(
    session: AsyncSession,
    project: Project,
    no: int,
    *,
    ref: str,
    field: str,
    problems: FieldProblems,
) -> None:
    """Почему адрес — не решение: записи нет или это запись другого типа."""
    entry = await EntryRepository(session).get_by_project_no(project.id, no)
    if entry is None:
        problems.add(field, "unknown_entry", ref=ref)
    else:
        problems.add(
            field,
            "not_a_decision",
            ref=ref,
            got=entry.type.value,
            expected=EntryType.DECISION.value,
        )


def _not_in_force_details(
    decisions: Sequence[ProjectDecision], *, key: str | None
) -> dict[str, Any]:
    """Подробности `decision_not_in_force`: каждое названное решение и его преемник."""
    details: dict[str, Any] = {
        "decisions": [
            {
                "ref": decision.ref,
                "superseded_by": None
                if decision.superseded_by is None
                else format_entry_ref(decision.project_key, decision.superseded_by.no),
            }
            for decision in decisions
        ]
    }
    if key is not None:
        details["key"] = key
    return details
