"""onboarding state

Revision ID: 9a4d7c2f5e81
Revises: 6d2e9b41c7f3
Create Date: 2026-09-28 12:00:00.000000+00:00

Состояние знакомства человека с Casefile хранится у учётной записи, а не в браузере —
решение владельца (`TRK-360#17`), реализация `TRK-369`. Три колонки на `accounts`:

- `onboarding_status` — прошёл ли человек знакомство: `pending`, `completed`, `skipped`;
- `onboarding_hidden_all` — скрыты ли разом все пояснения экранов;
- `onboarding_hidden` — какие пояснения скрыты по одному, список непрозрачных ключей.

Существующая учётная запись продуктом уже пользуется, и ей полагается `skipped` с
`hidden_all: true` — этими значениями заполняются добавленные колонки на уже стоящих
строках (`server_default`, применённый самим `ALTER TABLE ... ADD COLUMN`). Дальше
умолчание меняется на то, что видит новая учётная запись, — `pending`, всё показано, —
двумя `ALTER COLUMN ... SET DEFAULT`: без второго шага новые строки продолжали бы
заводиться уже пройденными.

В журнал состояние не пишется (`docs/CONVENTIONS.md`, «Журнал»): это сведения учётной
записи, как пароль и почта, а не ход работы, и подшивать миграции нечего.

Откат снимает все три колонки.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a4d7c2f5e81"
down_revision: str | None = "6d2e9b41c7f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_accounts_onboarding_status"
STATUSES = ("pending", "completed", "skipped")


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "onboarding_status",
            sa.String(length=16),
            server_default=sa.text("'skipped'"),
            nullable=False,
        ),
    )
    values = ", ".join(f"'{status}'" for status in STATUSES)
    op.execute(
        f"ALTER TABLE accounts ADD CONSTRAINT {CONSTRAINT} CHECK (onboarding_status IN ({values}))"
    )
    op.add_column(
        "accounts",
        sa.Column(
            "onboarding_hidden_all",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "onboarding_hidden",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    # Существующие строки получили `skipped`/`true` умолчанием `ADD COLUMN` выше — это их
    # состояние навсегда (`TRK-360#17`). Дальше умолчание меняется на то, что видит новая
    # учётная запись, заведённая уже после этой миграции.
    op.alter_column("accounts", "onboarding_status", server_default=sa.text("'pending'"))
    op.alter_column("accounts", "onboarding_hidden_all", server_default=sa.text("false"))


def downgrade() -> None:
    op.drop_column("accounts", "onboarding_hidden")
    op.drop_column("accounts", "onboarding_hidden_all")
    op.drop_column("accounts", "onboarding_status")
