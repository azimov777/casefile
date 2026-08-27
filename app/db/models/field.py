"""Реестр полей задачи: описание поля и его применимость к типам задач.

Поле — это данные, а не колонка: добавление атрибута задаче не требует миграции.
Само значение живёт в `issues.values JSONB` (задача 05), а здесь описано, что это
значение означает и каким оно может быть. Формат хранения зафиксирован в
`app/domain/fields.py` — читать его надо оттуда, а не выводить из этой таблицы.

Область действия та же, что у справочников: `queue_id IS NULL` — поле глобальное и
видно всем очередям, заполненное — локальное и видно только своей. Ключ уникален
внутри области, и одно ограничение с `NULLS NOT DISTINCT` закрывает оба случая.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.catalog import IssueType
from app.db.models.queue import Queue
from app.domain.fields import MAX_FIELD_KEY_LENGTH, FieldValueType


class Field(BaseModel):
    """Описание кастомного поля задачи."""

    __tablename__ = "fields"
    __table_args__ = (
        # Тот же приём, что у справочников: без `NULLS NOT DISTINCT` PostgreSQL
        # считает NULL-ы различными, и глобальных полей `severity` можно было бы
        # завести сколько угодно. Требует PostgreSQL 15+; проект на 17.
        UniqueConstraint("queue_id", "key", postgresql_nulls_not_distinct=True),
    )

    key: Mapped[str] = mapped_column(String(MAX_FIELD_KEY_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Тип и множественность вместе задают форму записи в JSONB. Менять их у поля с
    # данными запрещено сценарием: уже записанные значения задним числом стали бы
    # значить другое, а история изменений — читаться неверно.
    value_type: Mapped[FieldValueType] = mapped_column(
        string_enum(FieldValueType, name="field_value_type", length=16),
        nullable=False,
    )
    is_multiple: Mapped[bool] = mapped_column(default=False, server_default=false(), nullable=False)

    is_required: Mapped[bool] = mapped_column(default=False, server_default=false(), nullable=False)

    # Мягкое удаление. Жёстко удалить поле, которым пользовались, нельзя: значения
    # остались бы в задачах без описания, а история изменений — с записями о поле,
    # которого нет. Скрытое поле исчезает из конфигурации очереди, но не из данных.
    is_hidden: Mapped[bool] = mapped_column(default=False, server_default=false(), nullable=False)

    # Варианты перечисления: `[{"key": "minor", "name": "Незначительная"}, ...]`.
    # Порядок значим — в нём варианты показываются. JSONB, а не отдельная таблица:
    # вариант не самостоятельный объект, на него ничто не ссылается по идентификатору,
    # и таблица дала бы четыре запроса вместо одного ради списка из пяти строк.
    options: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    # Значение по умолчанию хранится ровно в той же форме, что и значение в задаче:
    # дата строкой, множественное — массивом. Одна форма на два места, иначе
    # умолчание пришлось бы приводить к формату при каждом создании задачи.
    default_value: Mapped[Any | None] = mapped_column(JSONB, default=None, nullable=True)

    # Порядок показа в форме. Применяется в конфигурации очереди и в списке
    # применимых полей; постраничный список полей идёт в порядке создания, потому что
    # курсор во всём проекте построен на паре `(created_at, id)`.
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"),
        default=None,
        nullable=True,
    )

    # Загрузка `selectin`: у глобального поля `queue_id` пуст, и запроса не будет
    # вовсе, а страница локальных полей заберёт свои очереди одним запросом.
    # Связь нужна, чтобы собрать ссылку `TRK.severity` из самой записи, а не из
    # контекста запроса, — иначе поле одной очереди отдавалось бы под именем другой.
    queue: Mapped[Queue | None] = relationship(lazy="selectin")

    # Типы задач, к которым поле применимо. Пустой набор означает «ко всем»: это
    # обычный случай, и требовать перечисления всех типов ради него значило бы
    # ломать конфигурацию очереди при каждом заведении нового типа.
    issue_types: Mapped[list[IssueType]] = relationship(
        secondary="field_issue_types",
        lazy="selectin",
        order_by=(IssueType.created_at, IssueType.id),
    )

    @property
    def applies_to_every_issue_type(self) -> bool:
        return not self.issue_types


class FieldIssueType(BaseModel):
    """Ограничение применимости поля одним типом задачи.

    Отдельная таблица, а не список ключей в JSONB: тип задачи — самостоятельный
    объект, и ссылка на него должна держаться внешним ключом. Иначе удаление типа
    оставило бы в реестре полей ссылку в никуда, и заметили бы это при создании
    задачи, далеко от места ошибки.

    Каскад по обоим ключам. По `field_id` он безобиден — ограничения без поля ничего
    не значат. По `issue_type_id` каскад страхует удаление очереди вместе с её
    локальными типами; сам по себе он опасен, потому что молча расширил бы поле с
    «только для багов» до «для всех типов», — поэтому удаление типа, на который
    ссылается поле, отклоняет сценарий справочников (`catalogs.delete_entry`).
    """

    __tablename__ = "field_issue_types"
    __table_args__ = (
        UniqueConstraint("field_id", "issue_type_id"),
        # Уникальное ограничение начинается с `field_id` и обратный вопрос — «какие
        # поля ограничены этим типом задачи» — не обслуживает. А задаётся он при
        # каждой попытке удалить тип задачи, поэтому индекс отдельный.
        Index("ix_field_issue_types_issue_type_id", "issue_type_id"),
    )

    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issue_types.id", ondelete="CASCADE"),
        nullable=False,
    )
