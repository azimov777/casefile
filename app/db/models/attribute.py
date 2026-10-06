"""Атрибуты проекта и направления: текущее значение справочного факта «имя → значение»."""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel
from app.domain.attributes import MAX_ATTRIBUTE_NAME_LENGTH


class ProjectAttribute(BaseModel):
    """Строка — нынешнее значение одного атрибута проекта (`CONCEPT.md`, 3.2).

    Истории здесь нет и не будет: каждое заведение, изменение и снятие подшивает
    служебную запись в дело проекта (`attribute_created`, `attribute_changed`,
    `attribute_removed`) с прежним и новым значением и причиной. Отдельная таблица истории
    была бы вторым журналом. Поэтому снятие удаляет строку: всё, что о ней было, уже в деле.

    Автора у строки нет по той же причине: кто завёл и кто менял — авторы записей дела.
    """

    __tablename__ = "project_attributes"
    __table_args__ = (
        # Имя уникально внутри проекта без учёта регистра, хранится как прислано.
        # Выражение то же, что в миграции (`docs/notes/db.md`, «Индекс по выражению
        # объявляется в модели тем же текстом, что в миграции»); по нему же идёт поиск по
        # имени, поэтому отдельного индекса по `project_id` не нужно.
        Index(
            "uq_project_attributes_project_id_lower_name",
            "project_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    # Без `ondelete`: проекты не удаляются, а если однажды — база откажет, и атрибуты
    # не исчезнут молча.
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_ATTRIBUTE_NAME_LENGTH), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class DirectionAttribute(BaseModel):
    """Строка — нынешнее значение одного атрибута направления (`CONCEPT.md`, 3.7).

    Механика атрибута проекта целиком: имя как прислано и уникально без учёта регистра,
    история — служебные записи дела направления, снятие удаляет строку. Своя таблица, а не
    второй владелец у `project_attributes`: у записей дела владелец общий ради одной ленты
    (`entries`), а у атрибутов общего нет ничего, кроме формы, и вторая колонка владельца
    превратила бы уникальность имени в два частичных индекса ради одной экономии таблицы.
    """

    __tablename__ = "direction_attributes"
    __table_args__ = (
        Index(
            "uq_direction_attributes_direction_id_lower_name",
            "direction_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    direction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("directions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_ATTRIBUTE_NAME_LENGTH), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)


#: Атрибут любого владельца: у обеих строк одна форма — имя и значение.
type Attribute = ProjectAttribute | DirectionAttribute
