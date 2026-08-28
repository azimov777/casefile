"""issue links

Revision ID: efad16cba888
Revises: d4f9a1b2c3e4
Create Date: 2026-08-28 08:27:24.607086+00:00

Одна таблица без переноса данных: связей до этой ревизии не было.

Три ограничения выражают инварианты связей на уровне базы. Уникальная тройка ловит
дубликат — он ловится только потому, что направление приводится к каноническому виду
до вставки (`app/domain/links.py`). Проверка `link_type IN (...)` не даёт положить в
таблицу обратный тип: с ним одна и та же связь оказалась бы записана дважды разными
словами. Частичный уникальный индекс по источнику иерархических строк и есть правило
«у задачи не более одного родителя».
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "efad16cba888"
down_revision: str | None = "d4f9a1b2c3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issue_links",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "link_type",
            sa.Enum(
                "relates",
                "depends_on",
                "blocks",
                "subtask_of",
                "parent_of",
                "duplicates",
                "duplicated_by",
                name="issue_link_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("author_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "link_type IN ('depends_on', 'duplicates', 'relates', 'subtask_of')",
            name=op.f("ck_issue_links_stored_link_type"),
        ),
        sa.CheckConstraint("source_id <> target_id", name=op.f("ck_issue_links_no_self_link")),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["actors.id"],
            name=op.f("fk_issue_links_author_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["issues.id"],
            name=op.f("fk_issue_links_source_id_issues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["issues.id"],
            name=op.f("fk_issue_links_target_id_issues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_links")),
        sa.UniqueConstraint(
            "source_id",
            "target_id",
            "link_type",
            name=op.f("uq_issue_links_source_id_target_id_link_type"),
        ),
    )
    op.create_index(
        "ix_issue_links_created_at_id",
        "issue_links",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_issue_links_source_id_link_type",
        "issue_links",
        ["source_id", "link_type"],
        unique=False,
    )
    op.create_index(
        "ix_issue_links_target_id_link_type",
        "issue_links",
        ["target_id", "link_type"],
        unique=False,
    )
    op.create_index(
        "uq_issue_links_parent",
        "issue_links",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'subtask_of'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_issue_links_parent",
        table_name="issue_links",
        postgresql_where=sa.text("link_type = 'subtask_of'"),
    )
    op.drop_index("ix_issue_links_target_id_link_type", table_name="issue_links")
    op.drop_index("ix_issue_links_source_id_link_type", table_name="issue_links")
    op.drop_index("ix_issue_links_created_at_id", table_name="issue_links")
    op.drop_table("issue_links")
