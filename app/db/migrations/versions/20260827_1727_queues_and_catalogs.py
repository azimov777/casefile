"""queues and catalogs

Revision ID: 5c4dcd2b7f21
Revises: a8ce71dd4ff7
Create Date: 2026-08-27 17:27:00.000000+00:00

Ревизия правлена руками после автогенерации, и правки не косметические:

1. Внешние ключи очереди на её справочники по умолчанию вынесены из `create_table` в
   отдельные `op.create_foreign_key`. Причина — кольцо ссылок: очередь ссылается на
   статус и тип, локальный статус ссылается на очередь. В моделях эти ключи помечены
   `use_alter=True`, а `CREATE TABLE` такие ключи не создаёт вовсе, поэтому без явного
   ALTER очередь осталась бы без внешних ключей — молча, схема выглядела бы рабочей.
2. Удалена строка `op.drop_constraint("ck_actors_actor_type")`, которую автогенерация
   добавляет сама. Это ложное срабатывание: имя ограничения, созданного `string_enum`,
   вычисляется соглашением об именах только при компиляции DDL, и сравнение по имени
   считает его отсутствующим в метаданных. Оставить строку — снять с `actors.type`
   проверку допустимых значений. Подробности — в `docs/notes/db.md`.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "5c4dcd2b7f21"
down_revision: str | None = "a8ce71dd4ff7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Начальный набор справочников. Те же значения объявлены константами
# `INITIAL_STATUSES`, `INITIAL_ISSUE_TYPES` и `INITIAL_RESOLUTIONS` в
# `app/domain/catalogs.py`. Здесь они записаны литералами сознательно: миграция не
# должна зависеть от кода приложения, который со временем меняется, — иначе накат
# старой ревизии на новом коде однажды создаст не то, что создавал раньше.
# Совпадение двух списков стережёт тест `tests/test_catalogs_service.py`.
INITIAL_STATUSES = [
    {"key": "open", "name": "Открыт", "category": "new", "is_active": True},
    {"key": "in_progress", "name": "В работе", "category": "in_progress", "is_active": True},  # noqa: RUF001
    {"key": "closed", "name": "Закрыт", "category": "done", "is_active": True},
]
INITIAL_ISSUE_TYPES = [
    {"key": "task", "name": "Задача", "icon": "task", "is_active": True},
    {"key": "bug", "name": "Баг", "icon": "bug", "is_active": True},
    {"key": "epic", "name": "Эпик", "icon": "epic", "is_active": True},
]
INITIAL_RESOLUTIONS = [
    {"key": "done", "name": "Сделано", "is_active": True},
    {"key": "rejected", "name": "Отклонено", "is_active": True},
    {"key": "duplicate", "name": "Дубликат", "is_active": True},
]


def _ordered(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Проставляет записям начального набора возрастающие отметки создания.

    Без этого все строки одной вставки получают одинаковый `now()` — время начала
    транзакции, — и порядок «открыт → в работе → закрыт» превращается в порядок
    случайных UUID: справочник в конфигурации очереди каждый раз выглядел бы иначе.
    Сортировка справочников идёт по паре `(created_at, id)`, поэтому достаточно
    развести отметки на микросекунду.

    `updated_at` проставляется тем же значением: иначе он берётся из `now()` — времени
    начала транзакции, — и у записи, которую никто не менял, время изменения
    оказывается раньше времени создания.
    """
    base = datetime.now(UTC)
    stamped: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        moment = base + timedelta(microseconds=index)
        stamped.append(row | {"created_at": moment, "updated_at": moment})
    return stamped


def upgrade() -> None:
    op.create_table(
        "queues",
        sa.Column("key", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_issue_number", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("default_issue_type_id", sa.Uuid(), nullable=False),
        sa.Column("default_status_id", sa.Uuid(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "last_issue_number >= 0", name=op.f("ck_queues_last_issue_number_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["actors.id"], name=op.f("fk_queues_owner_id_actors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queues")),
        sa.UniqueConstraint("key", name=op.f("uq_queues_key")),
    )

    issue_types = op.create_table(
        "issue_types",
        sa.Column("icon", sa.String(length=64), server_default=sa.text("''"), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            name=op.f("fk_issue_types_queue_id_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_types")),
        # NULLS NOT DISTINCT — не украшение: без него PostgreSQL считает NULL-ы
        # различными, и ограничение пропустило бы сколько угодно глобальных записей
        # с одним ключом. Требует PostgreSQL 15+.
        sa.UniqueConstraint(
            "queue_id",
            "key",
            name=op.f("uq_issue_types_queue_id_key"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    resolutions = op.create_table(
        "resolutions",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            name=op.f("fk_resolutions_queue_id_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolutions")),
        sa.UniqueConstraint(
            "queue_id",
            "key",
            name=op.f("uq_resolutions_queue_id_key"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    statuses = op.create_table(
        "statuses",
        # Категория — VARCHAR с CHECK, а не тип PostgreSQL: см. `string_enum` в
        # `app/db/base.py`. `create_constraint=True` обязателен, иначе проверки
        # допустимых значений не будет вовсе, а схема будет выглядеть правильной.
        sa.Column(
            "category",
            sa.Enum(
                "new",
                "in_progress",
                "done",
                name="status_category",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            name=op.f("fk_statuses_queue_id_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statuses")),
        sa.UniqueConstraint(
            "queue_id",
            "key",
            name=op.f("uq_statuses_queue_id_key"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    op.create_table(
        "queue_issue_types",
        sa.Column("queue_id", sa.Uuid(), nullable=False),
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
            ["issue_type_id"],
            ["issue_types.id"],
            name=op.f("fk_queue_issue_types_issue_type_id_issue_types"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["queue_id"],
            ["queues.id"],
            name=op.f("fk_queue_issue_types_queue_id_queues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queue_issue_types")),
        sa.UniqueConstraint(
            "queue_id", "issue_type_id", name=op.f("uq_queue_issue_types_queue_id_issue_type_id")
        ),
    )

    # Замыкание кольца ссылок. Без `ondelete` — это поведение NO ACTION: удалить
    # статус или тип, назначенный очереди по умолчанию, база не даст, но удаление
    # самой очереди пройдёт (NO ACTION проверяется в конце оператора, когда ссылка
    # из удаляемой очереди уже исчезла, а RESTRICT — сразу и потому падал бы).
    op.create_foreign_key(
        op.f("fk_queues_default_issue_type_id_issue_types"),
        "queues",
        "issue_types",
        ["default_issue_type_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_queues_default_status_id_statuses"),
        "queues",
        "statuses",
        ["default_status_id"],
        ["id"],
    )

    # Начальный набор справочников создаётся схемой, а не командой инициализации:
    # без единого статуса и типа задачи нельзя создать даже первую очередь, и свежая
    # база оказалась бы нерабочей — в том числе в тестах. Записи глобальные
    # (`queue_id` не задан) и ничем не отличаются от заведённых пользователем:
    # их можно переименовать, отключить и удалить.
    op.bulk_insert(statuses, _ordered(INITIAL_STATUSES))
    op.bulk_insert(issue_types, _ordered(INITIAL_ISSUE_TYPES))
    op.bulk_insert(resolutions, _ordered(INITIAL_RESOLUTIONS))


def downgrade() -> None:
    # Кольцо разрывается первым: пока очередь ссылается на статус, таблицу статусов
    # не удалить.
    op.drop_constraint(op.f("fk_queues_default_status_id_statuses"), "queues", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_queues_default_issue_type_id_issue_types"), "queues", type_="foreignkey"
    )
    op.drop_table("queue_issue_types")
    op.drop_table("statuses")
    op.drop_table("resolutions")
    op.drop_table("issue_types")
    op.drop_table("queues")
