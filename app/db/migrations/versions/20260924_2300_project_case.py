"""project case

Revision ID: 5c1d8e7a2b90
Revises: 3b8e6d2f9a41
Create Date: 2026-09-24 23:00:00.000000+00:00

Дело проекта (`CONCEPT.md`, 3.2 и 3.4; TRK-153, TRK-156): запись принадлежит задаче
**или** проекту. Таблица записей остаётся одна — лента, сквозной `seq`, оповещение
ждущих и триггер неизменяемости достаются делу проекта без второго журнала (решение в
деле TRK-156).

- `entries.task_id` допускает `NULL`: у записи проекта задачи нет;
- `entries.project_id` — владелец записи проекта, внешний ключ без `ondelete`, как у
  `task_id`: проекты не удаляются, а если это однажды случится, база откажет;
- `ck_entries_one_owner` — владелец ровно один: `num_nonnulls` считает непустые;
- `uq_entries_project_id_no` — номер записи уникален внутри проекта, как `(task_id, no)`
  внутри задачи. `NULL` в уникальности различны, поэтому записи задач (`project_id IS
  NULL`) её не задевают, и наоборот.

Строки не трогаются: записи задач уже удовлетворяют проверке. Имена объектов не
квалифицированы схемой — приём архива переноса установки гоняет миграции во временной
схеме (`app/services/archive.py`).

Откат снимает колонку и возвращает `NOT NULL`. Если в деле какого-то проекта уже есть
записи, откат отказывает на `SET NOT NULL`: удалить их нельзя (записи неизменяемы), а
молча потерять — тем более.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c1d8e7a2b90"
down_revision: str | None = "3b8e6d2f9a41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("entries", "task_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("entries", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_entries_project_id_projects"), "entries", "projects", ["project_id"], ["id"]
    )
    op.create_check_constraint(
        op.f("ck_entries_one_owner"), "entries", "num_nonnulls(task_id, project_id) = 1"
    )
    op.create_unique_constraint(op.f("uq_entries_project_id_no"), "entries", ["project_id", "no"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_entries_project_id_no"), "entries", type_="unique")
    op.drop_constraint(op.f("ck_entries_one_owner"), "entries", type_="check")
    op.drop_constraint(op.f("fk_entries_project_id_projects"), "entries", type_="foreignkey")
    # Раньше снятия колонки: записи проекта держат `task_id IS NULL`, и `SET NOT NULL`
    # на них отказывает — откат не проходит, пока такие записи есть.
    op.alter_column("entries", "task_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("entries", "project_id")
