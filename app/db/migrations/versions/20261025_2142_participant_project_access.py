"""participant project access

Revision ID: 50535bc472dd
Revises: 68c51da858b1
Create Date: 2026-10-25 21:42:23.254991+00:00

Доступ агента к проектам (TRK-746; слово владельца TRK~28#6, выбор «A»).

- `participants.project_access_mode` — режим `all` | `except` | `only`, NOT NULL, по
  умолчанию `all` (`ck_participants_project_access_mode` держит три значения); у
  существующих участников режим становится `all`, их данные не меняются;
- `participant_projects` — список проектов участника: пара уникальна
  (`uq_participant_projects_participant_id_project_id`), индекс по проекту. В `except`
  список — закрытые проекты, в `only` — открытые, в `all` — пуст.

Имена объектов не квалифицированы схемой — приём архива переноса гоняет миграции во
временной схеме (TRK#202). Откат снимает столбец и таблицу вместе со списками.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "50535bc472dd"
down_revision: str | None = "68c51da858b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column(
            "project_access_mode",
            sa.String(length=16),
            server_default="all",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_participants_project_access_mode",
        "participants",
        "project_access_mode IN ('all', 'except', 'only')",
    )
    op.create_table(
        "participant_projects",
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_participant_projects_participant_id_participants"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_participant_projects_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participant_projects")),
        sa.UniqueConstraint(
            "participant_id",
            "project_id",
            name=op.f("uq_participant_projects_participant_id_project_id"),
        ),
    )
    op.create_index(
        "ix_participant_projects_project_id", "participant_projects", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_participant_projects_project_id", table_name="participant_projects")
    op.drop_table("participant_projects")
    op.drop_constraint("ck_participants_project_access_mode", "participants", type_="check")
    op.drop_column("participants", "project_access_mode")
