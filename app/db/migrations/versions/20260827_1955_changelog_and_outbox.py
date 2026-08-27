"""changelog and outbox

Revision ID: f372e87bb785
Revises: aedda1f6c109
Create Date: 2026-08-27 19:55:39.411223+00:00

Ревизия правлена руками после автогенерации:

1. Удалены четыре строки `op.drop_constraint("ck_actors_actor_type", ...)` и им
   подобные вместе с их зеркалом в `downgrade`. Это известное ложное срабатывание:
   имя ограничения, созданного `string_enum`, вычисляется соглашением об именах только
   при компиляции DDL, и для сравнения по имени оно «отсутствует». Оставить строки —
   молча снять с четырёх колонок проверку допустимых значений. Подробности — в
   `docs/notes/db.md`.

2. Отметка `created_at` у обеих таблиц ставится `clock_timestamp()`, а не `now()`, — это
   не описка автогенерации, а объявление модели. `now()` — время начала транзакции, и
   все записи одной транзакции получили бы одну отметку, а сортировка по паре
   `(created_at, id)` выродилась бы в сортировку по случайным UUID: история задачи
   показывалась бы в произвольном порядке, события уходили бы не в том порядке, в каком
   происходили.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f372e87bb785"
down_revision: str | None = "aedda1f6c109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        # Без внешнего ключа намеренно: событие `issue.deleted` обязано пережить
        # задачу, а каскад унёс бы его вместе с ней.
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_key", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "delivered",
                "failed",
                name="outbox_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "delivered_to",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_outbox_events_attempts_not_negative")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["actors.id"], name=op.f("fk_outbox_events_actor_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    # Выборка воркера целиком: «необработанные, которым пришло время», по порядку.
    op.create_index(
        "ix_outbox_events_status_available_at_created_at",
        "outbox_events",
        ["status", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_events_object_type_object_id",
        "outbox_events",
        ["object_type", "object_id"],
        unique=False,
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"], unique=False)

    op.create_table(
        "changelog_entries",
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "changes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            ["actor_id"], ["actors.id"], name=op.f("fk_changelog_entries_actor_id_actors")
        ),
        # Каскад: задача удаляется насовсем, и её история вместе с ней. Факт удаления
        # остаётся событием в outbox, у которого ссылки на задачу нет.
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_changelog_entries_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changelog_entries")),
    )
    op.create_index(
        "ix_changelog_entries_issue_id_created_at_id",
        "changelog_entries",
        ["issue_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_changelog_entries_actor_id", "changelog_entries", ["actor_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_changelog_entries_actor_id", table_name="changelog_entries")
    op.drop_index("ix_changelog_entries_issue_id_created_at_id", table_name="changelog_entries")
    op.drop_table("changelog_entries")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_index("ix_outbox_events_object_type_object_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status_available_at_created_at", table_name="outbox_events")
    op.drop_table("outbox_events")
