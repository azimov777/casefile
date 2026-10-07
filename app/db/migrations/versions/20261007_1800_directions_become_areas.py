"""directions become areas

Revision ID: ed61a83a9be0
Revises: 29c012062376
Create Date: 2026-10-07 18:00:00.000000+00:00

Направление переименовано в область (решение проекта `TRK#57`, раздел 2; TRK-675):
таблица `directions` становится `areas`, `direction_attributes` — `area_attributes`,
колонка ссылки на неё `direction_id` — `area_id` у задач, записей дела и атрибутов, и
вместе с ними все имена, которые соглашение об именах (`app/db/base.py`,
`NAMING_CONVENTION`) выводит из имени таблицы и колонки: первичные ключи, уникальности,
проверки, внешние ключи и индексы. Проверка `ck_entries_one_owner` имени не меняет, а
колонку в своём выражении PostgreSQL переименовывает сам.

Только переименование: строки не трогаются, и ключи, адреса `ПРОЕКТ/ключ`, ссылки
`ПРОЕКТ/ключ#N` и записи дела остаются теми же байтами. `ALTER ... RENAME` меняет
каталог, а не данные, поэтому миграция мгновенна на любом объёме.

Записи дела, подшитые до ревизии, хранят прежнее слово как написано: `field_changed` с
`payload.field = "direction"` и заголовки служебных записей дела области
(`Direction created`, `Direction archived`, `Direction restored`). Они не переводятся:
записи неизменяемы, и триггер `entries_immutable` откажет любому `UPDATE` — так же
остались записи о входе в снятый статус `waiting` (TRK-573). Читаются они как есть:
нагрузка отдаёт поле строкой, а факт описи — `null` вместо незнакомого значения
(`_as_enum`, `app/db/repositories/entries.py`). Решение — дело TRK-675.

Имена объектов не квалифицированы схемой намеренно: приём архива переноса установки
(`app/services/archive.py`) гоняет миграции во временной схеме, поставив её первой в
`search_path`, и архив выпуска с направлениями доходит до областей этой ревизией.

Откат возвращает прежние имена — тоже без потерь.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ed61a83a9be0"
down_revision: str | None = "29c012062376"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Таблицы: (прежнее имя, новое имя).
_TABLES = (("directions", "areas"), ("direction_attributes", "area_attributes"))

#: Колонки ссылки на область: (таблица после переименования, прежнее имя, новое имя).
_COLUMNS = (
    ("area_attributes", "direction_id", "area_id"),
    ("entries", "direction_id", "area_id"),
    ("tasks", "direction_id", "area_id"),
)

#: Ограничения: (таблица после переименования, прежнее имя, новое имя).
_CONSTRAINTS = (
    ("areas", "pk_directions", "pk_areas"),
    ("areas", "uq_directions_project_id_key", "uq_areas_project_id_key"),
    ("areas", "ck_directions_description_length", "ck_areas_description_length"),
    ("areas", "ck_directions_author_kind", "ck_areas_author_kind"),
    ("areas", "fk_directions_project_id_projects", "fk_areas_project_id_projects"),
    ("area_attributes", "pk_direction_attributes", "pk_area_attributes"),
    (
        "area_attributes",
        "fk_direction_attributes_direction_id_directions",
        "fk_area_attributes_area_id_areas",
    ),
    ("entries", "fk_entries_direction_id_directions", "fk_entries_area_id_areas"),
    ("entries", "uq_entries_direction_id_no", "uq_entries_area_id_no"),
    ("tasks", "fk_tasks_direction_id_directions", "fk_tasks_area_id_areas"),
)

#: Индексы, заведённые отдельно от ограничений.
_INDEXES = (
    ("uq_direction_attributes_direction_id_lower_name", "uq_area_attributes_area_id_lower_name"),
    ("ix_tasks_direction_id", "ix_tasks_area_id"),
)


def upgrade() -> None:
    for old, new in _TABLES:
        op.rename_table(old, new)
    for table, old, new in _COLUMNS:
        op.alter_column(table, old, new_column_name=new)
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")


def downgrade() -> None:
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    for table, old, new in _COLUMNS:
        op.alter_column(table, new, new_column_name=old)
    for old, new in reversed(_TABLES):
        op.rename_table(new, old)
