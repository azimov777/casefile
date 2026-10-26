"""decision_review

Revision ID: b3f7a91c24d8
Revises: 50535bc472dd
Create Date: 2026-10-26 20:00:00.000000+00:00

Проверка решений человеком (TRK-755, TRK-756): запись `decision_review` в деле проекта
или области — исход `confirmed`, `rejected` или `removed` для одного решения. Тип хранится
VARCHAR с ограничением CHECK (`string_enum`), поэтому ограничение заменяется.

Строки не трогаются и данные не переносятся: решения, подшитые до этой ревизии, читаются
`review_state: unconfirmed` сами, потому что состояние считается при чтении из записей
проверки. Триггер `entries_immutable` не затронут. Имена объектов не квалифицированы
схемой — приём архива переноса гоняет миграции во временной схеме (TRK#202).

Откат возвращает прежнее ограничение; если в деле есть запись `decision_review`, откат
отказывает на проверке типа: записи неизменяемы, и откат схемы историю не отменяет.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3f7a91c24d8"
down_revision: str | None = "50535bc472dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения типа записи по соглашению `NAMING_CONVENTION` (`app/db/base.py`).
TYPE_CONSTRAINT = "ck_entries_entry_type"

#: Типы записей на день ревизии — литералом, а не из перечисления: ревизия обязана делать
#: то, что делала в день написания.
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
    "acceptance",
    "warning",
    "conclusion",
    "attached",
    "detached",
    "closed",
)

TYPES_AFTER = (*TYPES_BEFORE, "decision_review")


def _replace_type_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK (`string_enum`)."""
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {TYPE_CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {TYPE_CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    _replace_type_constraint(TYPES_AFTER)


def downgrade() -> None:
    _replace_type_constraint(TYPES_BEFORE)
