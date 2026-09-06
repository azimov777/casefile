"""field changed entry

Revision ID: a1c8f2d47b06
Revises: f3b90c47ad15
Create Date: 2026-09-06 17:00:00.000000+00:00

Заведён тип записи `field_changed` — правка обвязки задачи (`tags`, `priority`), то,
что меняется в любом незакрытом статусе и не имеет своей записи (`CONCEPT.md`, 3.4).

Зачем: лента журнала это лента записей дела, и изменение, не оставившее записи, не
доходит до внешнего мира вовсе (`CONCEPT.md`, 4.1). Теги и приоритет были исключением,
и открытый экран молча показывал устаревшее значение.

Миграция делает ровно одно: заменяет ограничение CHECK на список типов с новым
значением. Данные не трогаются: старых записей этого типа не бывает, а переписывать
историю миграция права не имеет — дело неизменяемо.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c8f2d47b06"
down_revision: str | None = "f3b90c47ad15"
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
    "assignee_changed",
    "link_added",
    "link_removed",
)

TYPES_AFTER = (*TYPES_BEFORE, "field_changed")


def _replace_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK.

    Перечисления в проекте — VARCHAR с CHECK, а не native enum (`app/db/base.py`,
    `string_enum`), ровно ради этой операции: `ALTER TYPE ... ADD VALUE` нельзя
    использовать в той же транзакции, где значение добавлено.
    """
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    _replace_constraint(TYPES_AFTER)


def downgrade() -> None:
    """Сужает ограничение обратно и падает, если такие записи уже подшиты.

    Молча снести их нельзя: дело неизменяемо, и откат схемы историю не отменяет
    (`CONCEPT.md`, 3.4). Падение на непустой установке — это честный отказ, а не
    поломка: оно говорит, что откатывать уже поздно.
    """
    _replace_constraint(TYPES_BEFORE)
