"""Схемы досок, колонок и спринтов.

Связанные объекты приезжают ссылками: статусы колонки — ссылками справочника
(`open`, `TRK.in_review`), сохранённый фильтр и доска — идентификаторами. Полные записи
отдают свои эндпоинты, и дублировать их в каждой карточке значило бы рассылать одно и то
же несколькими способами.

## Доска адресуется идентификатором, а не ключом

Как воркфлоу и сохранённый фильтр: у доски нет стабильного человеческого имени, которое
не менялось бы. Ключ, который можно переименовать, в пути хуже идентификатора, а ключ,
который переименовать нельзя, пришлось бы придумывать при создании каждой доски. То же
относится к спринтам — их заводят по одному в две недели, и глобально уникальный ключ
для каждого был бы данью формальности.

## Позиция карточки наружу не отдаётся

Место задаётся соседом (`after` / `before`), а не числом. Отдав позицию, мы позвали бы
клиента считать её самому — и однажды получили бы две вставки в одно место с одинаковым
числом. То же решение принято для чеклиста (`app/api/schemas/checklists.py`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.db.models.board import Board, BoardColumn, Sprint
from app.domain.boards import (
    MAX_BOARD_COLUMNS,
    MAX_BOARD_NAME_LENGTH,
    MAX_COLUMN_NAME_LENGTH,
    MAX_COLUMN_STATUSES,
    MAX_SPRINT_GOAL_LENGTH,
    MAX_SPRINT_NAME_LENGTH,
    SprintState,
    UnfinishedPolicy,
)
from app.services.boards import SprintCompletion
from app.services.catalogs import format_entry_ref

BoardNameField = Field(
    min_length=1,
    max_length=MAX_BOARD_NAME_LENGTH,
    examples=["Доска команды платформы"],
    description="Single line: it is shown in the board header and in lists",
)
ColumnNameField = Field(
    min_length=1,
    max_length=MAX_COLUMN_NAME_LENGTH,
    # Кириллическая «В» неотличима от латинской «B», и RUF001 это ловит. Перевод
    # здесь неуместен: названия колонок по соглашениям пишутся по-русски.
    examples=["В работе"],  # noqa: RUF001
    description="Single line: it is shown in the column header",
)
SprintNameField = Field(
    min_length=1,
    max_length=MAX_SPRINT_NAME_LENGTH,
    examples=["Спринт 42"],
    description="Single line, unique within the board",
)
DescriptionText = "Empty string when there is no description"
SavedFilterDescription = (
    "Saved filter that selects the issues of this board. The board adds columns and "
    "ordering on top of it and has no conditions of its own"
)
StatusesDescription = (
    "Catalog references of the statuses falling into this column: bare key for a global "
    "status, `QUEUE.key` for a queue-local one. A status belongs to at most one column "
    "of a board"
)
WipLimitDescription = (
    "Work-in-progress limit shown on the column header. It is a hint, not a gate: moving "
    "a card is a workflow transition, and a second gate on top of it would reject from "
    "the board what the issue card accepts"
)
PeriodDescription = (
    "Calendar day `YYYY-MM-DD`, without a time of day: a sprint does not start at 14:37"
)
SprintScopeDescription = (
    "Which issues to take: `backlog` for the ones outside any sprint, `current` for the "
    "active sprint, a sprint UUID for a particular one. Omit for every issue of the board"
)


class BoardColumnRead(BaseModel):
    """Колонка доски в ответе.

    Счётчика задач здесь нет намеренно: курсорная пагинация не считает total, а
    отдельный `COUNT` по фильтру доски — самый дорогой запрос API, и платить за него
    при каждом открытии доски незачем. Сколько карточек в колонке, видно по её странице.
    """

    id: uuid.UUID
    name: str = ColumnNameField
    statuses: list[str] = Field(
        examples=[["open", "TRK.in_review"]],
        description=StatusesDescription,
    )
    wip_limit: int | None = Field(default=None, examples=[3], description=WipLimitDescription)

    @classmethod
    def of(cls, column: BoardColumn) -> BoardColumnRead:
        return cls(
            id=column.id,
            name=column.name,
            statuses=[format_entry_ref(link.status) for link in column.status_links],
            wip_limit=column.wip_limit,
        )


class BoardRead(BaseModel):
    """Доска в ответе: настройки и колонки, но не задачи.

    Задачи отдают `/boards/{id}/columns/{column_id}/issues` и `/boards/{id}/backlog` —
    страницами. Вложить их сюда значило бы отдавать тысячи карточек там, где клиент
    хотел увидеть название и состав колонок.
    """

    id: uuid.UUID
    name: str = BoardNameField
    description: str = Field(examples=[""], description=DescriptionText)
    saved_filter: uuid.UUID = Field(description=SavedFilterDescription)
    columns: list[BoardColumnRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, board: Board) -> BoardRead:
        return cls(
            id=board.id,
            name=board.name,
            description=board.description,
            saved_filter=board.saved_filter_id,
            columns=[BoardColumnRead.of(column) for column in board.columns],
            created_at=board.created_at,
            updated_at=board.updated_at,
        )


class BoardColumnInput(BaseModel):
    """Колонка на входе: название, статусы и лимит."""

    model_config = ConfigDict(extra="forbid")

    name: str = ColumnNameField
    statuses: list[str] = Field(
        min_length=1,
        max_length=MAX_COLUMN_STATUSES,
        examples=[["open"]],
        description=StatusesDescription,
    )
    wip_limit: int | None = Field(default=None, ge=1, description=WipLimitDescription)


class BoardCreate(BaseModel):
    """Создание доски вместе с колонками.

    Колонки принимаются здесь, а не только отдельным запросом: доска без колонок ничего
    не показывает, и два запроса вместо одного оставляли бы промежуточное состояние, в
    котором доска уже есть, а смотреть на ней нечего.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = BoardNameField
    description: str = Field(default="", examples=[""], description=DescriptionText)
    saved_filter: uuid.UUID = Field(description=SavedFilterDescription)
    columns: list[BoardColumnInput] = Field(
        default_factory=list,
        max_length=MAX_BOARD_COLUMNS,
        description="Columns in display order, left to right",
    )


class BoardUpdate(BaseModel):
    """Частичное обновление доски.

    Колонок здесь нет: у них свои эндпоинты, потому что колонка — объект со своим
    идентификатором и своим местом, а не значение поля доски. Замена набора одним
    присваиванием потеряла бы идентификаторы, которые клиент держит открытыми.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=MAX_BOARD_NAME_LENGTH)
    description: str = unset_field(description="Pass an empty string to clear it")
    saved_filter: uuid.UUID = unset_field(description=SavedFilterDescription)


class BoardColumnCreate(BoardColumnInput):
    """Добавление колонки. Без `after` встаёт в конец, `after: null` — в начало."""

    after: uuid.UUID | None = unset_field(
        description="Put the column right after this one; null puts it first"
    )


class BoardColumnUpdate(BaseModel):
    """Частичное обновление колонки. `statuses` заменяет набор целиком."""

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=MAX_COLUMN_NAME_LENGTH)
    statuses: list[str] = unset_field(
        min_length=1,
        max_length=MAX_COLUMN_STATUSES,
        description=f"{StatusesDescription}. Replaces the whole set",
    )
    wip_limit: int | None = unset_field(
        ge=1,
        description=f"{WipLimitDescription}. Pass null to drop the limit",
    )
    after: uuid.UUID | None = unset_field(
        description="Move the column right after this one; null moves it first"
    )


class IssueRankSet(BaseModel):
    """Перестановка карточки: ровно один сосед.

    `after` ставит карточку сразу за указанной задачей, `before` — прямо перед ней;
    `after: null` означает начало списка, `before: null` — конец. Передать оба сразу
    нельзя: это два разных места, и выбрать между ними было бы гаданием.

    Индекс вместо соседа не годится: он разойдётся с состоянием доски, которую тем
    временем изменил кто-то ещё. Позиция наружу не отдаётся вовсе — иначе клиент
    посчитал бы её сам и получил бы две карточки на одном месте.
    """

    model_config = ConfigDict(extra="forbid")

    after: str | None = unset_field(
        examples=["TRK-1"],
        description="Issue key to stand right after; null means the top of the list",
    )
    before: str | None = unset_field(
        examples=["TRK-9"],
        description="Issue key to stand right before; null means the bottom of the list",
    )


class BoardIssueMove(BaseModel):
    """Перенос карточки в другую колонку.

    Это переход воркфлоу, а не запись статуса: доска не может обойти проверки процесса.
    Поэтому здесь же принимаются резолюция и значения полей — переход в колонку «Готово»
    требует резолюции, и без неё перетаскивание карточки означало бы два запроса, из
    которых первый оставлял бы задачу в противоречивом состоянии.
    """

    model_config = ConfigDict(extra="forbid")

    column: uuid.UUID = Field(description="Column to move the card into")
    status: str | None = Field(
        default=None,
        examples=["TRK.in_review"],
        description=(
            "Target status. Required when the column holds more than one status: picking "
            "the first one would move the issue to a status nobody asked for"
        ),
    )
    resolution: str | None = unset_field(
        description="Catalog reference of the resolution; required by a `done` status"
    )
    version: int | None = Field(
        default=None,
        ge=1,
        description="Version the client last saw; omit it to skip the check",
    )


class SprintRead(BaseModel):
    """Спринт в ответе."""

    id: uuid.UUID
    board: uuid.UUID = Field(description="Board this sprint belongs to")
    name: str = SprintNameField
    goal: str = Field(
        examples=[""],
        max_length=MAX_SPRINT_GOAL_LENGTH,
        description="Empty string when the goal is not written down",
    )
    start_date: date | None = Field(default=None, description=PeriodDescription)
    end_date: date | None = Field(default=None, description=PeriodDescription)
    state: SprintState = Field(
        examples=[SprintState.PLANNED],
        description="`planned` → `active` → `completed`; the chain is one-way",
    )
    started_at: datetime | None = Field(
        default=None,
        description="When the sprint was actually started, as opposed to planned",
    )
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, sprint: Sprint) -> SprintRead:
        return cls(
            id=sprint.id,
            board=sprint.board_id,
            name=sprint.name,
            goal=sprint.goal,
            start_date=sprint.start_date,
            end_date=sprint.end_date,
            state=sprint.state,
            started_at=sprint.started_at,
            completed_at=sprint.completed_at,
            created_at=sprint.created_at,
            updated_at=sprint.updated_at,
        )


class SprintCreate(BaseModel):
    """Создание спринта. Заводится он запланированным: запуск — отдельное решение."""

    model_config = ConfigDict(extra="forbid")

    board: uuid.UUID = Field(description="Board to plan the sprint on")
    name: str = SprintNameField
    goal: str = Field(default="", max_length=MAX_SPRINT_GOAL_LENGTH)
    start_date: date | None = Field(default=None, description=PeriodDescription)
    end_date: date | None = Field(default=None, description=PeriodDescription)


class SprintUpdate(BaseModel):
    """Частичное обновление спринта. Состояние меняют `start` и `complete`."""

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=MAX_SPRINT_NAME_LENGTH)
    goal: str = unset_field(
        max_length=MAX_SPRINT_GOAL_LENGTH,
        description="Pass an empty string to clear it",
    )
    start_date: date | None = unset_field(description=f"{PeriodDescription}. Pass null to drop it")
    end_date: date | None = unset_field(description=f"{PeriodDescription}. Pass null to drop it")


class SprintCompleteRequest(BaseModel):
    """Завершение спринта: куда девать незакрытые задачи.

    Значения по умолчанию у `unfinished` нет намеренно. «Перенести в следующий спринт» и
    «вернуть в бэклог» — разные способы работать, решение за командой, а молчаливое
    умолчание однажды растащило бы чужой спринт.
    """

    model_config = ConfigDict(extra="forbid")

    unfinished: UnfinishedPolicy = Field(
        examples=[UnfinishedPolicy.BACKLOG],
        description="Where the issues that did not reach a `done` status go",
    )
    sprint: uuid.UUID | None = Field(
        default=None,
        description="Sprint to carry them over to; required when `unfinished` is `sprint`",
    )


class SprintCompletionRead(BaseModel):
    """Итог завершения спринта: сам спринт и ключи переехавших задач.

    Список возвращается сразу: второй раз его собрать будет неоткуда — состав спринта
    нигде не хранится отдельно от самих задач, а закрытые остались в спринте.
    """

    sprint: SprintRead
    moved: list[str] = Field(
        default_factory=list,
        examples=[["TRK-7", "TRK-9"]],
        description="Keys of the unfinished issues that were carried over",
    )
    target: uuid.UUID | None = Field(
        default=None,
        description="Sprint they were carried over to; null means the backlog",
    )

    @classmethod
    def of(cls, completion: SprintCompletion) -> SprintCompletionRead:
        return cls(
            sprint=SprintRead.of(completion.sprint),
            moved=list(completion.moved),
            target=None if completion.target is None else completion.target.id,
        )


class SprintIssuesAdd(BaseModel):
    """Взятие задач в спринт.

    Список, а не одна задача: спринт планируют разбором целиком, и запрос на задачу
    превратил бы обычную операцию в полсотни запросов. Задача, уже взятая в спринт,
    ошибкой не считается и изменений не даёт.
    """

    model_config = ConfigDict(extra="forbid")

    issues: list[str] = Field(
        min_length=1,
        max_length=200,
        examples=[["TRK-1", "OPS-42"]],
        description="Issue keys; they may come from different queues",
    )
