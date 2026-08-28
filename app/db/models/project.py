"""Проекты и портфели: надочередной слой планирования.

Две таблицы одной формы, поэтому общая часть вынесена в примесь — так же, как у трёх
справочников в `app/db/models/catalog.py`. Отличается ровно одно: у проекта родитель —
портфель, у портфеля родитель — портфель же, то есть самоссылка.

## Почему две таблицы, а не одна с признаком вида

Соблазн слить их в одну таблицу с колонкой `kind` велик: полей у них поровну. Но
разошлись бы они немедленно и в самом неудобном месте — во внешних ключах. Задача
ссылается **только на проект**: портфель задач не содержит, он содержит проекты.
С общей таблицей этот запрет пришлось бы держать проверкой в сценарии вместо внешнего
ключа, и первая же ошибка дала бы задачу, привязанную к портфелю, — состояние, которого
не должно существовать, но которое база разрешает.

## Прогресс здесь не хранится

Колонки «процент готовности» у проекта нет и не будет. Задачу закрывают из REST, из MCP,
из автоматики и массовым переносом статуса, и каждое из этих мест обязано было бы
вспомнить про пересчёт. Прогресс считается запросом по задачам проекта — см.
`app/db/repositories/projects.py`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, ForeignKey, Index, String, Text, UniqueConstraint, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.actor import Actor
from app.domain.projects import MAX_PLANNING_KEY_LENGTH, ProjectStatus


class PlanningEntityMixin:
    """Общая часть проекта и портфеля: ключ, название, ответственный, период, состояние.

    Архивация (`is_archived`) — единственный способ убрать проект, которым пользовались:
    строка остаётся, задачи не теряют привязку, история цела, но в рабочих списках
    проекта больше нет. Удаления у проектов и портфелей нет вовсе — по той же причине,
    по которой его нет у очереди с задачами.
    """

    key: Mapped[str] = mapped_column(String(MAX_PLANNING_KEY_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Пустая строка вместо NULL — как у очереди, задачи и сохранённого фильтра:
    # «описания нет» и «описание пустое» — одно состояние.
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default=text("''"),
        nullable=False,
    )

    status: Mapped[ProjectStatus] = mapped_column(
        string_enum(ProjectStatus, name="project_status", length=16),
        default=ProjectStatus.NOT_STARTED,
        server_default=text(f"'{ProjectStatus.NOT_STARTED.value}'"),
        nullable=False,
    )

    # Календарные даты, а не моменты времени, — в отличие от дедлайна задачи. Проект не
    # начинается в 14:37, и хранить у него время значило бы вынудить клиента придумывать
    # часы, а потом объяснять, почему проект, начатый «сегодня», в другом поясе начался
    # вчера. `Date` указан явно: в `type_annotation_map` описан только `datetime`.
    start_date: Mapped[date | None] = mapped_column(Date, default=None, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, default=None, nullable=True)

    # Теги — тот же плоский список строк, что у задачи, и по тем же причинам. Словарь
    # тегов (`GET /api/v1/tags`) при этом собирается только по задачам: метки проектов
    # в него не попадают, потому что подсказка нужна там, где метки ставят пачками.
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )

    is_archived: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(default=None)

    @declared_attr
    def lead_id(cls) -> Mapped[uuid.UUID]:
        """Ответственный за результат. Без `ondelete`: акторов не удаляют, а отключают."""
        return mapped_column(ForeignKey("actors.id"), nullable=False)

    @declared_attr
    def lead(cls) -> Mapped[Actor]:
        """Ответственный приезжает ключом в каждом ответе, поэтому загружается сразу."""
        return relationship(lazy="joined", innerjoin=True, foreign_keys=lambda: [cls.lead_id])

    @declared_attr.directive
    def __table_args__(cls) -> tuple[Any, ...]:
        """Ключ уникален внутри своего вида, а не на обе таблицы сразу.

        `alpha` может быть и проектом, и портфелем: адресуются они разными путями
        (`/projects/alpha` против `/portfolios/alpha`) и разными фильтрами, и общий
        запрет только отнимал бы имена без всякой пользы.

        Индекс под курсорную пагинацию составной: страница проектов идёт по паре
        `(created_at, id)`, и без индекса каждая страница означала бы сортировку всей
        таблицы.
        """
        return (
            UniqueConstraint("key"),
            Index(f"ix_{cls.__tablename__}_created_at_id", "created_at", "id"),
        )


class Portfolio(PlanningEntityMixin, BaseModel):
    """Портфель: объединяет проекты и другие портфели.

    Задач портфель не содержит — их содержат его проекты. Прогресс портфеля
    агрегируется по задачам всех проектов-потомков.
    """

    __tablename__ = "portfolios"

    # Самоссылка: портфель лежит в портфеле. Без `ondelete` — портфели не удаляют, их
    # архивируют, и каскад, уносящий вложенные портфели вместе с родителем, был бы
    # катастрофой, к которой нет ни одного сценария.
    #
    # Отсутствие цикла в этой ссылке внешним ключом **не выражается**: это свойство
    # графа целиком, а не строки. Проверку держит сценарий
    # (`app/services/projects.py`), а читатели защищены ограничителем глубины
    # `MAX_PORTFOLIO_DEPTH` — ровно как в иерархии задач.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolios.id"),
        default=None,
        nullable=True,
    )

    # `joined` с `join_depth=1`, а не `selectin`, как у остальных связей проекта.
    # Это единственное исключение в проекте, и оно вынужденное: у самоссылочной связи
    # «многие к одному» стратегия `selectin` молча не срабатывает — атрибут остаётся
    # ленивым, и первое же обращение к нему вне async-контекста падает
    # `MissingGreenlet` при сборке ответа. Ни ошибки, ни предупреждения при загрузке
    # объекта при этом нет; поймала это живая проверка, а не тесты.
    #
    # `join_depth=1` обязателен: без него joined-загрузка к самоссылке не применяется
    # вовсе — SQLAlchemy нечем ограничить рекурсию. Отсюда и ограничение, которое надо
    # знать: загружается **один** уровень. `portfolio.parent.key` безопасен,
    # `portfolio.parent.parent` — снова ленивая загрузка. Подниматься по цепочке нужно
    # запросом (`PortfolioRepository.has_ancestor`), а не обходом связей.
    parent: Mapped[Portfolio | None] = relationship(
        lazy="joined",
        join_depth=1,
        remote_side=lambda: [Portfolio.id],
    )

    # Участники — набор, а не список: порядок ничего не значит, поэтому сортировка
    # задана по ключу актора и одинакова в любом ответе.
    members: Mapped[list[Actor]] = relationship(
        secondary="portfolio_members",
        lazy="selectin",
        order_by=Actor.key,
    )


class Project(PlanningEntityMixin, BaseModel):
    """Проект: собирает задачи из разных очередей вокруг общего результата."""

    __tablename__ = "projects"

    # Проект лежит не более чем в одном портфеле; `NULL` — проект сам по себе, и это
    # законное состояние, а не недооформленность. Без `ondelete` по той же причине,
    # что у самоссылки портфеля.
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolios.id"),
        default=None,
        nullable=True,
    )

    portfolio: Mapped[Portfolio | None] = relationship(lazy="selectin")

    members: Mapped[list[Actor]] = relationship(
        secondary="project_members",
        lazy="selectin",
        order_by=Actor.key,
    )


class ProjectMember(BaseModel):
    """Участник проекта: тот, кто в нём работает, но не обязательно за него отвечает.

    Отдельная таблица, а не список ключей в JSONB, — по той же причине, что у
    наблюдателей задачи: участник — существующий актор, и ссылка на него должна
    держаться внешним ключом. Иначе движок уведомлений узнал бы о ссылке в никуда в
    момент рассылки.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id"),
        # Уникальное ограничение начинается с проекта и обратный вопрос — «в каких
        # проектах участвует актор» — не обслуживает. А он и есть запрос личного
        # кабинета, поэтому индекс отдельный.
        Index("ix_project_members_actor_id", "actor_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("actors.id", ondelete="CASCADE"),
        nullable=False,
    )


class PortfolioMember(BaseModel):
    """Участник портфеля. Устроен так же, как участник проекта."""

    __tablename__ = "portfolio_members"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "actor_id"),
        Index("ix_portfolio_members_actor_id", "actor_id"),
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("actors.id", ondelete="CASCADE"),
        nullable=False,
    )
