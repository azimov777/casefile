"""drop token scope

Revision ID: 5c81e3a7d92b
Revises: ebf3dbbcc4e0
Create Date: 2026-10-01 09:00:00.000000+00:00

Наборов токена `task`/`main` больше нет (TRK-471, решение TRK-469#25): любой действующий
доступ агента открывает все инструменты MCP и маршруты REST. Миграция снимает колонку
`tokens.scope` вместе с её ограничением `ck_tokens_token_scope` (тип у неё не native enum,
а VARCHAR + CHECK, отдельного типа PostgreSQL нет).

Живые токены остаются действующими и работают дальше с полными правами агента: строки
не трогаются, меняется только схема.

Откат возвращает колонку набором `task` у всех строк — прежнее значение не восстановить,
его больше никто не хранил, а `task` — меньший из двух наборов.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c81e3a7d92b"
down_revision: str | None = "ebf3dbbcc4e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения по соглашению `NAMING_CONVENTION` (`app/db/base.py`).
CONSTRAINT = "ck_tokens_token_scope"


def upgrade() -> None:
    # Ограничение колонки уходит вместе с ней; явный снос не нужен.
    op.drop_column("tokens", "scope")


def downgrade() -> None:
    op.add_column(
        "tokens",
        sa.Column("scope", sa.String(length=16), server_default=sa.text("'task'"), nullable=False),
    )
    op.execute(f"ALTER TABLE tokens ADD CONSTRAINT {CONSTRAINT} CHECK (scope IN ('task', 'main'))")
    op.alter_column("tokens", "scope", server_default=None)
