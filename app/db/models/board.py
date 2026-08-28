"""Доска, её колонки и ранг карточки.

## Доска не хранит условий отбора

`boards.saved_filter_id` обязателен: источник задач доски — сохранённый фильтр из
задачи 12, а не собственный набор условий (`app/domain/boards.py`). Внешний ключ без
`ondelete`: удалить фильтр, на котором стоит доска, база не даст — доска без источника
перестала бы что-либо показывать, а объяснить это по строке в базе было бы нечем.

## Принадлежность статуса колонке держится составным ключом

`board_column_statuses` несёт и `column_id`, и `board_id`, а внешний ключ на колонку —
составной, на пару `(id, board_id)`. Простой ключ только по `column_id` позволил бы при
обходе сервисного слоя разложить статус в колонку чужой доски, и уникальность
`(board_id, status_id)` перестала бы что-либо значить. Тот же приём держит границу
очереди у воркфлоу (`app/db/models/workflow.py`).

## Ранг — отдельная таблица, а не колонка задачи

Порядок карточек не выводится ни из одного бизнес-поля, и у каждой доски он свой:
одна и та же задача может стоять первой в бэклоге команды и двадцатой на доске релиза.
Колонка в `issues` дала бы один порядок на все доски.

Строки здесь появляются только у задач, которые двигали руками. У остальных позиция
вычисляется из времени создания (`app/domain/boards.py`, `virtual_position`) — поэтому
таблица остаётся маленькой, а порядок всё равно полный.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.catalog import Status
from app.db.models.saved_filter import SavedFilter
from app.domain.boards import MAX_BOARD_NAME_LENGTH, MAX_COLUMN_NAME_LENGTH


class Board(BaseModel):
    """Доска: сохранённый фильтр плюс разбиение по колонкам и порядок карточек."""

    __tablename__ = "boards"
    __table_args__ = (
        # Курсорная пагинация во всём проекте идёт по паре `(created_at, id)`.
        Index("ix_boards_created_at_id", "created_at", "id"),
        Index("ix_boards_saved_filter_id", "saved_filter_id"),
    )

    name: Mapped[str] = mapped_column(String(MAX_BOARD_NAME_LENGTH), nullable=False)
    # Пустая строка вместо NULL — как у очереди, задачи, проекта и фильтра.
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default=text("''"),
        nullable=False,
    )

    saved_filter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_filters.id"),
        nullable=False,
    )
    saved_filter: Mapped[SavedFilter] = relationship(lazy="joined", innerjoin=True)

    columns: Mapped[list[BoardColumn]] = relationship(
        back_populates="board",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: (BoardColumn.position, BoardColumn.id),
    )


class BoardColumn(BaseModel):
    """Колонка доски: набор статусов, порядок и необязательный лимит задач в работе.

    Лимит хранится, но ничего не запрещает: перемещение карточки — это переход
    воркфлоу, и второй запрет поверх него означал бы, что одно и то же изменение статуса
    проходит из карточки задачи и отклоняется с доски. Лимит — то, что доска
    показывает, а не то, что она стережёт.
    """

    __tablename__ = "board_columns"
    __table_args__ = (
        # Две одноимённые колонки на доске неразличимы в интерфейсе.
        UniqueConstraint("board_id", "name"),
        # Нужен составному внешнему ключу из `board_column_statuses`: один только
        # `column_id` позволил бы разложить статус в колонку чужой доски.
        UniqueConstraint("id", "board_id"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("wip_limit IS NULL OR wip_limit > 0", name="wip_limit_positive"),
    )

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(MAX_COLUMN_NAME_LENGTH), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    #: Лимит задач в работе. `NULL` — лимита нет; ноль запрещён проверкой: колонка, куда
    #: нельзя положить ни одной карточки, — это отсутствующая колонка.
    wip_limit: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)

    board: Mapped[Board] = relationship(back_populates="columns")
    status_links: Mapped[list[BoardColumnStatus]] = relationship(
        back_populates="column",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: BoardColumnStatus.id,
    )


class BoardColumnStatus(BaseModel):
    """Статус, попадающий в колонку.

    Каскад по `status_id` нужен для удаления очереди: оно уносит её локальные статусы, и
    без каскада операция падала бы на внешнем ключе. Осмысленный случай — удаление
    статуса, который разложен в колонку, — отклоняет сценарий (`app/services/catalogs.py`):
    каскад унёс бы строку молча и мог оставить колонку без единого статуса, а такая
    колонка показывает все задачи доски.
    """

    __tablename__ = "board_column_statuses"
    __table_args__ = (
        # Статус принадлежит не более чем одной колонке доски: иначе карточка
        # показалась бы дважды, а вопрос «в какой она колонке» потерял бы ответ.
        UniqueConstraint("board_id", "status_id"),
        ForeignKeyConstraint(
            ["column_id", "board_id"],
            ["board_columns.id", "board_columns.board_id"],
            ondelete="CASCADE",
            name="fk_board_column_statuses_column_id_board_columns",
        ),
        Index("ix_board_column_statuses_column_id", "column_id"),
        Index("ix_board_column_statuses_status_id", "status_id"),
    )

    #: Доска — часть составного внешнего ключа на колонку, а не отдельная ссылка на
    #: `boards`. Второй ключ по тому же столбцу был бы не страховкой, а двусмысленностью:
    #: связь «статус в колонке» синхронизирует обе колонки ключа сама, и SQLAlchemy
    #: пришлось бы выбирать между двумя путями к одному значению. Каскад приходит по
    #: цепочке `boards → board_columns → board_column_statuses`.
    board_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    column_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statuses.id", ondelete="CASCADE"),
        nullable=False,
    )

    column: Mapped[BoardColumn] = relationship(back_populates="status_links")
    status: Mapped[Status] = relationship(lazy="joined", innerjoin=True)


class IssueRank(BaseModel):
    """Позиция задачи на доске.

    Строка появляется только у задачи, которую двигали руками. У остальных позиция
    вычисляется из времени создания, поэтому «нет строки» означает «стоит там, где
    встала по умолчанию», а не «порядок неизвестен».
    """

    __tablename__ = "issue_ranks"
    __table_args__ = (
        UniqueConstraint("board_id", "issue_id"),
        # Основной запрос — «соседняя позиция на этой доске»; он идёт по паре
        # `(board_id, position)`, и без индекса каждое перетаскивание карточки означало
        # бы чтение всех рангов доски.
        Index("ix_issue_ranks_board_id_position", "board_id", "position"),
        Index("ix_issue_ranks_issue_id", "issue_id"),
    )

    board_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Целое разреженной шкалы. `BigInteger`, потому что шкала совмещена с виртуальной:
    #: позиция задачи без ранга — это микросекунды эпохи, умноженные на шаг, и обе
    #: обязаны сравниваться как числа одного ряда.
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)
