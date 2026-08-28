"""boards sprints and ranks

Revision ID: 0c08b4f46fd2
Revises: ee156ee934e4
Create Date: 2026-08-28 13:30:55.699771+00:00

Доски, их колонки, спринты и ранг карточки. Переноса данных нет — ни одной из этих
сущностей до ревизии не существовало; у задач появляется пустая колонка `sprint_id`.

## Из автогенерации удалены снятия CHECK у перечислений

`alembic revision --autogenerate` дописал `op.drop_constraint` для
`ck_actors_actor_type`, `ck_fields_field_value_type`, `ck_issue_links_issue_link_type`,
`ck_issues_issue_priority`, `ck_outbox_events_outbox_status`,
`ck_portfolios_project_status`, `ck_projects_project_status` и
`ck_statuses_status_category` — по строке на каждое перечисление в схеме, ни одно из
которых к этой ревизии отношения не имеет. Это известное ложное срабатывание
(`docs/notes/db.md`): имя ограничения от `string_enum` вычисляется соглашением об
именах только при компиляции DDL, и до этого момента для сравнения оно «безымянное».
Оставить эти строки значило бы молча снять с колонок проверку допустимых значений.

## Доска ссылается на сохранённый фильтр, а не хранит условия

`boards.saved_filter_id` обязателен и объявлен без `ondelete`: удалить фильтр, на
котором стоит доска, база не даст. Доска без источника перестала бы что-либо
показывать, а объяснить это по строке в базе было бы нечем.

## Статус в колонке держится составным ключом

У `board_column_statuses` внешний ключ на колонку составной — на пару `(id, board_id)`,
для чего у `board_columns` заведено `UNIQUE (id, board_id)`. Простой ключ только по
`column_id` позволил бы разложить статус в колонку чужой доски, и уникальность
`(board_id, status_id)` перестала бы что-либо значить. Отдельного ключа `board_id →
boards.id` у таблицы нет намеренно: он был бы вторым путём к тому же значению, а каскад
приходит по цепочке `boards → board_columns → board_column_statuses`.

## Активный спринт держит частичный уникальный индекс

`uq_sprints_board_id_active` уникален по `board_id` при `state = 'active'`. Проверка в
сценарии этого не даёт: два одновременных запуска прошли бы её оба, и доска осталась бы
с двумя активными спринтами, а `sprint: current` — без единственного ответа.

## Ранг — отдельная таблица с `bigint`

Позиция совмещена с виртуальной шкалой: у задачи без строки в `issue_ranks` позиция
вычисляется из `created_at` как микросекунды эпохи, умноженные на 1024 (около 1.8e18).
`integer` этого не вмещает, поэтому колонка `bigint`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0c08b4f46fd2"
down_revision: str | None = "ee156ee934e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "boards",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("saved_filter_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["saved_filter_id"],
            ["saved_filters.id"],
            name=op.f("fk_boards_saved_filter_id_saved_filters"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boards")),
    )
    op.create_index("ix_boards_created_at_id", "boards", ["created_at", "id"], unique=False)
    op.create_index("ix_boards_saved_filter_id", "boards", ["saved_filter_id"], unique=False)

    op.create_table(
        "board_columns",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("wip_limit", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0",
            name=op.f("ck_board_columns_position_non_negative"),
        ),
        sa.CheckConstraint(
            "wip_limit IS NULL OR wip_limit > 0",
            name=op.f("ck_board_columns_wip_limit_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["boards.id"],
            name=op.f("fk_board_columns_board_id_boards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_columns")),
        sa.UniqueConstraint("board_id", "name", name=op.f("uq_board_columns_board_id_name")),
        # Нужен составному внешнему ключу из `board_column_statuses`.
        sa.UniqueConstraint("id", "board_id", name=op.f("uq_board_columns_id_board_id")),
    )

    op.create_table(
        "sprints",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("goal", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "planned",
                "active",
                "completed",
                name="sprint_state",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'planned'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["boards.id"],
            name=op.f("fk_sprints_board_id_boards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sprints")),
        sa.UniqueConstraint("board_id", "name", name=op.f("uq_sprints_board_id_name")),
    )
    op.create_index(
        "ix_sprints_board_id_created_at_id",
        "sprints",
        ["board_id", "created_at", "id"],
        unique=False,
    )
    op.create_index("ix_sprints_state", "sprints", ["state"], unique=False)
    op.create_index(
        "uq_sprints_board_id_active",
        "sprints",
        ["board_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "board_column_statuses",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("column_id", sa.Uuid(), nullable=False),
        sa.Column("status_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["column_id", "board_id"],
            ["board_columns.id", "board_columns.board_id"],
            name="fk_board_column_statuses_column_id_board_columns",
            ondelete="CASCADE",
        ),
        # Каскад по статусу нужен удалению очереди: оно уносит её локальные статусы.
        # Осмысленный случай — удаление статуса, разложенного в колонку, — отклоняет
        # сценарий (`app/services/catalogs.py`), иначе колонка молча осталась бы пустой.
        sa.ForeignKeyConstraint(
            ["status_id"],
            ["statuses.id"],
            name=op.f("fk_board_column_statuses_status_id_statuses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_column_statuses")),
        sa.UniqueConstraint(
            "board_id",
            "status_id",
            name=op.f("uq_board_column_statuses_board_id_status_id"),
        ),
    )
    op.create_index(
        "ix_board_column_statuses_column_id",
        "board_column_statuses",
        ["column_id"],
        unique=False,
    )
    op.create_index(
        "ix_board_column_statuses_status_id",
        "board_column_statuses",
        ["status_id"],
        unique=False,
    )

    op.create_table(
        "issue_ranks",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["boards.id"],
            name=op.f("fk_issue_ranks_board_id_boards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_issue_ranks_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_ranks")),
        sa.UniqueConstraint("board_id", "issue_id", name=op.f("uq_issue_ranks_board_id_issue_id")),
    )
    op.create_index(
        "ix_issue_ranks_board_id_position",
        "issue_ranks",
        ["board_id", "position"],
        unique=False,
    )
    op.create_index("ix_issue_ranks_issue_id", "issue_ranks", ["issue_id"], unique=False)

    # Спринт задачи. Без `ondelete`: спринт с задачами удалить нельзя, а каскад унёс бы
    # принадлежность молча.
    op.add_column("issues", sa.Column("sprint_id", sa.Uuid(), nullable=True))
    op.create_index("ix_issues_sprint_id", "issues", ["sprint_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_issues_sprint_id_sprints"),
        "issues",
        "sprints",
        ["sprint_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_issues_sprint_id_sprints"), "issues", type_="foreignkey")
    op.drop_index("ix_issues_sprint_id", table_name="issues")
    op.drop_column("issues", "sprint_id")

    op.drop_index("ix_issue_ranks_issue_id", table_name="issue_ranks")
    op.drop_index("ix_issue_ranks_board_id_position", table_name="issue_ranks")
    op.drop_table("issue_ranks")

    op.drop_index("ix_board_column_statuses_status_id", table_name="board_column_statuses")
    op.drop_index("ix_board_column_statuses_column_id", table_name="board_column_statuses")
    op.drop_table("board_column_statuses")

    op.drop_index(
        "uq_sprints_board_id_active",
        table_name="sprints",
        postgresql_where=sa.text("state = 'active'"),
    )
    op.drop_index("ix_sprints_state", table_name="sprints")
    op.drop_index("ix_sprints_board_id_created_at_id", table_name="sprints")
    op.drop_table("sprints")

    op.drop_table("board_columns")
    op.drop_index("ix_boards_saved_filter_id", table_name="boards")
    op.drop_index("ix_boards_created_at_id", table_name="boards")
    op.drop_table("boards")
