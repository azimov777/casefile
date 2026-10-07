"""task not_before

Revision ID: 29c012062376
Revises: 7be41d95c0a2
Create Date: 2026-10-07 02:00:00.000000+00:00

Поле задачи `not_before` (решение проекта `TRK#47`, TRK-592): момент, раньше которого
задачу не взять в работу. Необязательное, `NULL` у каждой существующей задачи: отложенных
задач до ревизии не было, переносить нечего.

Индекса нет намеренно: отбор `deferred:` сравнивает колонку с часами базы (`now()`), и в
отрицании (`deferred: false`) это условие к индексу не ляжет; отбор сужают проект и статус.

Откат снимает колонку: что стояло в поле, теряется, дело задач хранит его записями
`field_changed`. Имена объектов не квалифицированы схемой — приём архива переноса
установки гоняет миграции во временной схеме (`CONCEPT.md`, 5.5).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "29c012062376"
down_revision: str | None = "7be41d95c0a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "not_before")
