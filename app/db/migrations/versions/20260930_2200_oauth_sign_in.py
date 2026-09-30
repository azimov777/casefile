"""oauth sign-in: clients, codes, refresh tokens

Revision ID: ebf3dbbcc4e0
Revises: 9a4d7c2f5e81
Create Date: 2026-09-30 22:00:00.000000+00:00

Вход агента через OAuth 2.1 в службе mcp (TRK-448, программа TRK-446): три таблицы пути
к обычному токену участника — сам доступ остаётся строкой `tokens`.

- `oauth_clients` — клиенты DCR: `client_id` текстом и метаданные регистрации JSONB
  целиком; секретов нет, все клиенты публичные;
- `oauth_codes` — одноразовые коды авторизации: хеш кода, клиент, участник, автор
  согласия, PKCE-вызов, адрес возврата, срок, отметка погашения и выданный токен;
- `oauth_refresh_tokens` — refresh-токены: хеш, клиент, токен участника, цепочка
  ротаций (`family_id`), отметка погашения.

Строк миграция не заводит и не трогает. Откат сносит три таблицы: вошедшие клиенты
теряют refresh и регистрацию, а выданные им токены участников остаются в `tokens`
действующими, пока их не отзовут в «Доступах».
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ebf3dbbcc4e0"
down_revision: str | None = "9a4d7c2f5e81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
        sa.UniqueConstraint("client_id", name=op.f("uq_oauth_clients_client_id")),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_id", sa.Uuid(), nullable=True),
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
        sa.Column(
            "created_by_kind",
            sa.Enum(
                "agent",
                "human",
                "tracker",
                name="author_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_codes_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_oauth_codes_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["tokens.id"],
            name=op.f("fk_oauth_codes_token_id_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_oauth_codes_code_hash")),
    )
    op.create_index(op.f("ix_oauth_codes_client_id"), "oauth_codes", ["client_id"], unique=False)
    op.create_index(op.f("ix_oauth_codes_expires_at"), "oauth_codes", ["expires_at"], unique=False)
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_refresh_tokens_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["tokens.id"],
            name=op.f("fk_oauth_refresh_tokens_token_id_tokens"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_client_id"),
        "oauth_refresh_tokens",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_family_id"),
        "oauth_refresh_tokens",
        ["family_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_token_id"), "oauth_refresh_tokens", ["token_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_refresh_tokens_token_id"), table_name="oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_refresh_tokens_family_id"), table_name="oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_refresh_tokens_client_id"), table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_codes_expires_at"), table_name="oauth_codes")
    op.drop_index(op.f("ix_oauth_codes_client_id"), table_name="oauth_codes")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
