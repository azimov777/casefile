"""tasks and entries

Revision ID: a7d3e9f1c5b2
Revises: c4a1f7b93e28
Create Date: 2026-09-03 23:00:00.000000+00:00

Задача с фиксированными полями и пятью разделами, зашитыми статусами и версией для
оптимистичной блокировки; дело — таблица неизменяемых записей со сквозным номером
`seq` от базы и номером `no` внутри задачи (задача 22).

Неизменяемость записей закреплена в схеме триггером `entries_immutable`: `UPDATE` и
`DELETE` на `entries` падают исключением базы. Это не защита от клиента — маршрутов и
методов правки нет вовсе, — а защита от следующего разработчика, который напишет
«исправляющий» скрипт. `TRUNCATE` триггер не ловит: сброс установки целиком остаётся
возможным.

Перечисления — VARCHAR с CHECK, как во всём проекте (`string_enum` в `app/db/base.py`);
`create_constraint=True` обязателен, иначе колонка молча остаётся без проверки.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d3e9f1c5b2"
down_revision: str | None = "c4a1f7b93e28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _author_kind() -> sa.Enum:
    return sa.Enum(
        "agent",
        "human",
        "tracker",
        name="author_kind",
        native_enum=False,
        create_constraint=True,
        length=16,
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


IMMUTABLE_FUNCTION = """
CREATE FUNCTION entries_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'entries are immutable: % is not allowed', TG_OP;
END;
$$;
"""

IMMUTABLE_TRIGGER = """
CREATE TRIGGER entries_immutable
BEFORE UPDATE OR DELETE ON entries
FOR EACH ROW EXECUTE FUNCTION entries_reject_change();
"""


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("key", sa.String(length=36), nullable=False),
        sa.Column("queue_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("context", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("constraints", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("output", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "backlog",
                "open",
                "in_progress",
                "review",
                "done",
                "cancelled",
                name="task_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'backlog'"),
            nullable=False,
        ),
        sa.Column("assignee", sa.String(length=64), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "normal",
                "high",
                "critical",
                name="task_priority",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by_kind", _author_kind(), nullable=False),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_tasks_version_positive")),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["queues.id"],
            name=op.f("fk_tasks_queue_id_queues"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("key", name=op.f("uq_tasks_key")),
    )
    op.create_index("ix_tasks_queue_id_status", "tasks", ["queue_id", "status"], unique=False)
    op.create_index("ix_tasks_assignee", "tasks", ["assignee"], unique=False)
    op.create_index("ix_tasks_created_at_id", "tasks", ["created_at", "id"], unique=False)
    op.create_index("ix_tasks_tags", "tasks", ["tags"], unique=False, postgresql_using="gin")

    op.create_table(
        "entries",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("no", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
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
                "assignee_changed",
                "link_added",
                "link_removed",
                name="entry_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_kind", _author_kind(), nullable=False),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_entries_task_id_tasks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entries")),
        sa.UniqueConstraint("seq", name=op.f("uq_entries_seq")),
        sa.UniqueConstraint("task_id", "no", name=op.f("uq_entries_task_id_no")),
    )
    op.create_index("ix_entries_task_id_type", "entries", ["task_id", "type"], unique=False)

    op.execute(IMMUTABLE_FUNCTION)
    op.execute(IMMUTABLE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER entries_immutable ON entries")
    op.execute("DROP FUNCTION entries_reject_change()")
    op.drop_index("ix_entries_task_id_type", table_name="entries")
    op.drop_table("entries")
    op.drop_index("ix_tasks_tags", table_name="tasks", postgresql_using="gin")
    op.drop_index("ix_tasks_created_at_id", table_name="tasks")
    op.drop_index("ix_tasks_assignee", table_name="tasks")
    op.drop_index("ix_tasks_queue_id_status", table_name="tasks")
    op.drop_table("tasks")
