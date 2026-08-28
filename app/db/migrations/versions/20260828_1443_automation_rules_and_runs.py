"""automation rules and runs

Revision ID: d2e08534c9f9
Revises: 0c08b4f46fd2
Create Date: 2026-08-28 14:43:09.078415+00:00

Состояние правил автоматики и журнал их срабатываний. Переноса данных нет: ни одной из
этих сущностей до ревизии не существовало, а сами правила живут кодом и в базу не
переезжают.

## Из автогенерации удалены снятия CHECK у перечислений

`alembic revision --autogenerate` дописал `op.drop_constraint` для `ck_actors_actor_type`,
`ck_fields_field_value_type`, `ck_issue_links_issue_link_type`, `ck_issues_issue_priority`,
`ck_outbox_events_outbox_status`, `ck_portfolios_project_status`,
`ck_projects_project_status`, `ck_sprints_sprint_state` и `ck_statuses_status_category` —
по строке на каждое перечисление в схеме, ни одно из которых к этой ревизии отношения не
имеет. Это известное ложное срабатывание (`docs/notes/db.md`): имя ограничения от
`string_enum` вычисляется соглашением об именах только при компиляции DDL, и до этого
момента для сравнения оно «безымянное». Оставить эти строки значило бы молча снять с
колонок проверку допустимых значений.

## Строка правила не удаляется вместе с правилом

`automation_runs.rule_id` каскадный, и это осознанный выбор в паре с решением
синхронизации реестра **никогда не удалять** строку исчезнувшего из кода правила
(`app/services/automation.py`). Без второго первое унесло бы журнал в тот момент, когда
правило убрали из репозитория, — то есть ровно тогда, когда в журнал и приходят.

## У задачи в журнале `SET NULL`, а не каскад

Запись «правило закрыло TRK-7» осмысленна и после удаления TRK-7: она отвечает на
вопрос, что происходило с задачей, которой больше нет. Ссылка при этом обнуляется, а
ключ остаётся копией в `issue_key` — та же пара «ссылка плюс копия ключа», что у события
в outbox, и по той же причине.

## Время создания журнала ставит clock_timestamp()

Автодействие перебирает сотни задач в одной транзакции. С `now()` (время начала
транзакции) все записи пачки получили бы одну отметку, журнал показывался бы в порядке
случайных UUID, а окно лимита срабатываний считалось бы от условной границы. То же
отступление и по той же причине, что у `changelog_entries` и `outbox_events`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2e08534c9f9"
down_revision: str | None = "0c08b4f46fd2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("rule_key", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("queue_id", sa.Uuid(), nullable=True),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("saved_filter_id", sa.Uuid(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
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
            ["queue_id"],
            ["queues.id"],
            name=op.f("fk_automation_rules_queue_id_queues"),
        ),
        sa.ForeignKeyConstraint(
            ["saved_filter_id"],
            ["saved_filters.id"],
            name=op.f("fk_automation_rules_saved_filter_id_saved_filters"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_rules")),
        sa.UniqueConstraint("rule_key", name=op.f("uq_automation_rules_rule_key")),
    )
    op.create_index(
        "ix_automation_rules_created_at_id",
        "automation_rules",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_automation_rules_is_enabled_next_run_at",
        "automation_rules",
        ["is_enabled", "next_run_at"],
        unique=False,
    )

    op.create_table(
        "automation_runs",
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=64), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=True),
        sa.Column("issue_key", sa.String(length=128), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column(
            "trigger",
            sa.Enum(
                "event",
                "schedule",
                "manual",
                name="automation_run_trigger",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "success",
                "skipped",
                "failed",
                name="automation_run_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("initiator_id", sa.Uuid(), nullable=True),
        sa.Column("initiator_key", sa.String(length=64), nullable=True),
        sa.Column("chain_depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chain_depth >= 0",
            name=op.f("ck_automation_runs_chain_depth_not_negative"),
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name=op.f("ck_automation_runs_duration_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["initiator_id"],
            ["actors.id"],
            name=op.f("fk_automation_runs_initiator_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_automation_runs_issue_id_issues"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["automation_rules.id"],
            name=op.f("fk_automation_runs_rule_id_automation_rules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_runs")),
    )
    op.create_index(
        "ix_automation_runs_created_at_id",
        "automation_runs",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_automation_runs_issue_id_created_at",
        "automation_runs",
        ["issue_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_automation_runs_rule_id_issue_id_created_at",
        "automation_runs",
        ["rule_id", "issue_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_automation_runs_rule_id_issue_id_created_at", table_name="automation_runs")
    op.drop_index("ix_automation_runs_issue_id_created_at", table_name="automation_runs")
    op.drop_index("ix_automation_runs_created_at_id", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_automation_rules_is_enabled_next_run_at", table_name="automation_rules")
    op.drop_index("ix_automation_rules_created_at_id", table_name="automation_rules")
    op.drop_table("automation_rules")
