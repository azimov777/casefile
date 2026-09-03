"""search indexes

Revision ID: c1f8a3d60b72
Revises: b9c5d2e7a410
Create Date: 2026-09-04 03:00:00.000000+00:00

Индексы под запросы отбора задач (задача 25). Схема таблиц не меняется: вычисляемые
признаки колонками не становятся — они считаются из связей и дела (`CONCEPT.md`, 4.3),
и колонка была бы вторым местом, где живёт правда.

- `ix_tasks_queue_id_number` — порядок списка по умолчанию: «очередь, номер задачи».
  Номер вынут из ключа выражением `split_part(key, '-', 2)::bigint`, потому что
  отдельной колонки под него нет, а строковое сравнение поставило бы `TRK-10` перед
  `TRK-2`. Выражение неизменяемо (`split_part` и приведение к `bigint` — обе функции
  `IMMUTABLE`), иначе индекс по нему создать было бы нельзя.
- `ix_tasks_updated_at_id` — сортировка по времени обновления вместе с тайбрейкером:
  курсор идёт по паре, и индекс по одной колонке страницу не закрывает.
- `ix_tasks_title_trgm`, `ix_tasks_description_trgm` — вхождение подстроки (`text: ~`).
  Без них `ILIKE '%...%'` читает таблицу целиком.

`pg_trgm` заводится здесь же. Расширение помечено доверенным (`trusted`), поэтому его
создаёт владелец базы, а не суперпользователь, — в отличие от `pgcrypto`, который
проект сознательно не заводит миграцией (`docs/notes/db.md`).

Обе половины ревизии — обычные `CREATE INDEX` без `CONCURRENTLY`: миграции применяются
отдельным шагом на остановленном контуре, и блокировка на таблице в небольшой установке
стоит миллисекунды.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1f8a3d60b72"
down_revision: str | None = "b9c5d2e7a410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Номер задачи из ключа. Тот же текст лежит в `__table_args__` модели: индекс,
#: созданный миграцией и не объявленный в модели, всплывает в `alembic check` как
#: лишний и тонет среди известных ложных срабатываний (`docs/notes/db.md`).
_TASK_NUMBER = sa.text("(split_part(key, '-', 2)::bigint)")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index("ix_tasks_queue_id_number", "tasks", ["queue_id", _TASK_NUMBER])
    op.create_index("ix_tasks_updated_at_id", "tasks", ["updated_at", "id"])
    op.create_index(
        "ix_tasks_title_trgm",
        "tasks",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_tasks_description_trgm",
        "tasks",
        ["description"],
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_description_trgm", table_name="tasks")
    op.drop_index("ix_tasks_title_trgm", table_name="tasks")
    op.drop_index("ix_tasks_updated_at_id", table_name="tasks")
    op.drop_index("ix_tasks_queue_id_number", table_name="tasks")
    # Расширение остаётся: его могли завести не мы, и снятие унесло бы чужие индексы.
