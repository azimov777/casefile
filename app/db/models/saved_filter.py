"""Сохранённый фильтр: именованный запрос, который переиспользуют фронт, MCP и автоматика.

Хранится **описание** отбора, а не его результат: список задач меняется каждую минуту, а
вопрос «мои просроченные» остаётся тем же. Поэтому фильтр — это либо строка на языке
запросов, либо структурный фильтр, и ровно одно из двух.

Почему не оба сразу: два описания одного отбора немедленно порождают вопрос «какое из них
главное», а ответа на него нет. Расхождение при этом было бы молчаливым — фильтр
продолжал бы работать, просто не так, как показан в интерфейсе. Ограничение держит база,
а не только сценарий: строка с двумя описаниями не должна возникать никаким путём.

Функции языка вычисляются в момент выполнения, а не сохранения: `assignee: me()` в общем
фильтре означает «мои» для каждого, кто его запускает, а `deadline: <= today()` — сегодня,
а не в день создания. Ради этого фильтр и хранится текстом.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.db.models.actor import Actor


class SavedFilter(BaseModel):
    """Именованный отбор задач, принадлежащий актору."""

    __tablename__ = "saved_filters"
    __table_args__ = (
        # Имя уникально у владельца, а не на всю установку: два человека вправе
        # назвать свои фильтры «Мои задачи», и запрещать это значило бы заставлять
        # второго придумывать имя из-за первого.
        UniqueConstraint("owner_id", "name"),
        # Основной запрос — «фильтры этого актора» страницами; курсорная пагинация
        # проекта идёт по паре `(created_at, id)`, поэтому индекс составной.
        Index("ix_saved_filters_owner_id_created_at_id", "owner_id", "created_at", "id"),
        # Ровно один источник отбора. `num_nonnulls` вместо пары условий: одно
        # выражение читается как правило, а не как его следствие.
        CheckConstraint(
            "num_nonnulls(query, structured_filter) = 1",
            name="single_source",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Пустая строка вместо NULL, как у описания очереди и задачи: «описания нет» и
    # «описание пустое» — одно состояние, и два способа его записать разъехались бы.
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default=text("''"),
        nullable=False,
    )

    # Без `ondelete`: акторов не удаляют, их отключают, и фильтр обязан пережить
    # отключение своего владельца — им могли пользоваться и другие.
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actors.id"), nullable=False)

    #: Строка на языке запросов. NULL, если фильтр структурный.
    query: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)

    #: Структурный фильтр в каноническом виде: `{"terms": [...]}`. NULL, если фильтр
    #: текстовый. Колонка названа не `filter`: `FILTER` — ключевое слово SQL, и хотя
    #: SQLAlchemy закавычило бы имя само, читать такие запросы в логе невозможно.
    #:
    #: `none_as_null=True` — не украшение, а единственное, что делает NULL настоящим
    #: NULL. По умолчанию тип JSON пишет питоновский `None` как **значение** JSON
    #: `null`, и колонка перестаёт быть пустой: `num_nonnulls` насчитает два источника
    #: там, где заполнен один, а `IS NULL` не найдёт ничего. Сбой молчаливый ровно до
    #: первой проверки, которая на пустоту опирается.
    structured_filter: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        default=None,
        nullable=True,
    )

    #: Порядок выдачи (`["-deadline", "priority"]`). Часть фильтра, а не вызова: «мои
    #: горящие» без сортировки по дедлайну отвечают на другой вопрос.
    sort: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    # Ключ владельца нужен каждой странице списка, а `selectin` берёт всех акторов
    # страницы одним запросом и переиспользует уже загруженных.
    owner: Mapped[Actor] = relationship(lazy="selectin")
