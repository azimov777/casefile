"""directions

Revision ID: 3cc02e043842
Revises: a9cb1ec147c4
Create Date: 2026-10-06 11:30:00.000000+00:00

Направления (TRK#57; решения владельца `TRK#16`, `TRK#17`; TRK-555):
бесконечная часть работы внутри проекта — карточка, атрибуты, дело и архив.

- таблица `directions` — карточка: `project_id`, `key` (канонический, в нижнем регистре),
  `title`, `description` не длиннее 320 знаков (`ck_directions_description_length`),
  `archived_at`, автор и времена. Ключ уникален внутри проекта — `uq_directions_project_id_key`;
  родительского направления нет (`TRK#17`);
- таблица `direction_attributes` — нынешние значения атрибутов направления, имя уникально
  внутри направления без учёта регистра — индекс по `lower(name)` тем же текстом, что в
  модели;
- `entries.direction_id` — третий владелец записи дела: `ck_entries_one_owner` теперь
  считает три колонки, номер `no` уникален и внутри направления
  (`uq_entries_direction_id_no`). Новых типов записей нет: дело направления пишет те же,
  что дело проекта.

Строки не трогаются: направлений до этой ревизии не было, записи задач и проектов
удовлетворяют новой проверке. Имена объектов не квалифицированы схемой — приём архива
переноса установки гоняет миграции во временной схеме (TRK#202).

Откат снимает колонку и таблицы и возвращает проверку двух владельцев. Если в деле
какого-то направления есть записи, откат отказывает на этой проверке: у такой записи после
снятия колонки не осталось бы владельца, а удалить её нельзя — записи неизменяемы.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3cc02e043842"
down_revision: str | None = "a9cb1ec147c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Уникальность имени атрибута без учёта регистра: то же выражение, что в модели
#: (`app/db/models/attribute.py`).
NAME_INDEX = "uq_direction_attributes_direction_id_lower_name"

#: Предел описания — `MAX_DIRECTION_DESCRIPTION_LENGTH` на день ревизии. Литералом, а не
#: импортом: ревизия обязана делать то, что делала в день написания.
DESCRIPTION_LIMIT = 320


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


def upgrade() -> None:
    op.create_table(
        "directions",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
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
        sa.CheckConstraint(
            f"char_length(description) <= {DESCRIPTION_LIMIT}",
            name=op.f("ck_directions_description_length"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_directions_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directions")),
        sa.UniqueConstraint("project_id", "key", name=op.f("uq_directions_project_id_key")),
    )
    op.create_table(
        "direction_attributes",
        sa.Column("direction_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["direction_id"],
            ["directions.id"],
            name=op.f("fk_direction_attributes_direction_id_directions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_direction_attributes")),
    )
    op.create_index(
        NAME_INDEX,
        "direction_attributes",
        ["direction_id", sa.text("lower(name)")],
        unique=True,
    )

    op.add_column("entries", sa.Column("direction_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_entries_direction_id_directions"),
        "entries",
        "directions",
        ["direction_id"],
        ["id"],
    )
    op.drop_constraint(op.f("ck_entries_one_owner"), "entries", type_="check")
    op.create_check_constraint(
        op.f("ck_entries_one_owner"),
        "entries",
        "num_nonnulls(task_id, project_id, direction_id) = 1",
    )
    op.create_unique_constraint(
        op.f("uq_entries_direction_id_no"), "entries", ["direction_id", "no"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_entries_direction_id_no"), "entries", type_="unique")
    op.drop_constraint(op.f("ck_entries_one_owner"), "entries", type_="check")
    op.drop_constraint(op.f("fk_entries_direction_id_directions"), "entries", type_="foreignkey")
    op.drop_column("entries", "direction_id")
    # После снятия колонки: запись направления остаётся без владельца, и проверка двух
    # владельцев на ней отказывает — откат не проходит, пока такие записи есть.
    op.create_check_constraint(
        op.f("ck_entries_one_owner"), "entries", "num_nonnulls(task_id, project_id) = 1"
    )
    op.drop_index(NAME_INDEX, table_name="direction_attributes")
    op.drop_table("direction_attributes")
    op.drop_table("directions")
