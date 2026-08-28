"""workflows

Revision ID: d4f9a1b2c3e4
Revises: f372e87bb785
Create Date: 2026-08-28 12:00:00.000000+00:00

Существующим очередям нужен процесс сразу после миграции: `workflow_id` на
`queue_issue_types` в итоге обязательный. Для каждой очереди создаётся совместимый
воркфлоу со всеми доступными ей статусами и переходом «из любого» в каждый статус.
Так уже заведённая задача не оказывается вне графа, а дальнейшее ужесточение процесса
делается обычным редактором.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4f9a1b2c3e4"
down_revision: str | None = "f372e87bb785"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("queue_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("initial_status_id", sa.Uuid(), nullable=False),
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
            ["initial_status_id"],
            ["statuses.id"],
            name=op.f("fk_workflows_initial_status_id_statuses"),
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["queues.id"],
            name=op.f("fk_workflows_queue_id_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
        sa.UniqueConstraint("id", "queue_id", name=op.f("uq_workflows_id_queue_id")),
        sa.UniqueConstraint("queue_id", "name", name=op.f("uq_workflows_queue_id_name")),
    )
    op.create_table(
        "workflow_statuses",
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("status_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            name=op.f("ck_workflow_statuses_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["status_id"],
            ["statuses.id"],
            name=op.f("fk_workflow_statuses_status_id_statuses"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_statuses_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_statuses")),
        sa.UniqueConstraint(
            "workflow_id",
            "status_id",
            name=op.f("uq_workflow_statuses_workflow_id_status_id"),
        ),
    )
    op.create_index(
        "ix_workflow_statuses_status_id",
        "workflow_statuses",
        ["status_id"],
        unique=False,
    )
    op.create_table(
        "transitions",
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("from_status_id", sa.Uuid(), nullable=True),
        sa.Column("to_status_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "required_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "requires_resolution",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            name=op.f("ck_transitions_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["from_status_id"],
            ["statuses.id"],
            name=op.f("fk_transitions_from_status_id_statuses"),
        ),
        sa.ForeignKeyConstraint(
            ["to_status_id"],
            ["statuses.id"],
            name=op.f("fk_transitions_to_status_id_statuses"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_transitions_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transitions")),
        sa.UniqueConstraint(
            "workflow_id",
            "from_status_id",
            "to_status_id",
            "name",
            name=op.f("uq_transitions_workflow_id_from_status_id_to_status_id_name"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_transitions_from_status_id",
        "transitions",
        ["from_status_id"],
        unique=False,
    )
    op.create_index(
        "ix_transitions_to_status_id",
        "transitions",
        ["to_status_id"],
        unique=False,
    )

    op.add_column("queue_issue_types", sa.Column("workflow_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_queue_issue_types_workflow_id_workflows"),
        "queue_issue_types",
        "workflows",
        ["workflow_id", "queue_id"],
        ["id", "queue_id"],
    )
    op.create_index(
        "ix_queue_issue_types_workflow_id",
        "queue_issue_types",
        ["workflow_id"],
        unique=False,
    )

    # Старый контур позволял удалить все доступные статусы категории `done`. В таком
    # состоянии корректный граф построить невозможно, поэтому только для затронутых
    # очередей создаётся локальный технический статус. UUID очереди в ключе исключает
    # столкновение с пользовательским локальным каталогом без циклов и угадывания
    # суффикса в миграции.
    op.execute(
        sa.text(
            """
            INSERT INTO statuses
                (id, key, name, is_active, queue_id, category, created_at, updated_at)
            SELECT gen_random_uuid(),
                   'workflow_done_' || replace(q.id::text, '-', ''),
                   'Done', true, q.id, 'done', clock_timestamp(), clock_timestamp()
            FROM queues AS q
            WHERE NOT EXISTS (
                SELECT 1
                FROM statuses AS s
                WHERE s.category = 'done'
                  AND (s.queue_id IS NULL OR s.queue_id = q.id)
            )
            """
        )
    )

    # До появления воркфлоу резолюция не была связана с категорией статуса. Миграция
    # приводит старые строки к новому инварианту: у незавершённых задач снимает
    # резолюцию, а закрытым без исхода ставит честную локальную резолюцию
    # «не указано», не выдавая её за пользовательское `done`.
    op.execute(
        sa.text(
            """
            INSERT INTO resolutions
                (id, key, name, is_active, queue_id, created_at, updated_at)
            SELECT gen_random_uuid(),
                   'workflow_legacy_' || replace(q.id::text, '-', ''),
                   'Legacy outcome (unspecified)', true, q.id,
                   clock_timestamp(), clock_timestamp()
            FROM queues AS q
            WHERE EXISTS (
                SELECT 1
                FROM issues AS i
                JOIN statuses AS s ON s.id = i.status_id
                WHERE i.queue_id = q.id
                  AND s.category = 'done'
                  AND i.resolution_id IS NULL
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE issues AS i
            SET resolution_id = r.id,
                version = i.version + 1,
                updated_at = clock_timestamp()
            FROM statuses AS s, resolutions AS r
            WHERE s.id = i.status_id
              AND s.category = 'done'
              AND i.resolution_id IS NULL
              AND r.queue_id = i.queue_id
              AND r.key = 'workflow_legacy_' || replace(i.queue_id::text, '-', '')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE issues AS i
            SET resolution_id = NULL,
                version = i.version + 1,
                updated_at = clock_timestamp()
            FROM statuses AS s
            WHERE s.id = i.status_id
              AND s.category <> 'done'
              AND i.resolution_id IS NOT NULL
            """
        )
    )

    # Один совместимый процесс на очередь. В отличие от новых очередей, где сервис
    # создаёт строгий простой шаблон, миграция не имеет права внезапно запретить уже
    # работавшую смену статуса, поэтому ребро «из любого» ведёт в каждый доступный узел.
    op.execute(
        sa.text(
            """
            INSERT INTO workflows (id, queue_id, name, initial_status_id, created_at, updated_at)
            SELECT gen_random_uuid(), q.id, 'Default workflow', q.default_status_id,
                   clock_timestamp(), clock_timestamp()
            FROM queues AS q
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT w.id AS workflow_id,
                       s.id AS status_id,
                       (row_number() OVER (
                           PARTITION BY w.id ORDER BY s.created_at, s.id
                       ) - 1)::integer AS position
                FROM workflows AS w
                JOIN statuses AS s ON s.queue_id IS NULL OR s.queue_id = w.queue_id
            )
            INSERT INTO workflow_statuses
                (id, workflow_id, status_id, position, created_at, updated_at)
            SELECT gen_random_uuid(), workflow_id, status_id, position,
                   clock_timestamp(), clock_timestamp()
            FROM ranked
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT w.id AS workflow_id,
                       s.id AS status_id,
                       s.key AS status_key,
                       s.category AS category,
                       (row_number() OVER (
                           PARTITION BY w.id ORDER BY s.created_at, s.id
                       ) - 1)::integer AS position
                FROM workflows AS w
                JOIN statuses AS s ON s.queue_id IS NULL OR s.queue_id = w.queue_id
            )
            INSERT INTO transitions
                (id, workflow_id, from_status_id, to_status_id, name, required_fields,
                 requires_resolution, position, created_at, updated_at)
            SELECT gen_random_uuid(), workflow_id, NULL, status_id,
                   'Move to ' || status_key, '[]'::jsonb,
                   category = 'done', position, clock_timestamp(), clock_timestamp()
            FROM ranked
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE queue_issue_types AS binding
            SET workflow_id = workflow.id
            FROM workflows AS workflow
            WHERE workflow.queue_id = binding.queue_id
              AND workflow.name = 'Default workflow'
            """
        )
    )
    op.alter_column("queue_issue_types", "workflow_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    op.drop_index("ix_queue_issue_types_workflow_id", table_name="queue_issue_types")
    op.drop_constraint(
        op.f("fk_queue_issue_types_workflow_id_workflows"),
        "queue_issue_types",
        type_="foreignkey",
    )
    op.drop_column("queue_issue_types", "workflow_id")
    op.drop_index("ix_transitions_to_status_id", table_name="transitions")
    op.drop_index("ix_transitions_from_status_id", table_name="transitions")
    op.drop_table("transitions")
    op.drop_index("ix_workflow_statuses_status_id", table_name="workflow_statuses")
    op.drop_table("workflow_statuses")
    op.drop_table("workflows")
