"""project attributes

Revision ID: 8e4a61c3d2f7
Revises: 5c1d8e7a2b90
Create Date: 2026-09-25 01:00:00.000000+00:00

Атрибуты проекта (`CONCEPT.md`, 3.2 и 3.4; TRK-153, TRK-157): справочные факты «имя →
значение» с историей в деле проекта.

- таблица `project_attributes` — нынешние значения: `project_id`, `name` как прислано,
  `value`, времена. Имя уникально внутри проекта без учёта регистра — уникальный индекс
  по выражению `lower(name)`, тем же текстом, что в модели;
- ограничение типов записей `ck_entries_entry_type` расширяется служебными
  `attribute_created`, `attribute_changed` и `attribute_removed` — истории отдельной
  таблицей нет, она в деле проекта.

Строки не трогаются: атрибутов до этой ревизии не было. Имена объектов не квалифицированы
схемой — приём архива переноса установки гоняет миграции во временной схеме.

Откат снимает таблицу вместе с нынешними значениями и сужает ограничение типов. Если в
деле какого-то проекта уже есть записи об атрибутах, откат отказывает на сужении: записи
неизменяемы, и удалить историю ради отката нельзя.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e4a61c3d2f7"
down_revision: str | None = "5c1d8e7a2b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_entries_entry_type"

TYPES_BEFORE = (
    "summary",
    "decision",
    "attempt",
    "finding",
    "artifact",
    "question",
    "answer",
    "verdict",
    "note",
    "created",
    "status_changed",
    "section_changed",
    "field_changed",
    "assignee_changed",
    "link_added",
    "link_removed",
    "remark",
    "resolution",
)

TYPES_AFTER = (*TYPES_BEFORE, "attribute_created", "attribute_changed", "attribute_removed")

#: Уникальность имени без учёта регистра: то же выражение, что в модели
#: (`app/db/models/attribute.py`).
NAME_INDEX = "uq_project_attributes_project_id_lower_name"


def _replace_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK (`string_enum`)."""
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    op.create_table(
        "project_attributes",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_attributes_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_attributes")),
    )
    op.create_index(
        NAME_INDEX,
        "project_attributes",
        ["project_id", sa.text("lower(name)")],
        unique=True,
    )
    _replace_constraint(TYPES_AFTER)


def downgrade() -> None:
    _replace_constraint(TYPES_BEFORE)
    op.drop_index(NAME_INDEX, table_name="project_attributes")
    op.drop_table("project_attributes")
