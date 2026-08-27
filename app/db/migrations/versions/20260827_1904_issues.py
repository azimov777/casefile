"""issues

Revision ID: aedda1f6c109
Revises: 1ec6deb4a5aa
Create Date: 2026-08-27 19:04:50.691099+00:00

Ревизия правлена руками после автогенерации: удалены строки
`op.drop_constraint("ck_actors_actor_type")`, `op.drop_constraint("ck_fields_field_value_type")`
и `op.drop_constraint("ck_statuses_status_category")` вместе с их парами в `downgrade`.
Это ложное срабатывание, разобранное в `docs/notes/db.md`: имя ограничения, созданного
`string_enum`, вычисляется соглашением об именах только при компиляции DDL, и сравнение
по имени считает его отсутствующим в метаданных. Оставить строки — снять с трёх колонок
проверку допустимых значений; схема после этого выглядит правильной, а записать в них
можно любую строку.

Начальных задач ревизия не создаёт: задача — пользовательские данные, и придумывать их
за пользователя нечем.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "aedda1f6c109"
down_revision: str | None = "1ec6deb4a5aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "issues",
        sa.Column("key", sa.String(length=36), nullable=False),
        # Внешние ключи без `ondelete`, то есть с `NO ACTION`: удалить очередь, статус,
        # тип, резолюцию или актора, на которых стоят задачи, база не даст. Первую
        # линию обороны держат сценарии — они отвечают понятным `queue_not_empty` или
        # `status_in_use` вместо нарушения ограничения.
        sa.Column("queue_id", sa.Uuid(), nullable=False),
        sa.Column("issue_type_id", sa.Uuid(), nullable=False),
        sa.Column("status_id", sa.Uuid(), nullable=False),
        sa.Column("resolution_id", sa.Uuid(), nullable=True),
        # Приоритет — VARCHAR с CHECK, а не тип PostgreSQL: см. `string_enum` в
        # `app/db/base.py`. `create_constraint=True` обязателен, иначе проверки
        # допустимых значений не будет вовсе, а схема будет выглядеть правильной.
        sa.Column(
            "priority",
            sa.Enum(
                "trivial",
                "minor",
                "normal",
                "major",
                "blocker",
                name="issue_priority",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        sa.Column("summary", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
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
        sa.CheckConstraint("version >= 1", name=op.f("ck_issues_version_positive")),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["actors.id"], name=op.f("fk_issues_assignee_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["actors.id"], name=op.f("fk_issues_author_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["issue_type_id"],
            ["issue_types.id"],
            name=op.f("fk_issues_issue_type_id_issue_types"),
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"], ["queues.id"], name=op.f("fk_issues_queue_id_queues")
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"],
            ["resolutions.id"],
            name=op.f("fk_issues_resolution_id_resolutions"),
        ),
        sa.ForeignKeyConstraint(
            ["status_id"], ["statuses.id"], name=op.f("fk_issues_status_id_statuses")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issues")),
        sa.UniqueConstraint("key", name=op.f("uq_issues_key")),
    )
    op.create_index("ix_issues_assignee_id", "issues", ["assignee_id"], unique=False)
    # Под курсорную пагинацию: она во всём проекте идёт по паре `(created_at, id)`.
    op.create_index("ix_issues_created_at_id", "issues", ["created_at", "id"], unique=False)
    op.create_index("ix_issues_deadline", "issues", ["deadline"], unique=False)
    op.create_index(
        "ix_issues_queue_id_status_id", "issues", ["queue_id", "status_id"], unique=False
    )
    # GIN по `values`: под него ложатся `values ? :ref` и `values @> :fragment` —
    # на них держатся защита реестра полей и поиск по кастомным полям из задачи 12.
    op.create_index("ix_issues_values", "issues", ["values"], unique=False, postgresql_using="gin")

    op.create_table(
        "issue_followers",
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
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
            ["actor_id"],
            ["actors.id"],
            name=op.f("fk_issue_followers_actor_id_actors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_issue_followers_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_followers")),
        sa.UniqueConstraint(
            "issue_id", "actor_id", name=op.f("uq_issue_followers_issue_id_actor_id")
        ),
    )
    # Уникальное ограничение начинается с `issue_id` и обратный вопрос — «за какими
    # задачами следит этот актор» — не обслуживает, а это основной запрос инбокса.
    op.create_index("ix_issue_followers_actor_id", "issue_followers", ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_issue_followers_actor_id", table_name="issue_followers")
    op.drop_table("issue_followers")
    op.drop_index("ix_issues_values", table_name="issues", postgresql_using="gin")
    op.drop_index("ix_issues_queue_id_status_id", table_name="issues")
    op.drop_index("ix_issues_deadline", table_name="issues")
    op.drop_index("ix_issues_created_at_id", table_name="issues")
    op.drop_index("ix_issues_assignee_id", table_name="issues")
    op.drop_table("issues")
