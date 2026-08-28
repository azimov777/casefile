"""remove sprints

Revision ID: 4a7c9e1b53d8
Revises: bc656a96d68b
Create Date: 2026-08-28 21:57:00.000000+00:00

Убирает сущность «спринт» целиком: таблицу `sprints` и колонку `issues.sprint_id`.
Решение владельца — планирование спринтами продукту не нужно (задача 14a).

## Это необратимая потеря данных, и отдельная ревизия — про неё

Ревизия отделена от чистки кода намеренно: в установке, где спринты уже заводили,
`downgrade` вернёт **схему**, но не состав спринтов — ни их названия, ни принадлежность
задач восстанавливать неоткуда. Колонка вернётся пустой, таблица — тоже. Поэтому накат
на такой установке требует решения человека, а не «применилось вместе с остальными»;
об этом сказано в README.

## Порядок обратен порядку создания, иначе база откажет

Сначала снимается внешний ключ `issues.sprint_id → sprints.id`, потом уходит колонка и
только потом таблица: пока ключ стоит, `DROP TABLE sprints` отклоняется как нарушение
ссылочной целостности. Других входящих ключей у таблицы нет — уведомления, журнал
срабатываний и история ссылаются на задачи, а не на спринты, поэтому каскадов из-за
удаления не будет (проверено по `\\d sprints` до наката).

## CHECK перечисления уезжает вместе с таблицей

`ck_sprints_sprint_state` снимать отдельно не нужно: `DROP TABLE` уносит и проверку.
Это не то же самое, что известное ложное срабатывание автогенерации по CHECK у
перечислений (`docs/notes/db.md`) — там речь о чужих таблицах, которые ревизия не
трогает.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a7c9e1b53d8"
down_revision: str | None = "bc656a96d68b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("fk_issues_sprint_id_sprints"), "issues", type_="foreignkey")
    op.drop_index("ix_issues_sprint_id", table_name="issues")
    op.drop_column("issues", "sprint_id")

    op.drop_index(
        "uq_sprints_board_id_active",
        table_name="sprints",
        postgresql_where=sa.text("state = 'active'"),
    )
    op.drop_index("ix_sprints_state", table_name="sprints")
    op.drop_index("ix_sprints_board_id_created_at_id", table_name="sprints")
    op.drop_table("sprints")


def downgrade() -> None:
    """Возвращает схему, но не данные: спринты и их состав восстанавливать неоткуда."""
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

    op.add_column("issues", sa.Column("sprint_id", sa.Uuid(), nullable=True))
    op.create_index("ix_issues_sprint_id", "issues", ["sprint_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_issues_sprint_id_sprints"),
        "issues",
        "sprints",
        ["sprint_id"],
        ["id"],
    )
