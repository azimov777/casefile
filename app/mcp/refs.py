"""Разрешение ссылок: строка от агента → объект, который ждёт сценарий.

Сценарии принимают объекты (`Queue`, `Status`, `Actor`), а не строки, и потому не
зависят от того, кто их позвал. Значит перевод строки в объект — работа интерфейса, и у
MCP она своя, ровно как у REST (`app/api/routes/*`). Общего кода тут быть не может:
`api` и `mcp` друг от друга не зависят, а всё, что можно вынести, уже вынесено в
сценарии (`queues_service.resolve_catalog_ref`, `resolve_field_ref`, `resolve_scope`).

Адресация мягкая везде, где адресуют существующий объект: `trk-1` находит `TRK-1`,
`trk.open` — `TRK.open`. Строгость нужна только там, где ключ придумывают, и живёт она в
домене — вместе с сообщением, объясняющим ожидаемый формат.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.field import Field
from app.db.models.issue import Issue
from app.db.models.project import Portfolio, Project
from app.db.models.queue import Queue
from app.domain.catalogs import CatalogKind
from app.services import actors as actors_service
from app.services import issues as issues_service
from app.services import projects as projects_service
from app.services import queues as queues_service


async def actor(session: AsyncSession, key: str | None) -> Actor | None:
    """Актор по ключу; `None` остаётся `None` — «снять исполнителя»."""
    return None if key is None else await actors_service.get_actor_by_key(session, key)


async def issue(session: AsyncSession, key: str) -> Issue:
    """Задача по ключу (`TRK-123`) или `issue_not_found`."""
    return await issues_service.get_issue_by_key(session, key)


async def queue(session: AsyncSession, key: str) -> Queue:
    """Очередь по ключу или `queue_not_found`."""
    return await queues_service.get_queue_by_key(session, key)


async def optional_queue(session: AsyncSession, key: str | None) -> Queue | None:
    """Очередь или `None` — «правило работает во всех очередях»."""
    return None if key is None else await queue(session, key)


async def scope(session: AsyncSession, key: str | None) -> Queue | None:
    """Очередь-область: `None` означает глобальную область, а не «любую очередь»."""
    return await queues_service.resolve_scope(session, key)


async def status(session: AsyncSession, ref: str, *, initiator: Actor) -> Status:
    """Статус по ссылке (`open`, `TRK.open`)."""
    entry = await _catalog(session, CatalogKind.STATUS, ref, initiator=initiator)
    assert isinstance(entry, Status)
    return entry


async def issue_type(session: AsyncSession, ref: str, *, initiator: Actor) -> IssueType:
    """Тип задачи по ссылке."""
    entry = await _catalog(session, CatalogKind.ISSUE_TYPE, ref, initiator=initiator)
    assert isinstance(entry, IssueType)
    return entry


async def resolution(session: AsyncSession, ref: str, *, initiator: Actor) -> Resolution:
    """Резолюцию по ссылке."""
    entry = await _catalog(session, CatalogKind.RESOLUTION, ref, initiator=initiator)
    assert isinstance(entry, Resolution)
    return entry


async def optional_status(session: AsyncSession, ref: str | None, *, initiator: Actor) -> Any:
    """Статус или `None`, если ссылки нет."""
    return None if ref is None else await status(session, ref, initiator=initiator)


async def optional_issue_type(session: AsyncSession, ref: str | None, *, initiator: Actor) -> Any:
    """Тип задачи или `None`, если ссылки нет."""
    return None if ref is None else await issue_type(session, ref, initiator=initiator)


async def optional_resolution(session: AsyncSession, ref: str | None, *, initiator: Actor) -> Any:
    """Резолюция или `None`, если ссылки нет."""
    return None if ref is None else await resolution(session, ref, initiator=initiator)


async def field(session: AsyncSession, ref: str, *, initiator: Actor) -> Field:
    """Поле реестра по ссылке (`severity`, `TRK.severity`)."""
    return await queues_service.resolve_field_ref(session, ref, initiator=initiator)


async def project(session: AsyncSession, key: str) -> Project:
    """Проект по ключу или `project_not_found`."""
    return await projects_service.get_project_by_key(session, key)


async def optional_project(session: AsyncSession, key: str | None) -> Project | None:
    """Проект или `None` — «вынуть задачу из проекта»."""
    return None if key is None else await project(session, key)


async def portfolio(session: AsyncSession, key: str) -> Portfolio:
    """Портфель по ключу или `portfolio_not_found`."""
    return await projects_service.get_portfolio_by_key(session, key)


async def optional_portfolio(session: AsyncSession, key: str | None) -> Portfolio | None:
    """Портфель или `None` — «вынуть наверх»."""
    return None if key is None else await portfolio(session, key)


def identifier(value: str, name: str) -> uuid.UUID:
    """Строку в идентификатор объекта с внятной ошибкой вместо трассировки.

    Досок, колонок, переходов и подписок в проекте адресуют UUID, и агент получает их из
    выдачи предыдущего вызова. Опечатка в такой строке обязана называться ошибкой
    параметра: `invalid` в трассировке разбора не объясняет, что именно испорчено.
    """
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValidationError(
            message=f"Parameter {name} must be an object id in UUID form",
            details={"parameter": name, "value": value},
        ) from exc


async def _catalog(
    session: AsyncSession,
    kind: CatalogKind,
    ref: str,
    *,
    initiator: Actor,
) -> Any:
    return await queues_service.resolve_catalog_ref(session, kind, ref, initiator=initiator)
