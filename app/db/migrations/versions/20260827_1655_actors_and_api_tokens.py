"""actors and api tokens

Revision ID: a8ce71dd4ff7
Revises: 59ef3aa95644
Create Date: 2026-08-27 16:55:03.872698+00:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8ce71dd4ff7"
down_revision: str | None = "59ef3aa95644"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тот же UUID объявлен константой `SYSTEM_ACTOR_ID` в `app/domain/actors.py`. Здесь он
# записан литералом сознательно: миграция не должна зависеть от кода приложения, который
# со временем меняется, — иначе накат старой ревизии на новом коде однажды упадёт.
# Совпадение двух значений проверяет тест `tests/test_actors_service.py`.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    actors = op.create_table(
        "actors",
        # Перечисление хранится как VARCHAR с CHECK, а не как тип PostgreSQL:
        # см. `string_enum` в `app/db/base.py`. Ограничение создаёт сам SQLAlchemy
        # вместе с таблицей, но только при `create_constraint=True` — по умолчанию
        # оно выключено, и колонка молча остаётся без проверки значений.
        sa.Column(
            "type",
            sa.Enum(
                "human",
                "agent",
                "system",
                name="actor_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actors")),
        sa.UniqueConstraint("key", name=op.f("uq_actors_key")),
    )
    op.create_table(
        "api_tokens",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_api_tokens_actor_id_actors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index(op.f("ix_api_tokens_actor_id"), "api_tokens", ["actor_id"], unique=False)

    # Системный актор заводится схемой, а не командой инициализации: на него будут
    # ссылаться журнал изменений, outbox и автоматика, и его отсутствие означало бы,
    # что часть системы не работает на свежей базе — в том числе в тестах.
    op.bulk_insert(
        actors,
        [
            {
                "id": SYSTEM_ACTOR_ID,
                "type": "system",
                "key": "system",
                "display_name": "System",
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_api_tokens_actor_id"), table_name="api_tokens")
    op.drop_table("api_tokens")
    op.drop_table("actors")
