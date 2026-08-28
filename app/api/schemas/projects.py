"""Схемы проектов и портфелей.

Связанные объекты приезжают ссылками, а не вложенными записями: ответственный и
участники — ключами акторов, родительский портфель — ключом портфеля. Полные записи
отдают свои эндпоинты, и дублировать их в каждой карточке значило бы рассылать одно и
то же несколькими способами.

## Прогресс — часть ответа, а не отдельный маршрут

Он считается по задачам в момент запроса (`app/services/projects.py`), одним запросом на
страницу. Отдельный эндпоинт `/progress` заставил бы клиента делать второй поход ради
цифры, которую он всё равно показывает рядом с названием, а хранимой колонки у прогресса
нет и не будет.

Внутри прогресса лежат оба счётчика, а не только доля. Доля без них обманчива: «0%» у
проекта без задач и «0%» у проекта из тысячи незакрытых выглядят одинаково, а означают
разное. Поэтому `ratio` у проекта без задач — `null`, а не ноль.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.db.models.project import Portfolio, Project
from app.domain.issues import MAX_TAG_LENGTH, MAX_TAGS
from app.domain.projects import (
    MAX_PLANNING_KEY_LENGTH,
    MAX_PLANNING_MEMBERS,
    MAX_PLANNING_NAME_LENGTH,
    PLANNING_KEY_PATTERN,
    PlanningKind,
    Progress,
    ProjectStatus,
)

PlanningEntity = Project | Portfolio

KeyDescription = (
    "Stable identifier, lowercase latin. Immutable: it addresses the object in paths and "
    "in search filters (`project: alpha`)"
)
NameField = Field(
    min_length=1,
    max_length=MAX_PLANNING_NAME_LENGTH,
    examples=["Платформа доставки"],
    description="Single line: it is shown in lists and on portfolio cards",
)
DescriptionText = "Empty string when there is no description"
StatusDescription = (
    "Planning state, chosen by people and not derived from issue statuses: a project can "
    "be paused with every issue closed"
)
LeadDescription = "Key of the actor responsible for the result"
MembersDescription = f"Keys of the actors working on it, sorted; at most {MAX_PLANNING_MEMBERS}"
PeriodDescription = (
    "Calendar day `YYYY-MM-DD`, without a time of day: a project does not start at 14:37"
)
PortfolioDescription = "Key of the parent portfolio; null when the object is top level"
TagsField = Field(
    max_length=MAX_TAGS,
    examples=[["platform"]],
    description=(
        f"Flat labels, at most {MAX_TAGS} of {MAX_TAG_LENGTH} characters each. Order is "
        "kept, duplicates are dropped case-insensitively"
    ),
)


class ProgressRead(BaseModel):
    """Готовность по задачам: счётчики и доля.

    У портфеля счётчики сложены по задачам **всех** его проектов-потомков, а не усреднены
    по детям: портфель отвечает на вопрос «сколько работы под ним сделано», и мелкий
    проект, закрытый целиком, не должен двигать это число как крупный.
    """

    total: int = Field(examples=[42], description="Issues in the project, or under the portfolio")
    done: int = Field(examples=[17], description="Issues in a status of the `done` category")
    ratio: float | None = Field(
        default=None,
        examples=[0.4],
        description="Share of done issues from 0 to 1; null when there is nothing to measure",
    )

    @classmethod
    def of(cls, progress: Progress) -> ProgressRead:
        return cls(total=progress.total, done=progress.done, ratio=progress.ratio)


class PlanningRead(BaseModel):
    """Общие поля проекта и портфеля в ответе."""

    id: uuid.UUID
    key: str = Field(examples=["alpha"], description=KeyDescription)
    name: str = NameField
    description: str = Field(examples=[""], description=DescriptionText)
    status: ProjectStatus = Field(
        examples=[ProjectStatus.IN_PROGRESS],
        description=StatusDescription,
    )
    lead: str = Field(examples=["alice"], description=LeadDescription)
    members: list[str] = Field(default_factory=list, description=MembersDescription)
    start_date: date | None = Field(default=None, description=PeriodDescription)
    end_date: date | None = Field(default=None, description=PeriodDescription)
    tags: list[str] = TagsField
    portfolio: str | None = Field(default=None, description=PortfolioDescription)
    is_archived: bool = Field(description="Archived objects accept no new work")
    archived_at: datetime | None = None
    progress: ProgressRead
    created_at: datetime
    updated_at: datetime


class ProjectRead(PlanningRead):
    """Проект в ответе. Задачи в него не вложены — их отдаёт `/projects/{key}/issues`.

    В проекте бывают тысячи задач из разных очередей, и вкладывать их в карточку значило
    бы отдавать неподъёмный ответ там, где клиент хотел увидеть название и срок.
    """

    @classmethod
    def of(cls, project: Project, *, progress: Progress) -> ProjectRead:
        return cls(**_planning_payload(project, progress=progress))


class PortfolioRead(PlanningRead):
    """Портфель в ответе: счётчики состава вместо самого состава.

    Пара чисел заменяет обход состава там, где он не нужен целиком: список портфелей
    показывает «3 проекта, 1 портфель», не читая ни одного из них. Сам состав отдаёт
    `/portfolios/{key}/content` — страницами, потому что портфель бывает большим.
    """

    projects_count: int = Field(
        default=0,
        description="Projects lying directly in this portfolio, not counting nested ones",
    )
    portfolios_count: int = Field(default=0, description="Portfolios nested directly in it")

    @classmethod
    def of(
        cls,
        portfolio: Portfolio,
        *,
        progress: Progress,
        counts: tuple[int, int] = (0, 0),
    ) -> PortfolioRead:
        projects, nested = counts
        return cls(
            **_planning_payload(portfolio, progress=progress),
            projects_count=projects,
            portfolios_count=nested,
        )


class PortfolioItemRead(PlanningRead):
    """Позиция состава портфеля: проект или вложенный портфель.

    Одна модель на оба вида, а не объединение типов. Причина в контракте: `data` отдаёт
    одну коллекцию, курсор указывает позицию в одном упорядоченном запросе, и разделить
    состав на две страницы значило бы потерять записи на первой же границе. Поля у
    проекта и портфеля общие, различает их `kind`.
    """

    kind: PlanningKind = Field(
        examples=[PlanningKind.PROJECT],
        description="Whether this entry is a project or a nested portfolio",
    )

    @classmethod
    def of(
        cls,
        entity: PlanningEntity,
        *,
        kind: PlanningKind,
        progress: Progress,
    ) -> PortfolioItemRead:
        return cls(kind=kind, **_planning_payload(entity, progress=progress))


class PlanningCreate(BaseModel):
    """Общие поля создания проекта и портфеля."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=PLANNING_KEY_PATTERN,
        max_length=MAX_PLANNING_KEY_LENGTH,
        examples=["alpha"],
        description=KeyDescription,
    )
    name: str = NameField
    description: str = Field(default="", examples=[""], description=DescriptionText)
    status: ProjectStatus = Field(
        default=ProjectStatus.NOT_STARTED,
        description=StatusDescription,
    )
    lead: str | None = Field(
        default=None,
        examples=["alice"],
        description=f"{LeadDescription}; defaults to the actor behind the token",
    )
    members: list[str] = Field(
        default_factory=list,
        max_length=MAX_PLANNING_MEMBERS,
        description=MembersDescription,
    )
    start_date: date | None = Field(default=None, description=PeriodDescription)
    end_date: date | None = Field(default=None, description=PeriodDescription)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    portfolio: str | None = Field(default=None, description=PortfolioDescription)


class ProjectCreate(PlanningCreate):
    """Создание проекта. Задачи добавляются отдельно: они уже живут в своих очередях."""


class PortfolioCreate(PlanningCreate):
    """Создание портфеля. Цикл здесь невозможен: у нового портфеля детей ещё нет."""


class PlanningUpdate(BaseModel):
    """Частичное обновление: применяются только переданные поля.

    Ключа здесь нет и не будет: по нему адресуют объект в путях и в фильтрах поиска
    (`project: alpha`), и переименование сломало бы сохранённые фильтры молча.

    `portfolio` объявлен как `str | None`: `null` вынимает объект наверх, и это
    осмысленное значение, а не «не передано». Различать три состояния обязательно —
    иначе либо нельзя будет вынуть проект из портфеля, либо каждая правка описания
    выбрасывала бы его оттуда.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=MAX_PLANNING_NAME_LENGTH)
    description: str = unset_field(description="Pass an empty string to clear it")
    status: ProjectStatus = unset_field(description=StatusDescription)
    lead: str = unset_field(description=LeadDescription)
    members: list[str] = unset_field(
        max_length=MAX_PLANNING_MEMBERS,
        description=f"{MembersDescription}. Replaces the whole set",
    )
    start_date: date | None = unset_field(description=f"{PeriodDescription}. Pass null to drop it")
    end_date: date | None = unset_field(description=f"{PeriodDescription}. Pass null to drop it")
    tags: list[str] = unset_field(max_length=MAX_TAGS, description="Replaces the whole set")
    portfolio: str | None = unset_field(
        description=f"{PortfolioDescription}. Pass null to move it to the top level"
    )


class ProjectUpdate(PlanningUpdate):
    """Частичное обновление проекта."""


class PortfolioUpdate(PlanningUpdate):
    """Частичное обновление портфеля. Смена родителя проверяется на цикл."""


class PortfolioSet(BaseModel):
    """Перенос в другой портфель. `null` делает объект верхнеуровневым."""

    model_config = ConfigDict(extra="forbid")

    portfolio: str | None = Field(examples=["platform"], description=PortfolioDescription)


class ProjectIssuesAdd(BaseModel):
    """Добавление задач в проект.

    Список, а не одна задача: в проект переносят разбор целиком, и запрос на задачу
    превратил бы обычную операцию в полсотни запросов. Задача, которая уже в проекте,
    ошибкой не считается и изменений не даёт.
    """

    model_config = ConfigDict(extra="forbid")

    issues: list[str] = Field(
        min_length=1,
        max_length=200,
        examples=[["TRK-1", "OPS-42"]],
        description="Issue keys; they may come from different queues",
    )


def _planning_payload(entity: PlanningEntity, *, progress: Progress) -> dict[str, object]:
    """Общие поля проекта и портфеля в ответ.

    Родитель у проекта лежит в `portfolio`, у портфеля — в `parent`, но наружу оба
    отдаются полем `portfolio`: операция «переложить в другой портфель» у них одна, и
    два имени в контракте заставили бы клиента писать её дважды.
    """
    parent = entity.parent if isinstance(entity, Portfolio) else entity.portfolio
    return {
        "id": entity.id,
        "key": entity.key,
        "name": entity.name,
        "description": entity.description,
        "status": entity.status,
        "lead": entity.lead.key,
        "members": [member.key for member in entity.members],
        "start_date": entity.start_date,
        "end_date": entity.end_date,
        "tags": list(entity.tags),
        "portfolio": None if parent is None else parent.key,
        "is_archived": entity.is_archived,
        "archived_at": entity.archived_at,
        "progress": ProgressRead.of(progress),
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }
