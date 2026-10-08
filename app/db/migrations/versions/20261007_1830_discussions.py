"""discussions

Revision ID: 5d0c8e3a71b4
Revises: ed61a83a9be0
Create Date: 2026-10-07 18:30:00.000000+00:00

Обсуждения (решение проекта `TRK#51`; TRK-669): переписка человека и агентов по одному
узкому вопросу, своё дело с итогом и привязанные задачи.

- таблица `discussions` — карточка: `project_id`, `number` — номер внутри проекта
  (`uq_discussions_project_id_number`, адрес `TRK~7`), `title`, `status` — `open` или
  `closed` (`ck_discussions_discussion_status`), `closed_at`, автор и времена;
- таблица `discussion_tasks` — привязка задачи к обсуждению: пара уникальна
  (`uq_discussion_tasks_discussion_id_task_id`), индекс по задаче
  (`ix_discussion_tasks_task_id`) — от неё идут признаки карточки и проверки переходов;
- `entries.discussion_id` — четвёртый владелец записи дела: `ck_entries_one_owner`
  теперь считает четыре колонки, номер `no` уникален и внутри обсуждения
  (`uq_entries_discussion_id_no`);
- типы записей: `conclusion` — итог обсуждения, служебные `attached` и `detached` —
  привязка задачи и её снятие, `closed` — закрытие обсуждения. Тип хранится VARCHAR с
  ограничением CHECK (`string_enum`), поэтому ограничение заменяется.

Строки не трогаются: обсуждений до этой ревизии не было, записи задач, проектов и
областей удовлетворяют новой проверке владельца. Имена объектов не квалифицированы
схемой — приём архива переноса гоняет миграции во временной схеме (TRK#202).

Откат снимает колонку, таблицы и новые типы. Если в деле какого-то обсуждения есть
записи или записи новых типов подшиты, откат отказывает на проверке владельца или типа:
записи неизменяемы, и откат схемы историю не отменяет.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d0c8e3a71b4"
down_revision: str | None = "ed61a83a9be0"
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
)

TYPES_AFTER = (*TYPES_BEFORE, "conclusion", "attached", "detached", "closed")


def _author_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_by_kind",
            sa.Enum(
                "agent",
                "human",
                "tracker",
                name="author_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _replace_type_constraint(types: Sequence[str]) -> None:
    """Меняет список допустимых типов заменой ограничения CHECK (`string_enum`)."""
    values = ", ".join(f"'{item}'" for item in types)
    op.execute(f"ALTER TABLE entries DROP CONSTRAINT {TYPE_CONSTRAINT}")
    op.execute(f"ALTER TABLE entries ADD CONSTRAINT {TYPE_CONSTRAINT} CHECK (type IN ({values}))")


def upgrade() -> None:
    op.create_table(
        "discussions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "closed",
                name="discussion_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        *_author_columns(),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_discussions_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discussions")),
        sa.UniqueConstraint("project_id", "number", name=op.f("uq_discussions_project_id_number")),
    )
    op.create_table(
        "discussion_tasks",
        sa.Column("discussion_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        *_author_columns(),
        sa.ForeignKeyConstraint(
            ["discussion_id"],
            ["discussions.id"],
            name=op.f("fk_discussion_tasks_discussion_id_discussions"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_discussion_tasks_task_id_tasks")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discussion_tasks")),
        sa.UniqueConstraint(
            "discussion_id", "task_id", name=op.f("uq_discussion_tasks_discussion_id_task_id")
        ),
    )
    op.create_index(
        op.f("ix_discussion_tasks_task_id"), "discussion_tasks", ["task_id"], unique=False
    )

    op.add_column("entries", sa.Column("discussion_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_entries_discussion_id_discussions"),
        "entries",
        "discussions",
        ["discussion_id"],
        ["id"],
    )
    op.drop_constraint(op.f("ck_entries_one_owner"), "entries", type_="check")
    op.create_check_constraint(
        op.f("ck_entries_one_owner"),
        "entries",
        "num_nonnulls(task_id, project_id, area_id, discussion_id) = 1",
    )
    op.create_unique_constraint(
        op.f("uq_entries_discussion_id_no"), "entries", ["discussion_id", "no"]
    )
    _replace_type_constraint(TYPES_AFTER)


def downgrade() -> None:
    # Сначала типы: запись нового типа отказывает здесь, пока колонка и таблицы ещё целы.
    _replace_type_constraint(TYPES_BEFORE)
    op.drop_constraint(op.f("uq_entries_discussion_id_no"), "entries", type_="unique")
    op.drop_constraint(op.f("ck_entries_one_owner"), "entries", type_="check")
    op.drop_constraint(op.f("fk_entries_discussion_id_discussions"), "entries", type_="foreignkey")
    op.drop_column("entries", "discussion_id")
    # После снятия колонки: запись обсуждения остаётся без владельца, и проверка трёх
    # владельцев на ней отказывает — откат не проходит, пока такие записи есть.
    op.create_check_constraint(
        op.f("ck_entries_one_owner"), "entries", "num_nonnulls(task_id, project_id, area_id) = 1"
    )
    op.drop_index(op.f("ix_discussion_tasks_task_id"), table_name="discussion_tasks")
    op.drop_table("discussion_tasks")
    op.drop_table("discussions")
