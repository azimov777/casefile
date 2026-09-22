"""entry action id

Revision ID: 7f4089f291b8
Revises: 7e3b52a9c1d4
Create Date: 2026-09-22 22:00:00.000000+00:00

Признак одного действия у записи дела (`CONCEPT.md`, 3.4; TRK-118). Один вызов
(`update_task`, `transition`, `close_task`, `create_task`, `link` и прочие точки
входа `app/services/case.py` и `app/services/tasks.py`) подшивает от одной до
нескольких записей и ставит им одно и то же значение `action_id`; разные вызовы
получают разные значения. Интерфейс группирует записи по нему без эвристики по
совпавшему `created_at` (UI-133, UI-133#5): совпадение времени — следствие `now()`
внутри транзакции, а не обещание контракта.

Значение генерирует Python (`uuid.uuid4()`) на входе вызова, а не база: подробности —
в `app/db/models/entry.py`, раздел «`action_id` — признак одного действия».

Колонка допускает `null`: у записей, подшитых до этой миграции, действия, которым их
подшили, не записано, и восстанавливать его задним числом по совпавшим `created_at` и
автору — та же эвристика, от которой уходит сама задача (`decision` в деле TRK-118).
Таблица неизменяема триггером `entries_immutable`, и миграция строк не трогает —
только добавляет колонку.

Откат снимает колонку: значения признака теряются у всех записей, не только у старых.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f4089f291b8"
down_revision: str | None = "7e3b52a9c1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("entries", sa.Column("action_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("entries", "action_id")
