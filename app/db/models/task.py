"""Задача: центральная сущность трекера.

Поля фиксированы (`CONCEPT.md`, 3.3): название, описание, четыре текстовых раздела и
список проверок — колонки, а не реестр полей. Статус — перечисление, а не ссылка на
справочник: справочника статусов в базе нет.

Ключ задачи (`TRK-42`) не переиспользуется: выданный задаче, он закреплён за ней навсегда.
Меняется он только переносом в другой проект (`CONCEPT.md`, 3.3), и тогда прежний ключ
уходит в `previous_keys` и продолжает вести на задачу. Ключ и проект — две колонки, а не
ключ, вычисляемый из проекта: на ключ ссылаются записи дела и внешние системы.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.area import Area
from app.db.models.author import CreatedByMixin
from app.db.models.project import Project
from app.domain.tasks import (
    INITIAL_STATUS,
    MAX_ASSIGNEE_LENGTH,
    MAX_TASK_KEY_LENGTH,
    MAX_TITLE_LENGTH,
    TaskPriority,
    TaskStatus,
)


class Task(BaseModel, CreatedByMixin):
    """Строка задачи.

    Внешний ключ на проект без `ondelete`: проекты не удаляются, а если это однажды
    случится, база откажет, и задачи не исчезнут молча.

    Автор строки (`CreatedByMixin`) — тот, кто завёл задачу. Это не «исполнитель»:
    исполнитель — строка, которую трекер сам не меняет и сверяет с подписью только на
    входе в `in_progress` (`check_taken_by_assignee`, `app/domain/tasks.py`).
    """

    __tablename__ = "tasks"
    __table_args__ = (
        # «Задачи проекта в таком-то статусе» — основной запрос списка и назначателя.
        # Индекс начинается с проекта: по одному `project_id` он работает тоже, обратное
        # неверно.
        Index("ix_tasks_project_id_status", "project_id", "status"),
        # «Что у этого исполнителя» — фильтр поиска и входящая агента.
        Index("ix_tasks_assignee", "assignee"),
        # Курсорная пагинация проекта идёт по паре `(created_at, id)`; без индекса
        # каждая страница означала бы сортировку всей таблицы.
        Index("ix_tasks_created_at_id", "created_at", "id"),
        # Порядок списка задач по умолчанию — «проект, номер». Номер вынут из ключа
        # выражением: строковое сравнение поставило бы `TRK-10` перед `TRK-2`, а
        # отдельной колонки под номер нет — ключ и есть его хранилище.
        Index(
            "ix_tasks_project_id_number", "project_id", text("(split_part(key, '-', 2)::bigint)")
        ),
        # Сортировка по времени обновления с тайбрейкером по `id`: пара, а не одна
        # колонка, потому что курсор идёт по обеим.
        Index("ix_tasks_updated_at_id", "updated_at", "id"),
        # Триграммные индексы под `text: ~ ...` — вхождение подстроки в названии и
        # описании. Работают от трёх символов: в двух триграмм нет, и план вырождается
        # в последовательное чтение (`docs/notes/search.md`).
        Index(
            "ix_tasks_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_tasks_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        # Задача по прежнему ключу — `previous_keys @> '["UI-5"]'`: адресация по прежнему
        # ключу идёт на каждом обращении к задаче, как по текущему (`CONCEPT.md`, 3.3).
        # `jsonb_path_ops` — ровно под `@>`, и меньше индекса по умолчанию.
        Index(
            "ix_tasks_previous_keys",
            "previous_keys",
            postgresql_using="gin",
            postgresql_ops={"previous_keys": "jsonb_path_ops"},
        ),
        # «Какие задачи опираются на решение» — `decisions @> '["TRK#15"]'`: обратный путь от
        # решения проекта к задачам, отбор `decision:` (`CONCEPT.md`, 4.4). Тот же класс
        # операторов, что у прежних ключей: индекс ровно под `@>`.
        Index(
            "ix_tasks_decisions",
            "decisions",
            postgresql_using="gin",
            postgresql_ops={"decisions": "jsonb_path_ops"},
        ),
        # «Задачи области» — отбор `area:` (`CONCEPT.md`, 4.4) и число задач.
        Index("ix_tasks_area_id", "area_id"),
        # Версия только растёт и начинается с единицы: ноль означал бы, что счётчик
        # правили руками, и оптимистичная блокировка перестала бы ловить гонку.
        CheckConstraint("version >= 1", name="version_positive"),
    )

    key: Mapped[str] = mapped_column(String(MAX_TASK_KEY_LENGTH), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    # Прежние ключи в порядке ухода: те, что задача носила до переносов (`CONCEPT.md`,
    # 3.3). Список в строке задачи, а не таблица ключей: карточка и строка поиска читают
    # его вместе с задачей, одним запросом, а уникальность ключа держит не индекс, а
    # счётчик проекта — он только растёт, и в проект, где у задачи уже был ключ, она
    # возвращается с ним (`app/domain/tasks.py`, `returning_key`).
    previous_keys: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(MAX_TITLE_LENGTH), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Четыре текстовых раздела. Пустая строка вместо NULL: «раздела нет» и «раздел пуст»
    # — одно состояние, и два способа его записать разъехались бы у клиентов.
    goal: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    context: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    constraints: Mapped[str] = mapped_column(
        Text, default="", server_default=text("''"), nullable=False
    )
    output: Mapped[str] = mapped_column(Text, default="", server_default=text("''"), nullable=False)
    # Пятый раздел: упорядоченный список строк, нумерация с 1 по позиции. JSONB, а не
    # таблица: проверка не самостоятельный объект, на неё ссылаются номером внутри
    # задачи, и отдельная таблица дала бы соединение ради трёх строк.
    checks: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    status: Mapped[TaskStatus] = mapped_column(
        string_enum(TaskStatus, name="task_status", length=16),
        default=INITIAL_STATUS,
        server_default=text(f"'{INITIAL_STATUS.value}'"),
        nullable=False,
    )
    # Свободная строка: имя участника или метка. Внешнего ключа нет намеренно — у
    # временного агента строки в реестре нет (`CONCEPT.md`, 3.3).
    assignee: Mapped[str | None] = mapped_column(
        String(MAX_ASSIGNEE_LENGTH), default=None, nullable=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        string_enum(TaskPriority, name="task_priority", length=16),
        default=TaskPriority.NORMAL,
        server_default=text(f"'{TaskPriority.NORMAL.value}'"),
        nullable=False,
    )
    # Решения проекта, на которые опирается задача: канонические ссылки `TRK#15` в порядке
    # постановки (`CONCEPT.md`, 3.3). Строки, а не идентификаторы записей: ключ проекта и
    # номер записи неизменяемы, ссылка читается без соединения, а отбор `decision:` ищет
    # ровно ту строку, которую пишет агент. Внешнего ключа нет, как у `refs` записи:
    # существование решения проверяет сценарий при постановке ссылки, а записи дела не
    # удаляются. Статус решения здесь не хранится — он считается при чтении.
    decisions: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    # Область задачи: не больше одной, необязательная (`CONCEPT.md`, 3.3, 3.7).
    # Без `ondelete`: области не удаляются. Область другого проекта в колонку
    # попасть не должно — это проверяет сценарий (`area_project_mismatch`), а перенос
    # задачи колонку обнуляет.
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("areas.id"), default=None, nullable=True
    )

    # Момент «не раньше» (решение проекта `TRK#47`): до него вход в `in_progress`
    # отклоняется. Хранится момент, а не «отложена ли»: признак `deferred` считается при
    # чтении по часам базы (`app/db/repositories/tasks.py`, `deferred_now`), и колонка под
    # него разошлась бы с часами ровно в момент наступления.
    not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )

    # Версия для оптимистичной блокировки. Ведёт её SQLAlchemy (`version_id_col`):
    # каждый UPDATE строки идёт с условием `WHERE version = :seen` и поднимает
    # версию на единицу, а расхождение поднимает `StaleDataError`, которую сценарий
    # переводит в `version_conflict`. Так гонка двух правок ловится базой, а не только
    # сравнением в Python до записи.
    version: Mapped[int] = mapped_column(
        BigInteger,
        default=1,
        server_default=text("1"),
        nullable=False,
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "eager_defaults": True,
        "version_id_col": version,
    }

    # Ключ и название проекта входят в каждую карточку задачи, а проект у задачи один,
    # поэтому `joined`: одно соединение вместо второго запроса на каждый ответ.
    project: Mapped[Project] = relationship(lazy="joined")
    # Адрес области нужен каждой карточке и строке выдачи, и она одна: `joined`, как
    # проект. Внешняя связь — `outer`, потому что области у задачи может не быть.
    area: Mapped[Area | None] = relationship(lazy="joined", innerjoin=False)
