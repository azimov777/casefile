"""case entry lookups

Revision ID: e2b6c04a91df
Revises: a7d3e9f1c5b2
Create Date: 2026-09-03 23:40:00.000000+00:00

Индексы под запросы дела, появившиеся вместе с записями агента (задача 23).

Схема таблиц не меняется: `payload` записи уже был JSONB, и типизация нагрузки живёт в
коде, а не в базе. Ревизия добавляет только то, без чего новые запросы читали бы
таблицу целиком.

- `ix_entries_type_seq` — «вопросы всех задач по возрастанию `seq`»: выдача открытых
  вопросов участника идёт поперёк задач, и индекс по `(task_id, type)` ей не помогает,
  потому что начинается с задачи.
- `ix_entries_question_payload` — частичный GIN по нагрузке **вопросов**: фильтр по
  адресату это `payload -> 'addressees' @> '["name"]'`. Частичный, а не по всей
  таблице: вопросов в деле единицы на сотни записей, и полный GIN платил бы за каждую
  подшивку строки ради выборки, которая касается одного типа.

Обе — обычные `CREATE INDEX` без `CONCURRENTLY`: миграции применяются отдельным шагом
на остановленном контуре (`docker compose run --rm migrate`), а блокировка на таблице
в пустой или небольшой установке стоит миллисекунды. `CONCURRENTLY` потребовал бы
выхода из транзакции миграции — цена, которая здесь ничего не покупает.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2b6c04a91df"
down_revision: str | None = "a7d3e9f1c5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUESTION_ONLY = sa.text("type = 'question'")


def upgrade() -> None:
    op.create_index("ix_entries_type_seq", "entries", ["type", "seq"])
    op.create_index(
        "ix_entries_question_payload",
        "entries",
        ["payload"],
        postgresql_using="gin",
        postgresql_where=_QUESTION_ONLY,
    )


def downgrade() -> None:
    op.drop_index("ix_entries_question_payload", table_name="entries")
    op.drop_index("ix_entries_type_seq", table_name="entries")
