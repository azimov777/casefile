"""area_links

Revision ID: 39d463eb6de9
Revises: 3b9f4d192289
Create Date: 2026-10-25 20:25:18.836276+00:00

Связь области с областью `see_also` (TRK-732; слово владельца TRK~24#12): таблица
`area_links` — направленная пара «источник → цель» с обязательной причиной от 1 до 200
знаков. Пара уникальна (`uq_area_links_source_area_id_target_area_id`), связь с собой
отвергается (`ck_area_links_no_self_link`), предел причины держит
`ck_area_links_reason_length`; индекс по цели (`ix_area_links_target_area_id`) отвечает на
входящие связи. Строк до ревизии не было, существующие данные не трогаются. Имена объектов
не квалифицированы схемой — приём архива переноса гоняет миграции во временной схеме.

Откат снимает индекс и таблицу вместе со связями.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "39d463eb6de9"
down_revision: str | None = "3b9f4d192289"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "area_links",
        sa.Column("source_area_id", sa.Uuid(), nullable=False),
        sa.Column("target_area_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
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
            "char_length(reason) BETWEEN 1 AND 200", name=op.f("ck_area_links_reason_length")
        ),
        sa.CheckConstraint(
            "source_area_id <> target_area_id", name=op.f("ck_area_links_no_self_link")
        ),
        sa.ForeignKeyConstraint(
            ["source_area_id"], ["areas.id"], name=op.f("fk_area_links_source_area_id_areas")
        ),
        sa.ForeignKeyConstraint(
            ["target_area_id"], ["areas.id"], name=op.f("fk_area_links_target_area_id_areas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_area_links")),
        sa.UniqueConstraint(
            "source_area_id",
            "target_area_id",
            name=op.f("uq_area_links_source_area_id_target_area_id"),
        ),
    )
    op.create_index("ix_area_links_target_area_id", "area_links", ["target_area_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_area_links_target_area_id", table_name="area_links")
    op.drop_table("area_links")
