"""Портфели: карточка, состав, агрегированный прогресс, вложенность без циклов.

Портфель адресуется ключом, как проект. Пространства имён у них разные: `alpha` может
быть и проектом, и портфелем — адресуются они разными путями, и общий запрет только
отнимал бы имена.

Состав отдаётся одним списком (`/portfolios/{key}/content`), а не двумя коллекциями в
одном ответе: оболочка проекта кладёт под `data` ровно одну коллекцию, а курсор
указывает позицию в одном упорядоченном запросе. Две страницы, склеенные в памяти,
теряли бы записи на первой же границе.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.projects import (
    PortfolioCreate,
    PortfolioItemRead,
    PortfolioRead,
    PortfolioSet,
    PortfolioUpdate,
)
from app.core.sentinels import UNSET
from app.db.models.actor import Actor
from app.db.models.project import Portfolio, Project
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.projects import Progress, ProjectStatus
from app.services import actors as actors_service
from app.services import projects as service
from app.services.projects import PlanningChanges, PortfolioItem

router = APIRouter(prefix="/portfolios", tags=["portfolios"])

PortfolioKeyPath = Annotated[
    str,
    Path(description="Portfolio key, immutable", examples=["platform"]),
]
ParentFilterQuery = Annotated[
    str | None,
    Query(description="Portfolio key: list portfolios nested directly in it"),
]
# Псевдоним с `alias`: имя `status` в модуле занято импортом кодов FastAPI, а
# наружу параметр обязан называться именно `status`.
StatusFilterQuery = Annotated[
    ProjectStatus | None,
    Query(alias="status", description="Filter by planning status"),
]
ArchivedFilterQuery = Annotated[
    bool | None,
    Query(description="Filter by the archived flag; omit to get both"),
]
LeadFilterQuery = Annotated[str | None, Query(description="Filter by the lead actor key")]


async def _parent(session: AsyncSession, key: str | None) -> Portfolio | None:
    return None if key is None else await service.get_portfolio_by_key(session, key)


async def _actor(session: AsyncSession, key: str | None) -> Actor | None:
    return None if key is None else await actors_service.get_actor_by_key(session, key)


async def _read(session: AsyncSession, portfolio: Portfolio) -> DataResponse[PortfolioRead]:
    """Карточка портфеля: прогресс по задачам всех потомков плюс счётчики состава."""
    progress = await service.portfolio_progress(session, [portfolio])
    counts = await service.portfolio_child_counts(session, [portfolio])
    return DataResponse[PortfolioRead](
        data=PortfolioRead.of(
            portfolio,
            progress=progress.get(portfolio.id, Progress()),
            counts=counts.get(portfolio.id, (0, 0)),
        )
    )


async def _changes(session: AsyncSession, payload: PortfolioUpdate) -> PlanningChanges:
    """Тело запроса в термины сценария. `null` у `portfolio` делает портфель корневым."""
    given = payload.model_dump(exclude_unset=True)

    members: object = UNSET
    if "members" in given:
        members = [await actors_service.get_actor_by_key(session, key) for key in payload.members]

    lead: object = UNSET
    if "lead" in given:
        lead = await actors_service.get_actor_by_key(session, given["lead"])

    parent: object = UNSET
    if "portfolio" in given:
        parent = await _parent(session, given["portfolio"])

    return PlanningChanges(
        name=given.get("name", UNSET),
        description=given.get("description", UNSET),
        status=given.get("status", UNSET),
        lead=lead,
        members=members,
        start_date=given.get("start_date", UNSET),
        end_date=given.get("end_date", UNSET),
        tags=given.get("tags", UNSET),
        portfolio=parent,
    )


@router.get("", summary="List portfolios")
async def list_portfolios(
    session: SessionDep,
    current_actor: CurrentActorDep,
    parent: ParentFilterQuery = None,
    portfolio_status: StatusFilterQuery = None,
    is_archived: ArchivedFilterQuery = None,
    lead: LeadFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[PortfolioRead]:
    """Страница портфелей в порядке создания, с прогрессом и счётчиками состава.

    Прогресс всей страницы считается одним рекурсивным запросом: он разворачивает
    каждый портфель в его проекты-потомки и складывает счётчики задач разом.
    """
    page = await service.list_portfolios(
        session,
        initiator=current_actor,
        parent=await _parent(session, parent),
        status=portfolio_status,
        is_archived=is_archived,
        lead=await _actor(session, lead),
        limit=limit,
        cursor=cursor,
    )
    progress = await service.portfolio_progress(session, page.items)
    counts = await service.portfolio_child_counts(session, page.items)
    return CollectionResponse[PortfolioRead].of(
        [
            PortfolioRead.of(
                item,
                progress=progress.get(item.id, Progress()),
                counts=counts.get(item.id, (0, 0)),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a portfolio")
async def create_portfolio(
    payload: PortfolioCreate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[PortfolioRead]:
    """Заводит портфель. Ответственный по умолчанию — актор, стоящий за токеном."""
    portfolio = await service.create_portfolio(
        session,
        initiator=current_actor,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        lead=await _actor(session, payload.lead),
        members=[await actors_service.get_actor_by_key(session, key) for key in payload.members],
        start_date=payload.start_date,
        end_date=payload.end_date,
        tags=payload.tags,
        parent=await _parent(session, payload.portfolio),
    )
    return await _read(session, portfolio)


@router.get("/{portfolio_key}", summary="Read a portfolio")
async def read_portfolio(
    portfolio_key: PortfolioKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[PortfolioRead]:
    """Карточка портфеля. Состав отдаёт отдельный маршрут — он бывает большим."""
    portfolio = await service.read_portfolio(session, portfolio_key, initiator=current_actor)
    return await _read(session, portfolio)


@router.patch("/{portfolio_key}", summary="Update a portfolio")
async def update_portfolio(
    portfolio_key: PortfolioKeyPath,
    payload: PortfolioUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[PortfolioRead]:
    """Меняет только переданные поля. Смена родителя проверяется на цикл."""
    portfolio = await service.read_portfolio(session, portfolio_key, initiator=current_actor)
    updated, _ = await service.update_portfolio(
        session,
        portfolio,
        initiator=current_actor,
        changes=await _changes(session, payload),
    )
    return await _read(session, updated)


@router.put("/{portfolio_key}/parent", summary="Move a portfolio into another one")
async def move_portfolio(
    portfolio_key: PortfolioKeyPath,
    payload: PortfolioSet,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[PortfolioRead]:
    """Вкладывает портфель в другой; `null` делает его корневым.

    Кольцо запрещено на произвольной глубине, а не только на прямом «A внутри B, B
    внутри A»: цикл из трёх портфелей ломает обход состава так же, как из двух. Отказ —
    `portfolio_cycle_detected`.
    """
    portfolio = await service.read_portfolio(session, portfolio_key, initiator=current_actor)
    moved = await service.move_portfolio(
        session,
        portfolio,
        initiator=current_actor,
        parent=await _parent(session, payload.portfolio),
    )
    return await _read(session, moved)


@router.post("/{portfolio_key}/archive", summary="Archive a portfolio")
async def archive_portfolio(
    portfolio_key: PortfolioKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[PortfolioRead]:
    """Убирает портфель в архив: нового состава он не принимает.

    Вложенные проекты и портфели остаются как были. Каскадная архивация состава была бы
    ловушкой: вернуть портфель из архива после неё нельзя — неизвестно, что из его
    детей лежало в архиве до операции. Идемпотентно.
    """
    portfolio = await service.read_portfolio(session, portfolio_key, initiator=current_actor)
    archived = await service.archive_portfolio(session, portfolio, initiator=current_actor)
    return await _read(session, archived)


@router.post("/{portfolio_key}/unarchive", summary="Restore a portfolio from the archive")
async def unarchive_portfolio(
    portfolio_key: PortfolioKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[PortfolioRead]:
    """Возвращает портфель из архива. Тоже идемпотентно."""
    portfolio = await service.read_portfolio(session, portfolio_key, initiator=current_actor)
    restored = await service.restore_portfolio(session, portfolio, initiator=current_actor)
    return await _read(session, restored)


@router.get("/{portfolio_key}/content", summary="List the content of a portfolio")
async def read_portfolio_content(
    portfolio_key: PortfolioKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[PortfolioItemRead]:
    """Состав портфеля: вложенные портфели и проекты одним упорядоченным списком.

    Порядок общий — по времени создания, — поэтому страницы не зависят от того, чего в
    портфеле больше. Отличить одно от другого позволяет поле `kind`; у каждой позиции
    посчитан свой прогресс, у вложенного портфеля — агрегированный по его потомкам.
    """
    portfolio = await service.read_portfolio(session, portfolio_key, initiator=current_actor)
    page = await service.portfolio_content(
        session,
        portfolio,
        initiator=current_actor,
        limit=limit,
        cursor=cursor,
    )
    progress = await _content_progress(session, page.items)
    return CollectionResponse[PortfolioItemRead].of(
        [
            PortfolioItemRead.of(
                item.entity,
                kind=item.kind,
                progress=progress.get(item.entity.id, Progress()),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


async def _content_progress(
    session: AsyncSession,
    items: list[PortfolioItem],
) -> dict[uuid.UUID, Progress]:
    """Прогресс всех позиций страницы: два запроса на страницу, а не два на позицию.

    Проекты и портфели считаются разными запросами — у проекта прогресс по его задачам,
    у портфеля агрегируется по потомкам, — но каждый из двух идёт пачкой. Ключи двух
    словарей не пересекаются: идентификаторы приходят из разных таблиц.
    """
    projects = [item.entity for item in items if isinstance(item.entity, Project)]
    portfolios = [item.entity for item in items if isinstance(item.entity, Portfolio)]
    return {
        **await service.project_progress(session, projects),
        **await service.portfolio_progress(session, portfolios),
    }
