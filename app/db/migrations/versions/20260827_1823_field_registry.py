"""field registry

Revision ID: 1ec6deb4a5aa
Revises: 5c4dcd2b7f21
Create Date: 2026-08-27 18:23:12.840798+00:00

Ревизия правлена руками после автогенерации:

1. Удалены строки `op.drop_constraint("ck_actors_actor_type")` и
   `op.drop_constraint("ck_statuses_status_category")`, которые автогенерация
   добавляет сама. Это ложное срабатывание: имя ограничения, созданного
   `string_enum`, вычисляется соглашением об именах только при компиляции DDL, и
   сравнение по имени считает его отсутствующим в метаданных. Оставить строки —
   снять с `actors.type` и `statuses.category` проверку допустимых значений.
   Подробности — в `docs/notes/db.md`.
2. Добавлен индекс по `field_issue_types.issue_type_id`. Уникальное ограничение
   начинается с `field_id` и обратный вопрос — «какие поля ограничены этим типом
   задачи» — не обслуживает, а он задаётся при каждой попытке удалить тип.

Начальных полей ревизия не создаёт намеренно: набор атрибутов задачи зависит от
процесса, и угадывать его за пользователя нечем. Свежая база работоспособна и без
единого кастомного поля — в отличие от справочников, без которых нельзя создать очередь.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1ec6deb4a5aa"
down_revision: str | None = "5c4dcd2b7f21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fields",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        # Тип значения — VARCHAR с CHECK, а не тип PostgreSQL: см. `string_enum` в
        # `app/db/base.py`. `create_constraint=True` обязателен, иначе проверки
        # допустимых значений не будет вовсе, а схема будет выглядеть правильной.
        sa.Column(
            "value_type",
            sa.Enum(
                "string",
                "text",
                "number",
                "date",
                "datetime",
                "boolean",
                "enum",
                "actor",
                "issue",
                name="field_value_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("is_multiple", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("default_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("queue_id", sa.Uuid(), nullable=True),
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
            name=op.f("fk_fields_queue_id_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fields")),
        # NULLS NOT DISTINCT — то же, что у справочников: без него PostgreSQL считает
        # NULL-ы различными, и глобальных полей с одним ключом можно было бы завести
        # сколько угодно. Требует PostgreSQL 15+.
        sa.UniqueConstraint(
            "queue_id",
            "key",
            name=op.f("uq_fields_queue_id_key"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    op.create_table(
        "field_issue_types",
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("issue_type_id", sa.Uuid(), nullable=False),
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
            ["field_id"],
            ["fields.id"],
            name=op.f("fk_field_issue_types_field_id_fields"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issue_type_id"],
            ["issue_types.id"],
            name=op.f("fk_field_issue_types_issue_type_id_issue_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_field_issue_types")),
        sa.UniqueConstraint(
            "field_id",
            "issue_type_id",
            name=op.f("uq_field_issue_types_field_id_issue_type_id"),
        ),
    )
    op.create_index(
        op.f("ix_field_issue_types_issue_type_id"),
        "field_issue_types",
        ["issue_type_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_field_issue_types_issue_type_id"), table_name="field_issue_types")
    op.drop_table("field_issue_types")
    op.drop_table("fields")
