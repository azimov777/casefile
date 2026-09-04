"""Ключ идемпотентности: запись о вызове, который уже был выполнен."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel
from app.domain.idempotency import FINGERPRINT_LENGTH, MAX_KEY_LENGTH


class IdempotencyKey(BaseModel):
    """Ключ, отпечаток запроса и ответ, который повтор обязан получить снова.

    Автора строки хранить незачем — его называет токен, и `CreatedByMixin` здесь был бы
    второй, расходящейся с ним версией того же факта.

    ## Уникальность — единственное, что защищает от гонки

    Ограничение на пару `(token_id, key)` не украшение схемы, а сам механизм: два
    одновременных повтора одного ключа сходятся на этом индексе. Второй `INSERT`
    **ждёт** на нём, пока первая транзакция не закончится, и дальше либо получает
    нарушение уникальности (первая зафиксировалась — значит, ответ уже есть и его надо
    отдать), либо вставляется сам (первая откатилась — значит, работу надо сделать).
    Проверка «поищи и вставь, если нет» на её месте была бы зелёной в тестах и
    дырявой в бою: два запроса проходят такую проверку одновременно.

    Пара, а не один ключ: ключи живут в паре с токеном (`CONCEPT.md`, 4.5), и
    одинаковые ключи разных агентов независимы.

    ## Ответ хранится целиком, включая секреты

    Повтор обязан вернуть **тот же** ответ, а не собрать похожий: у выпуска токена в
    ответе лежит секрет, и второй раз его взять неоткуда — в `tokens` только хеш.
    Поэтому строка живёт сутки (`KEY_TTL`) и удаляется попутно при записи следующей:
    хранить секрет дольше, чем нужно повтору, — плата без выгоды.
    """

    __tablename__ = "idempotency_keys"

    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(MAX_KEY_LENGTH), nullable=False)
    #: Имя операции: `operation_id` маршрута REST или имя инструмента MCP. Входит и в
    #: отпечаток — колонка нужна затем, чтобы отказ мог назвать операцию, за которой
    #: ключ закреплён, а разбор инцидента не сводился к сравнению двух хешей.
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(FINGERPRINT_LENGTH), nullable=False)
    #: Статус ответа, с которым он ушёл в первый раз. У REST маршрут объявляет тот же
    #: статус сам, поэтому при повторе он совпадает по построению; колонка нужна, чтобы
    #: строка была самодостаточной при разборе инцидента и чтобы у MCP, где статуса нет
    #: вовсе, это было видно значением NULL, а не догадкой.
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    #: Тело первого ответа. Пусто ровно до конца транзакции, которая заняла ключ:
    #: строка и созданный ею объект фиксируются вместе, поэтому чужому запросу пустой
    #: ответ не виден никогда. `none_as_null` обязателен — без него в колонке оказалось
    #: бы значение JSON `null`, и `IS NULL` перестал бы находить незаполненные строки.
    response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        default=None,
    )

    __table_args__ = (
        UniqueConstraint("token_id", "key", name="uq_idempotency_keys_token_id_key"),
        # Индекс под попутную уборку: устаревшие ключи снимает `DELETE ... WHERE
        # created_at < ...` на каждой записи нового ключа, и без индекса эта уборка
        # превратилась бы в полный проход по таблице на каждом создающем запросе.
        Index("ix_idempotency_keys_created_at", "created_at"),
    )
