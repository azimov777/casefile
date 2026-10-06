"""task decisions: links from a task to the project decisions it relies on

Revision ID: 4b8e1d6a2c57
Revises: 9e2c6b4f1a83
Create Date: 2026-10-06 01:00:00.000000+00:00

Решения проекта (`TRK-554`, `CONCEPT.md`, 3.2 и 3.3):

- колонка `tasks.decisions` — ссылки `TRK#15` на записи `decision` дела проекта,
  JSONB-список в порядке постановки. У всех задач пуста: до ревизии ссылаться было нечем;
- GIN-индекс `ix_tasks_decisions` (`jsonb_path_ops`) под `decisions @> '["TRK#15"]'` —
  отбор `decision:`, обратный путь от решения к задачам.

Нагрузка `supersedes` у решения проекта колонки не требует: это ключ `payload` записи, а
решения, подшитые до ревизии, его не несут и не заменяют ничего. Статус решения не
хранится вовсе — он считается при чтении.

Откат снимает индекс и колонку: ссылки задач на решения теряются, записи дела остаются.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4b8e1d6a2c57"
down_revision: str | None = "9e2c6b4f1a83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "decisions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tasks_decisions",
        "tasks",
        ["decisions"],
        postgresql_using="gin",
        postgresql_ops={"decisions": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_decisions", table_name="tasks")
    op.drop_column("tasks", "decisions")
