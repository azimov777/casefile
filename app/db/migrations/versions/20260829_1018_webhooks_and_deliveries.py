"""webhooks and deliveries

Revision ID: b911b956fc67
Revises: 4a7c9e1b53d8
Create Date: 2026-08-29 10:18:14.197597+00:00

Заводит канал наружу: подписки вебхуков и очередь доставок, она же журнал (задача 15).

## Одна таблица на очередь и на историю

`webhook_deliveries` — и задание, и запись журнала. Разделение на две означало бы
перенос строки между ними при завершении, то есть момент, в который доставка не лежит
ни там, ни там, если процесс умрёт посередине. Здесь завершение — смена статуса, и
потерять строку невозможно.

## Строки автогенерации о чужих CHECK удалены руками

`--autogenerate` дописал в ревизию снятие `ck_actors_actor_type` и ещё десятка
ограничений у колонок-перечислений, к вебхукам отношения не имеющих. Оставить их значило
бы молча снять проверку допустимых значений с половины таблиц установки. Это известное
поведение сравнения по имени, описанное в `docs/notes/db.md`; проверяется глазами через
`\\d actors` после наката.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b911b956fc67"
down_revision: str | None = "4a7c9e1b53d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secret", sa.String(length=256), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "all",
                "queue",
                "project",
                name="webhook_scope",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'all'"),
            nullable=False,
        ),
        sa.Column("scope_key", sa.String(length=128), nullable=True),
        sa.Column(
            "event_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.String(length=64), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
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
            "consecutive_failures >= 0",
            name=op.f("ck_webhook_subscriptions_consecutive_failures_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["actors.id"],
            name=op.f("fk_webhook_subscriptions_created_by_id_actors"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_subscriptions")),
        sa.UniqueConstraint("name", name="uq_webhook_subscriptions_name"),
    )
    op.create_index(
        "ix_webhook_subscriptions_created_at_id",
        "webhook_subscriptions",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_subscriptions_scope_scope_key",
        "webhook_subscriptions",
        ["scope", "scope_key"],
        unique=False,
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_key", sa.String(length=128), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
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
                name="webhook_delivery_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_webhook_deliveries_attempts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["webhook_subscriptions.id"],
            name=op.f("fk_webhook_deliveries_subscription_id_webhook_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(
        "ix_webhook_deliveries_created_at_id",
        "webhook_deliveries",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"], unique=False
    )
    op.create_index(
        "ix_webhook_deliveries_status_available_at_created_at",
        "webhook_deliveries",
        ["status", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_webhook_deliveries_subscription_id_created_at_id",
        "webhook_deliveries",
        ["subscription_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_subscription_id_created_at_id", table_name="webhook_deliveries"
    )
    op.drop_index(
        "ix_webhook_deliveries_status_available_at_created_at", table_name="webhook_deliveries"
    )
    op.drop_index("ix_webhook_deliveries_event_id", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_created_at_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_subscriptions_scope_scope_key", table_name="webhook_subscriptions")
    op.drop_index("ix_webhook_subscriptions_created_at_id", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")
