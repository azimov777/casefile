"""Запись дела: неизменяемая страница журнала задачи.

Дело хранит всё (`CONCEPT.md`, 3.4 и 4.1): и записи агента, и служебные записи о
каждом изменении. Отдельной таблицы событий нет — эта таблица и есть лента для внешнего
мира, а `seq` — её курсор.

## Два номера

`seq` — сквозной по всему трекеру, выдаёт база (`GENERATED ALWAYS AS IDENTITY`), задать
его снаружи нельзя. Он монотонный в порядке вставки и служит курсором ленты.
`no` — порядковый внутри задачи, с 1: на него ссылаются (`TRK-42#12`), поэтому он без
дыр. Выдаёт его репозиторий под блокировкой строки задачи
(`EntryRepository.allocate_no`), а не счётчик на задаче: счётчик терял бы номер на
откате, и в деле появлялась бы дыра ровно там, где ссылка должна быть надёжной.

## Неизменяемость

На уровне кода: у репозитория нет методов правки и удаления, у API нет таких
маршрутов. На уровне схемы: триггер `entries_immutable` (миграция `tasks and entries`)
отклоняет `UPDATE` и `DELETE` на таблице. `updated_at` из общей примеси остаётся ради
единообразия таблиц и всегда равно `created_at`.

## Автор

Пара колонок из `CreatedByMixin` — та же, что у реестров, и заполняется той же
функцией `created_by_columns`. В концепции поле называется `author`, и наружу оно
уходит под этим именем через свойство; колонки не переименованы, чтобы «кто это
сделал» во всех таблицах проекта лежало одинаково.

## `action_id` — признак одного действия

Один вызов (`update_task`, `transition`, `close_task`, `create_task`, `link` и
прочие точки входа `app/services/case.py` и `app/services/tasks.py`) подшивает от
одной до нескольких записей, и всем им ставится одно и то же значение —
`uuid.uuid4()`, сгенерированное в Python на входе вызова, а не в базе. Разные вызовы
получают разные значения, даже подряд в одной сессии и в одной транзакции: интерфейс
группирует записи по этому полю (TRK-118, UI-133), и группировка не должна зависеть
от того, что БД считает одной транзакцией — это деталь реализации, а не контракт
(вывод UI-133#5 о совпадении `created_at`).

Именно поэтому это не `pg_current_xact_id()`/`txid_current()`: тесты ведут вызовы
сервисного слоя внутри одной внешней транзакции теста через `SAVEPOINT`
(`join_transaction_mode="create_savepoint"`, `tests/conftest.py`), и настоящий
транзакционный id был бы там одним на весь тест — ровно то смешение, от которого
уходит сама задача.

Точка присвоения — единственная: `_append` в `app/services/case.py`. Функции,
которые подшивают несколько записей одним вызовом (`apply_task_changes`,
`close_task`, `_record_on_both_sides` в `app/services/links.py`), генерируют
значение один раз сами и передают его явно во все свои внутренние подшивки; когда
вызывающий его не передал, `_append` генерирует новое — так у одиночной записи
(`add_summary`, `ask` и прочие МСР-инструменты сами по себе) всегда есть значение,
а группа не распадается на случайные значения по одной на запись.

Колонка допускает `null`: у записей, подшитых до миграции этого поля, значения нет
и взяться ему неоткуда — без него совпадение `created_at` и автора не значит
совпадения действия (то же рассуждение, что и в задаче), и трекер не восстанавливает
исторические группы задним числом.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.domain.authors import Author
from app.domain.case import MAX_ENTRY_TITLE_LENGTH, EntryType


class Entry(BaseModel, CreatedByMixin):
    """Одна запись дела. Добавить можно, изменить и удалить нельзя."""

    __tablename__ = "entries"
    __table_args__ = (
        # Записи по задаче и номеру — основной способ адресации (`TRK-42#12`) и
        # порядок чтения дела. Уникальность держит и «нет двух двенадцатых записей».
        UniqueConstraint("task_id", "no"),
        # Лента: «записи после `seq` N» с фильтром по типу. Уникальность `seq`
        # покрывает хвост ленты; фильтр по типу внутри задачи (сводки, вопросы,
        # вердикты) — свой индекс, потому что предыдущий начинается с номера.
        Index("ix_entries_task_id_type", "task_id", "type"),
        # «Вопросы всех задач по возрастанию `seq`» — выдача открытых вопросов
        # участника. Предыдущий индекс ей не годится: он начинается с задачи, а
        # «входящая» идёт поперёк задач.
        Index("ix_entries_type_seq", "type", "seq"),
        # Фильтр по адресату вопроса — `payload -> 'addressees' @> '["name"]'`.
        # Частичный, только по вопросам: вопросов в деле единицы на сотни записей, и
        # полный GIN платил бы за каждую подшивку строки ради одного типа.
        Index(
            "ix_entries_question_payload",
            "payload",
            postgresql_using="gin",
            postgresql_where=text("type = 'question'"),
        ),
    )

    # `GENERATED ALWAYS`: значение задаёт только база, вставка с явным `seq` отклоняется.
    seq: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        unique=True,
        nullable=False,
    )
    # Без `ondelete`: задачи не удаляются, а если это однажды случится — база откажет,
    # и дело не исчезнет молча.
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    no: Mapped[int] = mapped_column(Integer, nullable=False)

    type: Mapped[EntryType] = mapped_column(
        string_enum(EntryType, name="entry_type", length=32),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(MAX_ENTRY_TITLE_LENGTH), nullable=False)
    # Пустая строка у служебных записей: тело служебной записи — это её `payload`.
    body: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    # Структурные поля по типу записи. Форма по каждому типу — задача 23; здесь только
    # служебные: `status_changed` — `from`, `to`, `reason`; `section_changed` —
    # `field`, `before`, `after`; `assignee_changed` — `before`, `after`.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    # Ссылки на записи (`TRK-42#12`), задачи (`TRK-7`) и адреса. Проверяет их задача 23.
    refs: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    # Признак одного действия: см. раздел `action_id` в шапке модуля. `null` — только у
    # записей, подшитых до миграции этого поля.
    action_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    @property
    def author(self) -> Author:
        """Автор записи — под именем из концепции."""
        return self.created_by
