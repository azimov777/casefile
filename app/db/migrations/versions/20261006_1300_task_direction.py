"""task direction

Revision ID: 7be41d95c0a2
Revises: 3cc02e043842
Create Date: 2026-10-06 13:00:00.000000+00:00

Поле задачи `direction` (TRK#57; решение владельца `TRK#16`, части 3 и 4;
TRK-556): не больше одного направления своего проекта, необязательное.

- `tasks.direction_id` — ссылка на `directions.id`, `NULL` у каждой существующей задачи:
  направлений до ревизии не было, переносить нечего;
- индекс `ix_tasks_direction_id` — под отбор `direction:` и «задачи направления».

Откат снимает индекс и колонку: что стояло в поле, теряется, дело задач хранит его
записями `field_changed`. Имена объектов не квалифицированы схемой — приём архива переноса
установки гоняет миграции во временной схеме (TRK#202).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7be41d95c0a2"
down_revision: str | None = "3cc02e043842"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("direction_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_direction_id_directions"), "tasks", "directions", ["direction_id"], ["id"]
    )
    op.create_index(op.f("ix_tasks_direction_id"), "tasks", ["direction_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_direction_id"), table_name="tasks")
    op.drop_constraint(op.f("fk_tasks_direction_id_directions"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "direction_id")
