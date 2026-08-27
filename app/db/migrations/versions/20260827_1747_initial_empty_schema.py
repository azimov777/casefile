"""initial empty schema

Revision ID: 59ef3aa95644
Revises:
Create Date: 2026-08-27 17:47:59.454705
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "59ef3aa95644"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
