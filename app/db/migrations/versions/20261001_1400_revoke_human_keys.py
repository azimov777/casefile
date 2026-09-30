"""revoke the keys of people: a person signs in, keys are for agents

Revision ID: 9e2c6b4f1a83
Revises: 7d3a5e1b9c42
Create Date: 2026-10-01 14:00:00.000000+00:00

Решение `TRK-469#25`, ответ владельца `TRK-469#19`: человек токенов себе не получает.
Живые строки `kind = 'key'` участников рода `human` — `bootstrap`, ключи, выпущенные
человеку в CLI или в «Доступах», — получают `revoked_at`.

Не отзываются: сеансы и ключ интерфейса машины `local-ui` (вид `session`), ключи агентов
и общие ключи без участника (`participant_id` пуст), подключения `oauth`. Уже отозванные
строки не трогаются: их `revoked_at` остаётся прежним.

Откат ничего не возвращает: отозванный ключ человека оживлять нельзя, секрета у него
всё равно никто не знает. Обратимость в том, что схема не менялась.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9e2c6b4f1a83"
down_revision: str | None = "7d3a5e1b9c42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tokens
           SET revoked_at = now()
         WHERE kind = 'key'
           AND revoked_at IS NULL
           AND participant_id IN (SELECT id FROM participants WHERE kind = 'human')
        """
    )


def downgrade() -> None:
    """Схема не менялась, отозванные ключи людей остаются отозванными."""
