"""remark and resolution entries

Revision ID: b7d41e2a9c53
Revises: a1c8f2d47b06
Create Date: 2026-09-06 20:00:00.000000+00:00

Заведены типы записей `remark` и `resolution`: человек говорит «вышло не то», не
переписывая ТЗ, а разбор называет исход и задачу, в которую ушла работа (`CONCEPT.md`,
3.4).

Зачем: сказать о недовольстве было негде. Разделы неизменяемы от `open`, вопроса агент
не задаст (он не знает, что человек чем-то недоволен), а сказанное в чате умирает вместе
с сессией. Замечание — запись дела, поэтому оно хранится столько же, сколько дело, и
приезжает в пакете преемника целиком, пока не разобрано.

Миграция делает ровно одно: заменяет ограничение CHECK на список типов двумя новыми
значениями. Индексов не добавляет: и «замечания без резолюции», и счёт принятых в работу
идут по `ix_entries_task_id_type`, который уже есть.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d41e2a9c53"
down_revision: str | None = "a1c8f2d47b06"
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
)

TYPES_AFTER = (*TYPES_BEFORE, "remark", "resolution")


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
    (`CONCEPT.md`, 3.4). Падение на непустой установке — честный отказ: оно говорит,
    что откатывать уже поздно.
    """
    _replace_constraint(TYPES_BEFORE)
