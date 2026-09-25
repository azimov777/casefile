"""task move

Revision ID: 6d2e9b41c7f3
Revises: 3f9a6c21d4b8
Create Date: 2026-09-25 14:00:00.000000+00:00

Перенос задачи в другой проект (`CONCEPT.md`, 3.3; TRK-171, TRK-172): ключ задачи
меняется, а прежний продолжает вести на неё.

- колонка `tasks.previous_keys` — прежние ключи в порядке ухода, JSONB-список. У всех
  существующих задач он пуст: до этой ревизии задачи не переносились, и прежних ключей
  нет ни у одной. Поэтому переносить строки нечего — ни на живой установке, ни в архиве
  переноса установки старой ревизии, который доводят до head этой же миграцией;
- GIN-индекс `ix_tasks_previous_keys` (`jsonb_path_ops`) под `previous_keys @> '["UI-5"]'`:
  по прежнему ключу задачу ищет каждое обращение, как по текущему;
- ограничение типов записей `ck_entries_entry_type` расширяется служебным `moved`.

Имена объектов не квалифицированы схемой — приём архива переноса установки гоняет
миграции во временной схеме.

Откат снимает индекс и колонку и сужает ограничение типов. Если какая-то задача уже
переносилась, откат отказывает на сужении — о её запись `moved`: записи неизменяемы, а
без колонки прежние ключи перестали бы вести на задачу молча.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6d2e9b41c7f3"
down_revision: str | None = "3f9a6c21d4b8"
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
    "archived",
    "restored",
)

TYPES_AFTER = (*TYPES_BEFORE, "moved")


def _replace_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK (`string_enum`)."""
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "previous_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tasks_previous_keys",
        "tasks",
        ["previous_keys"],
        postgresql_using="gin",
        postgresql_ops={"previous_keys": "jsonb_path_ops"},
    )
    _replace_constraint(TYPES_AFTER)


def downgrade() -> None:
    _replace_constraint(TYPES_BEFORE)
    op.drop_index("ix_tasks_previous_keys", table_name="tasks")
    op.drop_column("tasks", "previous_keys")
