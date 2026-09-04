"""idempotency keys

Revision ID: d4a7c1e93f28
Revises: c1f8a3d60b72
Create Date: 2026-09-04 05:00:00.000000+00:00

Ключи идемпотентности создающих вызовов (задача 27).

Главное в этой таблице — уникальность пары `(token_id, key)`. Она не проверка «чтобы не
завелось лишнего», а сам механизм: два одновременных повтора одного ключа сходятся на
этом индексе, второй ждёт на нём конца первой транзакции и дальше либо получает
нарушение уникальности (значит, ответ уже есть), либо вставляется сам (значит, первая
откатилась). Проверка в коде на её месте пропустила бы оба запроса разом.

Пара, а не один ключ: ключ живёт в паре с токеном, и одинаковые ключи разных агентов
независимы. `NULLS NOT DISTINCT` тут не нужен — `token_id` не бывает пустым.

`ON DELETE CASCADE` у токена: токены не удаляются (отзыв — это дата в `revoked_at`), но
если строка когда-нибудь уйдёт, ключи уйдут вместе с ней — оставлять записи с секретами
в ответах, привязанные к несуществующему доступу, незачем.

Индекс по `created_at` — под попутную уборку: устаревшие ключи снимаются `DELETE ...
WHERE created_at < ...` на каждой записи нового ключа, и без индекса эта уборка была бы
полным проходом по таблице на каждом создающем запросе.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a7c1e93f28"
down_revision: str | None = "c1f8a3d60b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            ["token_id"],
            ["tokens.id"],
            name=op.f("fk_idempotency_keys_token_id_tokens"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("token_id", "key", name="uq_idempotency_keys_token_id_key"),
    )
    op.create_index(
        "ix_idempotency_keys_created_at",
        "idempotency_keys",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
