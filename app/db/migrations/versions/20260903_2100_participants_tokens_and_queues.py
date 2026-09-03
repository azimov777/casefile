"""participants, tokens and queues

Revision ID: c4a1f7b93e28
Revises: 6f1c0a3d5b27
Create Date: 2026-09-03 21:00:00.000000+00:00

Фундамент трекера для агентов (задача 21). Акторы и токены доступа, оставшиеся после
задачи 20, заменяются участниками и токенами с наборами; появляются очереди.

Почему отдельной ревизией, а не правкой предыдущей: ревизия `6f1c0a3d5b27` уже могла
быть накатана — контур разработки поднимался после задачи 20. Переписанный `upgrade`
применённой ревизии не выполняется повторно, и такая база молча осталась бы со старой
схемой. `downgrade` здесь восстанавливает прежние таблицы целиком, включая системного
актора: иначе откат оставлял бы базу в состоянии, которого не было никогда.

Что изменилось по существу, а не по именам:

- у участника нет ни признака активности, ни рода `system`: отключать некого (доступ
  снимается отзывом токена), а служебные действия подписывает автор рода `tracker`,
  которому строка в реестре не нужна;
- у токена появился набор (`task` / `main`) и участник стал необязательным: токен без
  участника — общий агентский, подпись ему даёт заголовок `X-Actor-Label`;
- у каждой строки реестров появился автор: род и подпись двумя колонками.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a1f7b93e28"
down_revision: str | None = "6f1c0a3d5b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Системный актор ревизии `6f1c0a3d5b27`: нужен только откату, чтобы вернуть базу
# ровно в то состояние, в котором она была до этой ревизии.
LEGACY_SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _author_kind() -> sa.Enum:
    """Перечисление автора: своё для каждой таблицы, одинаковое по содержимому.

    Перечисления в проекте хранятся как VARCHAR с CHECK, а не как тип PostgreSQL
    (см. `string_enum` в `app/db/base.py`). `create_constraint=True` обязателен: по
    умолчанию он выключен, и колонка молча остаётся без всякой проверки значений —
    схема при этом выглядит правильной.
    """
    return sa.Enum(
        "agent",
        "human",
        "tracker",
        name="author_kind",
        native_enum=False,
        create_constraint=True,
        length=16,
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "participants",
        sa.Column(
            "kind",
            sa.Enum(
                "human",
                "agent",
                name="participant_kind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("created_by_kind", _author_kind(), nullable=False),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participants")),
        sa.UniqueConstraint("name", name=op.f("uq_participants_name")),
    )
    op.create_table(
        "queues",
        sa.Column("key", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("last_task_number", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by_kind", _author_kind(), nullable=False),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queues")),
        sa.UniqueConstraint("key", name=op.f("uq_queues_key")),
    )
    op.create_table(
        "tokens",
        # Пустой участник — это общий агентский токен, а не потерянная ссылка.
        sa.Column("participant_id", sa.Uuid(), nullable=True),
        sa.Column(
            "scope",
            sa.Enum(
                "task",
                "main",
                name="token_scope",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_kind", _author_kind(), nullable=False),
        sa.Column("created_by_signature", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participants.id"],
            name=op.f("fk_tokens_participant_id_participants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_tokens_token_hash")),
    )
    op.create_index(op.f("ix_tokens_participant_id"), "tokens", ["participant_id"], unique=False)

    op.drop_index(op.f("ix_api_tokens_actor_id"), table_name="api_tokens")
    op.drop_table("api_tokens")
    op.drop_table("actors")


def downgrade() -> None:
    actors = op.create_table(
        "actors",
        sa.Column(
            "type",
            sa.Enum(
                "human",
                "agent",
                "system",
                name="actor_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actors")),
        sa.UniqueConstraint("key", name=op.f("uq_actors_key")),
    )
    op.create_table(
        "api_tokens",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["actors.id"],
            name=op.f("fk_api_tokens_actor_id_actors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index(op.f("ix_api_tokens_actor_id"), "api_tokens", ["actor_id"], unique=False)
    op.bulk_insert(
        actors,
        [
            {
                "id": LEGACY_SYSTEM_ACTOR_ID,
                "type": "system",
                "key": "system",
                "display_name": "System",
                "is_active": True,
            }
        ],
    )

    op.drop_index(op.f("ix_tokens_participant_id"), table_name="tokens")
    op.drop_table("tokens")
    op.drop_table("queues")
    op.drop_table("participants")
