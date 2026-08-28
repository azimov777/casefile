"""saved filters and search indexes

Revision ID: 7b1c40e9d5a2
Revises: 3f4520fae0b9
Create Date: 2026-08-28 13:10:00.000000+00:00

Таблица сохранённых фильтров и индексы под поиск. Переноса данных нет: ни того, ни
другого до этой ревизии не было.

## `pg_trgm` — доверенное расширение, и в этом вся разница

В заметках проекта уже записано, почему `pgcrypto` не заводится миграцией: `CREATE
EXTENSION` требует прав суперпользователя и ломается в управляемых базах. С `pg_trgm`
это не так: начиная с PostgreSQL 13 оно помечено доверенным (`trusted`), и создать его
может владелец базы. Проект живёт на 17 в обоих контурах, поэтому строка здесь
допустима — но правило не отменяет: недоверенное расширение по-прежнему заводится
руками, а не миграцией.

Расширение нужно ради `gin_trgm_ops`: полнотекстовый поиск идёт `ILIKE '%...%'`, а
шаблон, начинающийся с подстановки, не ложится ни на один обычный индекс. Триграммный
GIN покрывает именно этот случай. Цена названа прямо: индекс крупнее B-tree, а запрос
короче трёх символов он не ускоряет вовсе — триграмм в нём просто нет.

## Ограничение единственного источника держит база

У сохранённого фильтра заполнена ровно одна из колонок `query` и `structured_filter`.
Проверять это только в сценарии было бы недостаточно: строка с двумя описаниями одного
отбора не должна возникать никаким путём, включая правку руками в консоли.

Из сгенерированной ревизии удалены строки `op.drop_constraint(... type_="check")` для
колонок-перечислений (`ck_actors_actor_type`, `ck_fields_field_value_type`,
`ck_issue_links_issue_link_type`, `ck_issues_issue_priority`,
`ck_outbox_events_outbox_status`, `ck_statuses_status_category`): автогенерация
приписывает их каждой ревизии, а оставленные — молча снимают проверку допустимых
значений (`docs/notes/db.md`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b1c40e9d5a2"
down_revision: str | None = "3f4520fae0b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "saved_filters",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("structured_filter", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "sort",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            "num_nonnulls(query, structured_filter) = 1",
            name=op.f("ck_saved_filters_single_source"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["actors.id"],
            name=op.f("fk_saved_filters_owner_id_actors"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_filters")),
        sa.UniqueConstraint("owner_id", "name", name=op.f("uq_saved_filters_owner_id_name")),
    )
    op.create_index(
        "ix_saved_filters_owner_id_created_at_id",
        "saved_filters",
        ["owner_id", "created_at", "id"],
        unique=False,
    )

    op.create_index(
        "ix_issues_tags",
        "issues",
        ["tags"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_issues_summary_trgm",
        "issues",
        ["summary"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"summary": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_issues_description_trgm",
        "issues",
        ["description"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_comments_body_trgm",
        "comments",
        ["body"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"body": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_comments_body_trgm", table_name="comments", postgresql_using="gin")
    op.drop_index("ix_issues_description_trgm", table_name="issues", postgresql_using="gin")
    op.drop_index("ix_issues_summary_trgm", table_name="issues", postgresql_using="gin")
    op.drop_index("ix_issues_tags", table_name="issues", postgresql_using="gin")
    op.drop_index("ix_saved_filters_owner_id_created_at_id", table_name="saved_filters")
    op.drop_table("saved_filters")
    # Расширение не удаляется: его мог завести кто-то ещё, и снятие оборвало бы чужие
    # индексы. Откат схемы не обязан вычищать общие объекты базы.
