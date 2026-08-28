"""comments and checklists

Revision ID: 3f4520fae0b9
Revises: efad16cba888
Create Date: 2026-08-28 09:52:38.760159+00:00

Две таблицы без переноса данных: обсуждения и чеклистов до этой ревизии не было.

Из сгенерированной ревизии удалены строки `op.drop_constraint(... type_="check")` для
`ck_actors_actor_type`, `ck_fields_field_value_type`, `ck_issue_links_issue_link_type`,
`ck_issues_issue_priority`, `ck_outbox_events_outbox_status` и
`ck_statuses_status_category` — автогенерация приписывает их каждой ревизии, а
оставленные, они молча сняли бы проверку допустимых значений с колонок-перечислений,
к этой ревизии отношения не имеющих (`docs/notes/db.md`).

Особенности схемы, которые легко принять за недосмотр:

- у `comments.created_at` умолчание `clock_timestamp()`, а не `now()`: время начала
  транзакции одинаково для всех её строк, и пачка комментариев от автоматики
  сортировалась бы по случайным UUID;
- GIN по `comments.mentions` обслуживает запрос движка уведомлений «где меня
  упомянули» (`mentions ? 'alice'`);
- у `checklist_items.position` нет уникальности: перенумерация списка меняет позиции
  пачкой, и уникальный индекс отверг бы промежуточное состояние одного UPDATE. Порядок
  доопределён до устойчивого сортировкой по паре `(position, id)`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f4520fae0b9"
down_revision: str | None = "efad16cba888"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "checklist_items",
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=255), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("is_done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("checked_by_id", sa.Uuid(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
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
            ["assignee_id"],
            ["actors.id"],
            name=op.f("fk_checklist_items_assignee_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["checked_by_id"],
            ["actors.id"],
            name=op.f("fk_checklist_items_checked_by_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_checklist_items_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_items")),
    )
    op.create_index(
        "ix_checklist_items_assignee_id",
        "checklist_items",
        ["assignee_id"],
        unique=False,
    )
    op.create_index(
        "ix_checklist_items_issue_id_position_id",
        "checklist_items",
        ["issue_id", "position", "id"],
        unique=False,
    )
    op.create_table(
        "comments",
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "mentions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["actors.id"],
            name=op.f("fk_comments_author_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_comments_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index("ix_comments_author_id", "comments", ["author_id"], unique=False)
    op.create_index(
        "ix_comments_issue_id_created_at_id",
        "comments",
        ["issue_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_comments_mentions",
        "comments",
        ["mentions"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_comments_mentions", table_name="comments", postgresql_using="gin")
    op.drop_index("ix_comments_issue_id_created_at_id", table_name="comments")
    op.drop_index("ix_comments_author_id", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_checklist_items_issue_id_position_id", table_name="checklist_items")
    op.drop_index("ix_checklist_items_assignee_id", table_name="checklist_items")
    op.drop_table("checklist_items")
