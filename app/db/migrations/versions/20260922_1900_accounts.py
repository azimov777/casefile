"""accounts and session tokens

Revision ID: 7e3b52a9c1d4
Revises: c4a9d31f7e58
Create Date: 2026-09-22 19:00:00.000000+00:00

Учётные записи людей (`docs/CONCEPT.md`, 3.1 и 5.4; TRK-113): почта, хеш пароля, флаг
администратора и отключение — у одного участника-человека. И срок у токена: сеанс
браузера после входа по почте и паролю — это токен со сроком.

Строк миграция не заводит. Учётную запись администратора заводит шаг подъёма
(`python -m app.cli local-token`, `app/services/setup.py`): только он знает, какой
участник — человек этой установки, и только у него в окружении прежний
`TRACKER_PASSWORD_HASH`, который становится паролем этой учётной записи. Миграции
окружения установки не читают.

Откат сносит таблицу и колонку: учётные записи и сроки сеансов теряются. Токены сеансов
после отката живут без срока — их стоит отозвать руками, если откат не на пустой базе.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7e3b52a9c1d4"
down_revision: str | None = "c4a9d31f7e58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_accounts_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("email", name=op.f("uq_accounts_email")),
        sa.UniqueConstraint("participant_id", name=op.f("uq_accounts_participant_id")),
    )
    op.add_column("tokens", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tokens", "expires_at")
    op.drop_table("accounts")
