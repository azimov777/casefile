"""drop task tags

Revision ID: c4a9d31f7e58
Revises: a1c7e64b0d92
Create Date: 2026-09-08 10:30:00.000000+00:00

Свободные метки задачи сняты (`CONCEPT.md`, 3.3 и 6): за живую сессию они ставились при
создании каждой задачи и ни разу не понадобились для навигации, а единственное настоящее
применение — машинная метка сквозного теста — выражается отбором `text` по фразе из
названия.

Миграция сносит колонку `tags` вместе с GIN-индексом `ix_tasks_tags`. **Значения
теряются безвозвратно**, и это решение владельца, а не упущение: перекладывать их в
описание или в дело миграция не должна — то и другое читают люди и агенты, и подмешанные
туда метки выглядели бы содержанием задачи.

Записи `field_changed` с полем `tags` не трогаются. Записи дела неизменяемы и постоянны
(`CONCEPT.md`, 4.1): подшитое остаётся правдой о том, что тогда произошло, даже когда
поля больше нет. Схема ответа это учитывает — список остаётся допустимым видом значения
в `before` и `after`.

Обратная миграция возвращает колонку и индекс, но не значения: их взять неоткуда.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4a9d31f7e58"
down_revision: str | None = "a1c7e64b0d92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_tasks_tags"


def upgrade() -> None:
    # Индекс — первым: удаление колонки снесло бы его само, но явный порядок читается
    # в откате симметрично и не зависит от того, что Postgres делает попутно.
    op.drop_index(INDEX, table_name="tasks", postgresql_using="gin")
    op.drop_column("tasks", "tags")


def downgrade() -> None:
    """Возвращает колонку пустой: значения не сохранялись и восстановлению не подлежат.

    Умолчание `'[]'` обязательно и здесь: колонка `NOT NULL`, а строки в таблице уже
    есть — без него откат упал бы на первой же задаче.
    """
    op.add_column(
        "tasks",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(INDEX, "tasks", ["tags"], unique=False, postgresql_using="gin")
