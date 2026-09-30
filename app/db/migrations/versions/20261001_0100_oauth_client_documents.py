"""oauth client documents: document expiry of CIMD clients

Revision ID: 4c1e8a9d2b37
Revises: ebf3dbbcc4e0
Create Date: 2026-10-01 01:00:00.000000+00:00

Клиент по документу метаданных (CIMD, TRK-449) живёт в той же `oauth_clients`, что и
клиент DCR: на его строку ссылаются коды и refresh-токены. Отличает его колонка
`document_expires_at` — до этого момента документ берётся из строки, после скачивается
заново. У клиентов DCR она пуста.

Строк миграция не трогает: все существующие клиенты — DCR. Откат снимает колонку;
клиенты по документу после отката выглядели бы клиентами DCR с вечным документом,
поэтому откат их удаляет вместе с кодами и refresh-токенами (каскад) — при следующем
входе клиент скачает документ заново.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c1e8a9d2b37"
down_revision: str | None = "ebf3dbbcc4e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oauth_clients",
        sa.Column("document_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("DELETE FROM oauth_clients WHERE document_expires_at IS NOT NULL")
    op.drop_column("oauth_clients", "document_expires_at")
