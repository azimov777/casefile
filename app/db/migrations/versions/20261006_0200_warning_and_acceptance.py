"""warning and acceptance entries

Revision ID: 4b8e2d7c1f90
Revises: 4b8e1d6a2c57
Create Date: 2026-10-06 02:00:00.000000+00:00

Заведены типы записей `warning` и `acceptance` (TRK-561, решение TRK-561#11).

`warning` — служебная запись закрытия: задача закрыта с проверками `partial` или
`unverifiable`, и нагрузка называет их номера и исходы. `acceptance` — запись агента или
человека: недостаток принят. Предупреждение открыто, пока после него нет `acceptance`
или `remark` (`CONCEPT.md`, 3.4).

Зачем: у вердикта было два исхода, и недоделанную или невыполнимую проверку закрывали
`passed` с оговоркой рядом (TRK-545#11). Новые исходы лежат в JSON нагрузки и миграции
не требуют; новые типы записей — требуют: тип записи хранится VARCHAR с ограничением
CHECK (`string_enum`).

Миграция делает ровно одно: заменяет ограничение CHECK на список типов двумя новыми
значениями. Индексов не добавляет: и открытые предупреждения, и реакции на них идут по
`ix_entries_task_id_type`, который уже есть.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4b8e2d7c1f90"
down_revision: str | None = "4b8e1d6a2c57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_entries_entry_type"

TYPES_BEFORE = (
    "summary",
    "decision",
    "attempt",
    "finding",
    "artifact",
    "question",
    "answer",
    "verdict",
    "note",
    "created",
    "status_changed",
    "section_changed",
    "field_changed",
    "assignee_changed",
    "link_added",
    "link_removed",
    "remark",
    "resolution",
    "attribute_created",
    "attribute_changed",
    "attribute_removed",
    "archived",
    "restored",
    "moved",
)

TYPES_AFTER = (*TYPES_BEFORE, "acceptance", "warning")


def _replace_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK (`string_enum`)."""
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    _replace_constraint(TYPES_AFTER)


def downgrade() -> None:
    """Сужает ограничение обратно и падает, если такие записи уже подшиты.

    Молча снести их нельзя: дело неизменяемо, и откат схемы историю не отменяет
    (`CONCEPT.md`, 3.4). Падение на непустой установке — честный отказ: оно говорит,
    что откатывать уже поздно.
    """
    _replace_constraint(TYPES_BEFORE)
