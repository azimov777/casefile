"""Состояние правил автоматики и журнал их срабатываний.

Правило — это код в репозитории (`app/automation/rules/`), и в базе от него лежит
только то, что меняется без перевыкладки: включённость, привязка к очереди, параметры,
источник отбора и время последнего запуска. Само поведение здесь не хранится и храниться
не должно — декларативный DSL в базе прямо исключён из объёма задачи.

## Почему строка правила переживает удаление правила из кода

Строку не удаляют при синхронизации реестра. Каскад унёс бы вместе с ней журнал
срабатываний — то есть ровно ту историю, ради которой в журнал и смотрят после того, как
правило убрали. Строка без объявления помечается недоступной (`automation_rule_unavailable`)
и не выполняется, но остаётся видимой в списке и в журнале.

Сам журнал такого правила живёт по своему, более короткому сроку хранения
(`TRACKER_RETENTION_ORPHAN_RUNS_DAYS`): вопрос «почему оно так сделало» задают, пока
правило есть. Строку правила чистка при этом не трогает — см. `app/services/retention.py`.

## Почему у срабатывания есть и ссылка на задачу, и её ключ

По той же причине, что у события в outbox: ссылка позволяет отобрать журнал по задаче,
а копия ключа переживает её удаление. У задачи каскад `SET NULL`, а не `CASCADE`: запись
«правило закрыло задачу TRK-7» осмысленна и после того, как TRK-7 удалили, — а вот
ссылка на несуществующую строку осмысленной уже не будет.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.actor import Actor
from app.db.models.queue import Queue
from app.db.models.saved_filter import SavedFilter
from app.domain.automation import RunStatus, RunTrigger

#: Совпадает с шаблоном ключа правила: латиница, цифры и подчёркивание, до 64 символов.
MAX_RULE_KEY_LENGTH = 64

#: Ключ задачи в журнале — та же длина, что у ключа объекта в outbox.
MAX_ISSUE_KEY_LENGTH = 128

#: Копия ключа актора: совпадает с длиной колонки в таблице акторов.
MAX_ACTOR_KEY_LENGTH = 64

#: Потолок текста ошибки в журнале. Тот же, что у `outbox_events.last_error`: колонке
#: нужна причина, а не дамп запроса с параметрами.
MAX_ERROR_LENGTH = 1000


class AutomationRule(BaseModel):
    """Состояние одного правила: включено ли, где работает, с какими параметрами.

    Одна строка на ключ правила. Два состояния одного правила для двух очередей могли бы
    показаться полезными, но тогда «включить правило» перестало бы иметь единственный
    смысл, а маршрут `/automation/rules/{key}` — единственный адресат. Нужны разные
    настройки для разных очередей — это разные правила в коде.
    """

    __tablename__ = "automation_rules"
    __table_args__ = (
        UniqueConstraint("rule_key"),
        Index("ix_automation_rules_created_at_id", "created_at", "id"),
        # Выборка планировщика целиком: «включённые, которым пришло время».
        Index("ix_automation_rules_is_enabled_next_run_at", "is_enabled", "next_run_at"),
    )

    rule_key: Mapped[str] = mapped_column(String(MAX_RULE_KEY_LENGTH), nullable=False)

    #: Выключено по умолчанию, и это главное свойство синхронизации реестра. Правило,
    #: приехавшее с новой выкладкой включённым, начало бы менять задачи в ту же минуту,
    #: когда его никто ещё не настроил и не прочитал.
    is_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    #: Очередь, которой ограничено правило. NULL — все очереди. Отбор по привязке идёт
    #: до вызова правила: иначе каждое правило обязано было бы помнить про неё само.
    #: Без `ondelete`: очередь нельзя удалить, пока в ней есть задачи, а привязанное к
    #: ней правило — такая же причина сначала разобраться, а потом удалять.
    queue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("queues.id"),
        default=None,
        nullable=True,
    )

    #: Параметры правила в том виде, в каком их проверила схема самого правила.
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    #: Сохранённый фильтр вместо объявленной в коде строки отбора. Только у автодействий;
    #: у остальных форм остаётся NULL. Без `ondelete`: удалить фильтр, на котором стоит
    #: правило, база не даст — правило молча перестало бы что-либо отбирать.
    saved_filter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("saved_filters.id"),
        default=None,
        nullable=True,
    )

    last_run_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)
    #: Когда автодействие можно брать в работу. NULL у триггеров и макросов — их
    #: планировщик не выбирает вовсе.
    next_run_at: Mapped[datetime | None] = mapped_column(default=None, nullable=True)

    queue: Mapped[Queue | None] = relationship(lazy="selectin")
    saved_filter: Mapped[SavedFilter | None] = relationship(lazy="selectin")


class AutomationRun(BaseModel):
    """Запись журнала срабатываний: правило, задача, результат, ошибка, время.

    Журнал пишется на каждое **рассмотренное** срабатывание, а не только на успешное.
    Вопрос «почему правило не сработало» задают чаще, чем «что оно сделало», и ответ на
    него должен читаться строкой в журнале, а не выводиться из её отсутствия. Поэтому у
    записи есть `status` и `reason`, а не только текст ошибки.

    На этих же строках держится защита от зацикливания: лимит «сколько раз правило
    сработало по этой задаче за окно времени» считается запросом сюда. Значит, запись
    обязана фиксироваться даже тогда, когда работа правила откатилась, — движок пишет её
    вне вложенной транзакции самого правила.
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        # Лимит срабатываний: «сколько раз это правило отработало по этой задаче за
        # окно». Порядок колонок повторяет условие запроса.
        Index(
            "ix_automation_runs_rule_id_issue_id_created_at",
            "rule_id",
            "issue_id",
            "created_at",
        ),
        # Журнал страницами: общий порядок пагинации проекта — пара `(created_at, id)`.
        Index("ix_automation_runs_created_at_id", "created_at", "id"),
        # «Что происходило с этой задачей» — отдельный вопрос, на который предыдущий
        # индекс не отвечает: он начинается с правила.
        Index("ix_automation_runs_issue_id_created_at", "issue_id", "created_at"),
        CheckConstraint("chain_depth >= 0", name="chain_depth_not_negative"),
        CheckConstraint("duration_ms >= 0", name="duration_not_negative"),
    )

    # Каскад: строку правила удаляют только вместе с решением забыть его историю.
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Копия ключа рядом со ссылкой — по той же причине, что `actor_key` в outbox:
    #: журнал читают и показывают пачками, и соединение ради одной строки там лишнее.
    rule_key: Mapped[str] = mapped_column(String(MAX_RULE_KEY_LENGTH), nullable=False)

    #: Задача, по которой сработало правило. NULL у срабатывания, не привязанного к
    #: задаче (событие доски), и у записи, чья задача уже удалена.
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"),
        default=None,
        nullable=True,
    )
    issue_key: Mapped[str | None] = mapped_column(
        String(MAX_ISSUE_KEY_LENGTH),
        default=None,
        nullable=True,
    )

    #: Событие, вызвавшее срабатывание. Без внешнего ключа — по той же причине, по
    #: которой его нет у самого события: строка outbox переживает удалённую задачу, но
    #: гарантий обратного порядка нет. С задачи 18 это уже не гипотеза: у очереди
    #: событий свой срок хранения, и он короче срока журнала не обязан быть.
    event_id: Mapped[uuid.UUID | None] = mapped_column(default=None, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)

    trigger: Mapped[RunTrigger] = mapped_column(
        string_enum(RunTrigger, name="automation_run_trigger", length=16),
        nullable=False,
    )
    status: Mapped[RunStatus] = mapped_column(
        string_enum(RunStatus, name="automation_run_status", length=16),
        nullable=False,
    )
    #: Почему пропущено: `condition_not_met`, `rate_limited`, `chain_depth_exceeded`...
    #: Строка, а не перечисление с проверкой: причины пополняются вместе с защитами, и
    #: миграция ради одной строки повторила бы историю типов событий.
    reason: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)

    #: Что правило сделало: список описаний действий в порядке выполнения. Без него
    #: журнал отвечает «сработало», но не «что именно сделало», а это первый вопрос
    #: того, кто разбирает последствия.
    actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)

    #: Настоящий инициатор: тот, чьё действие породило событие. Правило выполняется от
    #: системного актора, и без этой колонки цепочку «правило X, запущено из-за действия
    #: актора Y» восстановить было бы нечем.
    initiator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("actors.id"),
        default=None,
        nullable=True,
    )
    initiator_key: Mapped[str | None] = mapped_column(
        String(MAX_ACTOR_KEY_LENGTH),
        default=None,
        nullable=True,
    )

    #: Глубина цепочки на момент срабатывания: 0 — правило сработало на действие
    #: человека, 1 — на изменение, сделанное другим правилом, и так далее.
    chain_depth: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    # Отметка времени идёт вперёд внутри транзакции — то же отступление от
    # `TimestampsMixin`, что у журнала изменений и outbox, и по той же причине.
    # Автодействие перебирает сотни задач в одной транзакции: с `now()` все записи
    # получили бы одну отметку, и журнал показывался бы в порядке случайных UUID.
    # Второе следствие важнее: окно лимита срабатываний считается от `created_at`, и
    # одинаковое время у всей пачки сделало бы его границу условной.
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    initiator: Mapped[Actor | None] = relationship(lazy="selectin")
