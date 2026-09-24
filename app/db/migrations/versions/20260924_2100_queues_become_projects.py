"""queues become projects

Revision ID: 3b8e6d2f9a41
Revises: 7f4089f291b8
Create Date: 2026-09-24 21:00:00.000000+00:00

Очередь переименована в проект (`CONCEPT.md`, 3.2; TRK-150, TRK-152): таблица `queues`
становится `projects`, колонка `tasks.queue_id` — `tasks.project_id`, и вместе с ними
все имена, которые соглашение об именах (`app/db/base.py`, `NAMING_CONVENTION`) выводит
из имени таблицы и колонки: первичный ключ, уникальность ключа, проверка вида автора,
внешний ключ задачи и оба индекса задач.

Только переименование: строки не трогаются, и ключи задач, счётчики `last_task_number`,
записи дела и ссылки `TRK-42#3` остаются теми же байтами. `ALTER ... RENAME` меняет
каталог, а не данные, поэтому миграция мгновенна на любом объёме.

Имена объектов не квалифицированы схемой намеренно: приём архива переноса установки
(`app/services/archive.py`) гоняет миграции во временной схеме, поставив её первой в
`search_path`, и архив формата v0.3 с таблицей `queues` доходит до `projects` именно этой
ревизией.

Откат возвращает прежние имена — тоже без потерь.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3b8e6d2f9a41"
down_revision: str | None = "7f4089f291b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ограничения по таблицам: (таблица после переименования, старое имя, новое имя).
_CONSTRAINTS = (
    ("projects", "pk_queues", "pk_projects"),
    ("projects", "uq_queues_key", "uq_projects_key"),
    ("projects", "ck_queues_author_kind", "ck_projects_author_kind"),
    ("tasks", "fk_tasks_queue_id_queues", "fk_tasks_project_id_projects"),
)

#: Индексы, заведённые отдельно от ограничений.
_INDEXES = (
    ("ix_tasks_queue_id_status", "ix_tasks_project_id_status"),
    ("ix_tasks_queue_id_number", "ix_tasks_project_id_number"),
)


def upgrade() -> None:
    op.rename_table("queues", "projects")
    op.alter_column("tasks", "queue_id", new_column_name="project_id")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")


def downgrade() -> None:
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    op.alter_column("tasks", "project_id", new_column_name="queue_id")
    op.rename_table("projects", "queues")
