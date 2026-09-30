"""participant owner

Revision ID: 7d3a5e1b9c42
Revises: bb05bcd1d657
Create Date: 2026-10-01 10:00:00.000000+00:00

У участника-агента появляется хозяин — человек (`participants.owner_id`, TRK-476, решение
TRK-475#14). У существующих строк NULL: локальные `claude`/`codex`, общие агенты и люди
хозяина не имеют. Откат снимает колонку и связь.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d3a5e1b9c42"
down_revision: str | None = "bb05bcd1d657"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_participants_owner_id_participants",
        "participants",
        "participants",
        ["owner_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_participants_owner_id_participants", "participants", type_="foreignkey")
    op.drop_column("participants", "owner_id")
