"""task links

Revision ID: b9c5d2e7a410
Revises: e2b6c04a91df
Create Date: 2026-09-04 01:00:00.000000+00:00

Связи между задачами: одна строка на связь, видимая с обеих сторон (задача 24).

В колонке `kind` лежат только канонические виды — `parent`, `blocks`, `relates`;
обратные (`child`, `blocked_by`) вычисляются при чтении и в базу не попадают. Это
закреплено ограничением CHECK, а не только кодом: без канонизации уникальная тройка
`(source_id, target_id, kind)` не поймала бы дубликат, потому что «A blocks B» и
«B blocked_by A» — разные строки про одну связь.

Отсутствия циклов в схеме нет и быть не может: это свойство графа целиком, а не строки.
Проверку держит `app/services/links.py`, цена названа в `docs/notes/links.md`.

Внешние ключи без `ON DELETE`: задачи не удаляются — как и у записей дела. Каскад унёс
бы связи молча, оставив в делах обеих задач записи о связи, которой больше нет.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c5d2e7a410"
down_revision: str | None = "e2b6c04a91df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "links",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "blocks",
                "parent",
                "relates",
                name="link_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
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
        sa.CheckConstraint("source_id <> target_id", name=op.f("ck_links_no_self_link")),
        sa.CheckConstraint(
            "kind IN ('blocks', 'parent', 'relates')",
            name=op.f("ck_links_stored_link_kind"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["tasks.id"], name=op.f("fk_links_source_id_tasks")),
        sa.ForeignKeyConstraint(["target_id"], ["tasks.id"], name=op.f("fk_links_target_id_tasks")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_links")),
        sa.UniqueConstraint(
            "source_id",
            "target_id",
            "kind",
            name=op.f("uq_links_source_id_target_id_kind"),
        ),
    )
    op.create_index("ix_links_source_id_kind", "links", ["source_id", "kind"], unique=False)
    op.create_index("ix_links_target_id_kind", "links", ["target_id", "kind"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_links_target_id_kind", table_name="links")
    op.drop_index("ix_links_source_id_kind", table_name="links")
    op.drop_table("links")
