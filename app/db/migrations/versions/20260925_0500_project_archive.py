"""project archive

Revision ID: 3f9a6c21d4b8
Revises: b7d2f94c0e15
Create Date: 2026-09-25 05:00:00.000000+00:00

Архивирование проекта (`CONCEPT.md`, 3.2; TRK-154, TRK-159): архив заменяет удаление,
которого нет.

- колонка `projects.archived_at` — время архивирования, `NULL` у живого проекта. Все
  существующие проекты остаются живыми: автоархива нет ни по какому признаку;
- ограничение типов записей `ck_entries_entry_type` расширяется служебными `archived` и
  `restored` — причина архивирования и восстановления живёт в деле проекта.

Задачам ничего не добавляется: признака архива у задачи нет, «архивна» задача, лежащая в
архивном проекте. Имена объектов не квалифицированы схемой — приём архива переноса
установки гоняет миграции во временной схеме.

Откат снимает колонку и сужает ограничение типов. Если в деле какого-то проекта уже есть
записи `archived` или `restored`, откат отказывает на сужении: записи неизменяемы, и
удалить историю ради отката нельзя. Архивный проект после отката стал бы живым молча,
поэтому такой откат и должен споткнуться — о его запись `archived`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f9a6c21d4b8"
down_revision: str | None = "b7d2f94c0e15"
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
    "attribute_created",
    "attribute_changed",
    "attribute_removed",
)

TYPES_AFTER = (*TYPES_BEFORE, "archived", "restored")


def _replace_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK (`string_enum`)."""
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    _replace_constraint(TYPES_AFTER)


def downgrade() -> None:
    _replace_constraint(TYPES_BEFORE)
    op.drop_column("projects", "archived_at")
