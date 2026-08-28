"""Сценарии проектов и портфелей: надочередной слой планирования.

## Состав проекта — это поле задачи, а не отдельная механика

`add_issues` и `remove_issues` не присваивают ничего сами: они собирают `IssueChanges`
и зовут `apply_issue_changes` — ту же единую точку, через которую идёт любая правка
задачи. Иначе добавление в проект прошло бы мимо истории задачи, мимо outbox и мимо
будущей автоматики, и обнаружилось бы это как дыра в истории, далеко от места ошибки.

Прямое следствие, которое надо знать: у задачи, добавленной в проект, растёт `version`.
Клиент, который держал её для оптимистичной блокировки, обязан перечитать задачу.

## Список задач проекта — это поиск, а не второй фильтр

`list_project_issues` подставляет условие `project: <ключ>` первым слагаемым и отдаёт
всё в `app/services/search.py`. Поэтому в проекте работают тот же язык запросов, та же
сортировка, тот же выбор возвращаемых полей и та же курсорная пагинация, что и в общем
поиске, — и второй реализации отбора у проекта не появляется. Требование задачи «список
должен уметь фильтроваться и постранично отдаваться» закрывается именно этим, а не
набором параметров, повторяющих половину поиска.

## Прогресс считается по запросу и всегда пачкой

Функции прогресса принимают набор объектов и возвращают словарь: страница из полусотни
проектов обязана стоить один запрос, а не полсотни. Кеша нет и он пока не нужен — если
понадобится, инвалидировать его будет подписчик шины по событиям задач, а не сценарий.

## Портфель и проект различаются меньше, чем кажется

Общая часть правок вынесена в `_apply_common`. Разница ровно в двух вещах: у проекта
родитель — портфель (`portfolio_id`), у портфеля — портфель же (`parent_id`); и цикл
возможен только во втором случае, потому что у проекта детей нет.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.project import Portfolio, Project
from app.db.pagination import Page
from app.db.repositories import PortfolioRepository, ProjectRepository
from app.domain.errors import (
    ActorInactiveError,
    InvalidPortfolioError,
    InvalidPortfolioKeyError,
    InvalidProjectError,
    InvalidProjectKeyError,
    PortfolioArchivedError,
    PortfolioCycleError,
    PortfolioKeyTakenError,
    PortfolioNotFoundError,
    ProjectArchivedError,
    ProjectKeyTakenError,
    ProjectNotFoundError,
)
from app.domain.issues import IssueChange, normalize_tags, tags_differ
from app.domain.projects import (
    INVALID_ERRORS,
    MAX_PLANNING_MEMBERS,
    PlanningKind,
    Progress,
    ProjectStatus,
    normalize_planning_key,
    validate_period,
    validate_planning_description,
    validate_planning_key,
    validate_planning_name,
)
from app.domain.search import SystemField
from app.services import events as events_service
from app.services import issues as issues_service
from app.services import search as search_service
from app.services.permissions import ensure_allowed

PlanningEntity = Project | Portfolio

#: Ошибка «ключ занят» по виду объекта: проверка ключа общая, а коды у проекта и
#: портфеля свои, и склеивать их в один было бы отказом от точности контракта.
_KEY_TAKEN_ERRORS = {
    PlanningKind.PROJECT: ProjectKeyTakenError,
    PlanningKind.PORTFOLIO: PortfolioKeyTakenError,
}


@dataclass(frozen=True, slots=True)
class PlanningChanges:
    """Что меняем в проекте или портфеле. Не переданное поле остаётся `UNSET`.

    `portfolio` у проекта означает родительский портфель, у портфеля — тот, внутрь
    которого он вложен. Поле одно, потому что и операция одна: «переложить в другой
    портфель». `null` вынимает объект наверх — это законное состояние, а не
    недооформленность, поэтому тип допускает `None`.

    Ключ в изменения не входит и не меняется никогда: по нему адресуют проект в путях,
    в фильтрах (`project: alpha`) и в сохранённых фильтрах, и переименование ключа
    сломало бы всё это молча.
    """

    name: str = UNSET
    description: str = UNSET
    status: ProjectStatus = UNSET
    lead: Actor = UNSET
    members: Sequence[Actor] = UNSET
    start_date: date | None = UNSET
    end_date: date | None = UNSET
    tags: Sequence[str] = UNSET
    portfolio: Portfolio | None = UNSET


@dataclass(frozen=True, slots=True)
class PortfolioItem:
    """Одна позиция состава портфеля: вложенный портфель или проект.

    Вид лежит рядом с объектом, а не выводится из его типа вызывающим: HTTP-слою нужно
    поставить в ответ поле `kind`, и `isinstance` в схеме означал бы второе место, где
    проект отличают от портфеля.
    """

    kind: PlanningKind
    entity: PlanningEntity


# --- Чтение ------------------------------------------------------------------------


async def get_project_by_key(session: AsyncSession, key: str) -> Project:
    """Проект по ключу или `project_not_found`.

    Адресация мягкая: `/projects/Alpha` находит `alpha`. Прав не проверяет — точка
    входа интерфейса `read_project`, а поиск зовёт эту функцию уже после проверки
    собственного действия.
    """
    project = await ProjectRepository(session).get_by_key(normalize_planning_key(key))
    if project is None:
        raise ProjectNotFoundError(details={"key": key})
    return project


async def get_portfolio_by_key(session: AsyncSession, key: str) -> Portfolio:
    """Портфель по ключу или `portfolio_not_found`."""
    portfolio = await PortfolioRepository(session).get_by_key(normalize_planning_key(key))
    if portfolio is None:
        raise PortfolioNotFoundError(details={"key": key})
    return portfolio


async def read_project(session: AsyncSession, key: str, *, initiator: Actor) -> Project:
    ensure_allowed(initiator, "project.read")
    return await get_project_by_key(session, key)


async def read_portfolio(session: AsyncSession, key: str, *, initiator: Actor) -> Portfolio:
    ensure_allowed(initiator, "portfolio.read")
    return await get_portfolio_by_key(session, key)


async def list_projects(
    session: AsyncSession,
    *,
    initiator: Actor,
    portfolio: Portfolio | None = None,
    status: ProjectStatus | None = None,
    is_archived: bool | None = None,
    lead: Actor | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Project]:
    """Страница проектов в порядке создания.

    `portfolio` отбирает **прямых** детей портфеля, а не всех потомков: «что лежит в
    этом портфеле» и «какие проекты под ним вообще» — разные вопросы, и второй
    обслуживает прогресс, а не список.
    """
    ensure_allowed(initiator, "project.list")
    return await ProjectRepository(session).list_page(
        portfolio_id=None if portfolio is None else portfolio.id,
        status=status,
        is_archived=is_archived,
        lead_id=None if lead is None else lead.id,
        limit=limit,
        cursor=cursor,
    )


async def list_portfolios(
    session: AsyncSession,
    *,
    initiator: Actor,
    parent: Portfolio | None = None,
    status: ProjectStatus | None = None,
    is_archived: bool | None = None,
    lead: Actor | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Portfolio]:
    """Страница портфелей в порядке создания; `parent` — прямые дети портфеля."""
    ensure_allowed(initiator, "portfolio.list")
    return await PortfolioRepository(session).list_page(
        parent_id=None if parent is None else parent.id,
        status=status,
        is_archived=is_archived,
        lead_id=None if lead is None else lead.id,
        limit=limit,
        cursor=cursor,
    )


async def portfolio_content(
    session: AsyncSession,
    portfolio: Portfolio,
    *,
    initiator: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[PortfolioItem]:
    """Состав портфеля одним списком: вложенные портфели и проекты вперемешку.

    Один упорядоченный список, а не две коллекции в одном ответе. Причина обязательная:
    оболочка ответа проекта отдаёт под `data` ровно одну коллекцию, а курсор указывает
    позицию в **одном** запросе — две страницы, склеенные в памяти, потеряли бы записи
    на первой же границе.

    Объекты грузятся двумя пачками по идентификаторам из страницы, а не по одному:
    состав портфеля читают целиком, и запрос на позицию превратил бы список из
    пятидесяти строк в пятьдесят запросов.
    """
    ensure_allowed(initiator, "portfolio.read", target=portfolio)
    page = await PortfolioRepository(session).content_page(
        portfolio.id,
        limit=limit,
        cursor=cursor,
    )

    portfolio_ids = [item_id for kind, item_id in page.items if kind is PlanningKind.PORTFOLIO]
    project_ids = [item_id for kind, item_id in page.items if kind is PlanningKind.PROJECT]
    nested = await PortfolioRepository(session).load_many(portfolio_ids)
    projects = await ProjectRepository(session).load_many(project_ids)

    items: list[PortfolioItem] = []
    for kind, item_id in page.items:
        entity = nested[item_id] if kind is PlanningKind.PORTFOLIO else projects[item_id]
        items.append(PortfolioItem(kind=kind, entity=entity))
    return Page(items=items, next_cursor=page.next_cursor)


async def list_project_issues(
    session: AsyncSession,
    project: Project,
    *,
    initiator: Actor,
    query: str | None = None,
    structured: Sequence[search_service.StructuredTerm] = (),
    saved_filter_id: uuid.UUID | None = None,
    sort: Sequence[str] = (),
    fields: Sequence[str] = (),
    limit: int | None = None,
    cursor: str | None = None,
) -> search_service.SearchOutcome:
    """Задачи проекта — это поиск с приклеенным условием `project: <ключ>`.

    Своего отбора у проекта нет и быть не должно: в проекте тысячи задач из разных
    очередей, и клиенту нужны те же язык запросов, сортировка и выбор полей, что и в
    общем поиске. Набор параметров, повторяющий половину поиска, разошёлся бы с ним на
    первом же краевом случае — а разошёлся бы молча, разной выдачей на одинаковый по
    смыслу вопрос.

    Условие проекта добавляется **первым слагаемым** и склеивается по `and`, поэтому
    сузить выдачу клиент может, а расширить её за пределы проекта — нет.
    """
    scope = search_service.StructuredTerm(
        name=SystemField.PROJECT.value,
        values=[project.key],
    )
    return await search_service.search_issues(
        session,
        initiator=initiator,
        query=query,
        structured=[scope, *structured],
        saved_filter_id=saved_filter_id,
        sort=sort,
        fields=fields,
        limit=limit,
        cursor=cursor,
    )


# --- Прогресс ----------------------------------------------------------------------


async def project_progress(
    session: AsyncSession,
    projects: Sequence[Project],
) -> dict[uuid.UUID, Progress]:
    """Прогресс каждого проекта набора. Проект без задач получает нулевой `Progress`.

    Нулевой, а не отсутствующий: `GROUP BY` не возвращает строк для пустых групп, и
    разбирать эту особенность SQL должен один вызывающий, а не каждый. `Progress.ratio`
    у него `None` — «считать не по чему», и это не то же самое, что «сделано 0%».
    """
    if not projects:
        return {}
    counted = await ProjectRepository(session).progress_of([project.id for project in projects])
    return {project.id: counted.get(project.id, Progress()) for project in projects}


async def portfolio_progress(
    session: AsyncSession,
    portfolios: Sequence[Portfolio],
) -> dict[uuid.UUID, Progress]:
    """Прогресс каждого портфеля набора, сложенный по задачам всех его потомков.

    Портфель без единого проекта с задачами получает нулевой `Progress` — по той же
    причине и с тем же смыслом, что у пустого проекта.
    """
    if not portfolios:
        return {}
    counted = await PortfolioRepository(session).progress_of([item.id for item in portfolios])
    return {item.id: counted.get(item.id, Progress()) for item in portfolios}


async def portfolio_child_counts(
    session: AsyncSession,
    portfolios: Sequence[Portfolio],
) -> dict[uuid.UUID, tuple[int, int]]:
    """Сколько прямых проектов и вложенных портфелей у каждого портфеля набора.

    Пара чисел в карточке заменяет обход состава там, где состав не нужен целиком:
    список портфелей показывает «3 проекта, 1 портфель», не читая ни одного из них.
    """
    if not portfolios:
        return {}
    ids = [item.id for item in portfolios]
    projects = await ProjectRepository(session).count_in_portfolios(ids)
    nested = await PortfolioRepository(session).count_children(ids)
    return {item.id: (projects.get(item.id, 0), nested.get(item.id, 0)) for item in portfolios}


# --- Создание ----------------------------------------------------------------------


async def create_project(
    session: AsyncSession,
    *,
    initiator: Actor,
    key: str,
    name: str,
    description: str = "",
    status: ProjectStatus = ProjectStatus.NOT_STARTED,
    lead: Actor | None = None,
    members: Sequence[Actor] = (),
    start_date: date | None = None,
    end_date: date | None = None,
    tags: Sequence[str] = (),
    portfolio: Portfolio | None = None,
) -> Project:
    """Заводит проект. Ответственный по умолчанию — тот, кто его создаёт.

    Как и у задачи: проект, заведённый агентом, отвечает агентом, а не владельцем
    установки. Задач у нового проекта нет — их добавляют отдельно, потому что задача
    уже существует в своей очереди к моменту, когда её решают отнести к результату.
    """
    ensure_allowed(initiator, "project.create")
    stored_key = validate_planning_key(key, kind=PlanningKind.PROJECT, error=InvalidProjectKeyError)
    await _ensure_key_free(session, stored_key, kind=PlanningKind.PROJECT)
    responsible = _validated_lead(lead or initiator)
    stored_members = _validated_members(members, kind=PlanningKind.PROJECT)
    if portfolio is not None:
        _ensure_portfolio_accepts(portfolio)

    validate_period(start_date, end_date, kind=PlanningKind.PROJECT)
    project = Project(
        key=stored_key,
        name=validate_planning_name(name, kind=PlanningKind.PROJECT),
        description=validate_planning_description(description, kind=PlanningKind.PROJECT),
        status=status,
        lead=responsible,
        members=stored_members,
        start_date=start_date,
        end_date=end_date,
        tags=normalize_tags(tags, error=InvalidProjectError),
        portfolio=portfolio,
    )
    await ProjectRepository(session).add(project)
    await events_service.record_planning_change(
        session,
        project,
        initiator=initiator,
        action="project.create",
    )
    return project


async def create_portfolio(
    session: AsyncSession,
    *,
    initiator: Actor,
    key: str,
    name: str,
    description: str = "",
    status: ProjectStatus = ProjectStatus.NOT_STARTED,
    lead: Actor | None = None,
    members: Sequence[Actor] = (),
    start_date: date | None = None,
    end_date: date | None = None,
    tags: Sequence[str] = (),
    parent: Portfolio | None = None,
) -> Portfolio:
    """Заводит портфель. Цикл при создании невозможен: у нового портфеля детей нет."""
    ensure_allowed(initiator, "portfolio.create")
    stored_key = validate_planning_key(
        key, kind=PlanningKind.PORTFOLIO, error=InvalidPortfolioKeyError
    )
    await _ensure_key_free(session, stored_key, kind=PlanningKind.PORTFOLIO)
    responsible = _validated_lead(lead or initiator)
    stored_members = _validated_members(members, kind=PlanningKind.PORTFOLIO)
    if parent is not None:
        _ensure_portfolio_accepts(parent)

    validate_period(start_date, end_date, kind=PlanningKind.PORTFOLIO)
    portfolio = Portfolio(
        key=stored_key,
        name=validate_planning_name(name, kind=PlanningKind.PORTFOLIO),
        description=validate_planning_description(description, kind=PlanningKind.PORTFOLIO),
        status=status,
        lead=responsible,
        members=stored_members,
        start_date=start_date,
        end_date=end_date,
        tags=normalize_tags(tags, error=InvalidPortfolioError),
        parent=parent,
    )
    await PortfolioRepository(session).add(portfolio)
    await events_service.record_planning_change(
        session,
        portfolio,
        initiator=initiator,
        action="portfolio.create",
    )
    return portfolio


# --- Изменение ---------------------------------------------------------------------


async def update_project(
    session: AsyncSession,
    project: Project,
    *,
    initiator: Actor,
    changes: PlanningChanges,
    action: str = "project.update",
) -> tuple[Project, tuple[IssueChange, ...]]:
    """Единая точка изменения проекта: применяются только переданные поля.

    Возвращает **фактические** изменения — поле, переданное со значением, равным
    текущему, записи не даёт и события не порождает. Ровно то же правило, что у задачи,
    и по той же причине: иначе подписчик реагировал бы на изменение, которого не было.

    Правка архивного проекта разрешена: архив запрещает приём новых задач, а не
    исправление названия. Так же ведёт себя архивная очередь.
    """
    ensure_allowed(initiator, action, target=project)

    recorded: list[IssueChange] = []
    _apply_common(project, changes, kind=PlanningKind.PROJECT, recorded=recorded)
    if is_set(changes.portfolio):
        if changes.portfolio is not None:
            _ensure_portfolio_accepts(changes.portfolio)
        after_id = None if changes.portfolio is None else changes.portfolio.id
        if after_id != project.portfolio_id:
            _record(recorded, "portfolio", _key_of(project.portfolio), _key_of(changes.portfolio))
            project.portfolio = changes.portfolio

    if not recorded:
        return project, ()

    await ProjectRepository(session).flush()
    await events_service.record_planning_change(
        session,
        project,
        initiator=initiator,
        action=action,
        changes=tuple(recorded),
    )
    return project, tuple(recorded)


async def update_portfolio(
    session: AsyncSession,
    portfolio: Portfolio,
    *,
    initiator: Actor,
    changes: PlanningChanges,
    action: str = "portfolio.update",
) -> tuple[Portfolio, tuple[IssueChange, ...]]:
    """Единая точка изменения портфеля. Смена родителя проверяется на цикл."""
    ensure_allowed(initiator, action, target=portfolio)

    recorded: list[IssueChange] = []
    _apply_common(portfolio, changes, kind=PlanningKind.PORTFOLIO, recorded=recorded)
    if is_set(changes.portfolio):
        after_id = None if changes.portfolio is None else changes.portfolio.id
        if after_id != portfolio.parent_id:
            if changes.portfolio is not None:
                _ensure_portfolio_accepts(changes.portfolio)
                await _ensure_no_cycle(session, portfolio, parent=changes.portfolio)
            _record(recorded, "portfolio", _key_of(portfolio.parent), _key_of(changes.portfolio))
            portfolio.parent = changes.portfolio

    if not recorded:
        return portfolio, ()

    await PortfolioRepository(session).flush()
    await events_service.record_planning_change(
        session,
        portfolio,
        initiator=initiator,
        action=action,
        changes=tuple(recorded),
    )
    return portfolio, tuple(recorded)


async def move_project(
    session: AsyncSession,
    project: Project,
    *,
    initiator: Actor,
    portfolio: Portfolio | None,
) -> Project:
    """Переносит проект в другой портфель; `None` вынимает его наверх.

    Обёртка над единой точкой изменения, а не собственное присваивание, — как
    `assign_issue` у задачи. Отдельный сценарий существует потому, что перенос
    самостоятельная операция планирования: у него свой маршрут и своё действие в
    проверке прав, а когда появятся роли, разрешать «двигать проекты по портфелям»
    придётся отдельно от «править описание».
    """
    updated, _ = await update_project(
        session,
        project,
        initiator=initiator,
        changes=PlanningChanges(portfolio=portfolio),
    )
    return updated


async def move_portfolio(
    session: AsyncSession,
    portfolio: Portfolio,
    *,
    initiator: Actor,
    parent: Portfolio | None,
) -> Portfolio:
    """Переносит портфель внутрь другого; `None` делает его корневым. Цикл запрещён."""
    updated, _ = await update_portfolio(
        session,
        portfolio,
        initiator=initiator,
        changes=PlanningChanges(portfolio=parent),
    )
    return updated


async def archive_project(session: AsyncSession, project: Project, *, initiator: Actor) -> Project:
    """Убирает проект в архив. Задачи остаются в нём, прогресс продолжает считаться.

    Идемпотентно — повторный вызов ничего не меняет и ошибкой не считается: клиент, не
    получивший ответ и повторивший запрос, не должен получать отказ на выполненное
    действие. Так же ведут себя архивация очереди и отзыв токена.
    """
    return await _set_archived(session, project, initiator=initiator, archived=True)


async def restore_project(session: AsyncSession, project: Project, *, initiator: Actor) -> Project:
    """Возвращает проект из архива. Тоже идемпотентно."""
    return await _set_archived(session, project, initiator=initiator, archived=False)


async def archive_portfolio(
    session: AsyncSession,
    portfolio: Portfolio,
    *,
    initiator: Actor,
) -> Portfolio:
    """Убирает портфель в архив. Вложенные проекты и портфели остаются как были.

    Каскадная архивация состава здесь была бы ловушкой: вернуть портфель из архива
    после неё нельзя — неизвестно, какие из его детей лежали в архиве **до** операции.
    """
    return await _set_archived(session, portfolio, initiator=initiator, archived=True)


async def restore_portfolio(
    session: AsyncSession,
    portfolio: Portfolio,
    *,
    initiator: Actor,
) -> Portfolio:
    """Возвращает портфель из архива. Идемпотентно."""
    return await _set_archived(session, portfolio, initiator=initiator, archived=False)


# --- Состав проекта ----------------------------------------------------------------


async def add_issues(
    session: AsyncSession,
    project: Project,
    *,
    initiator: Actor,
    issues: Sequence[Issue],
) -> list[issues_service.IssueMutation]:
    """Добавляет задачи в проект. Задача, уже входящая в него, изменения не даёт.

    Каждая задача проходит через единую точку изменения, поэтому у каждой растёт версия
    и появляется запись в истории. Идемпотентность отсюда же: `apply_issue_changes`
    возвращает пустой список изменений, когда прислали то, что уже стоит.

    Задача, которая лежала в **другом** проекте, переезжает молча — и это осознанно:
    отказ означал бы обязательный двухшаговый ритуал «сначала вынь, потом положи», а
    переезд между проектами виден в истории задачи как обычное изменение поля.
    """
    _ensure_project_accepts(project)
    return [
        await issues_service.apply_issue_changes(
            session,
            issue,
            initiator=initiator,
            changes=issues_service.IssueChanges(project=project),
            action="issue.set_project",
        )
        for issue in issues
    ]


async def remove_issue(
    session: AsyncSession,
    project: Project,
    *,
    initiator: Actor,
    issue: Issue,
) -> issues_service.IssueMutation:
    """Убирает задачу из проекта. Задача остаётся жить в своей очереди.

    Задача, входящая в **другой** проект, не трогается: убрать её отсюда нельзя, потому
    что здесь её нет. Отказ в этом случае был бы честнее молчания — иначе клиент,
    перепутавший проект, получил бы `204` и уверенность, что задача вынута, тогда как
    она осталась в чужом проекте.
    """
    if issue.project_id != project.id:
        raise ProjectNotFoundError(
            details={
                "key": project.key,
                "issue": issue.key,
                "reason": "issue_not_in_project",
            },
        )
    return await issues_service.apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=issues_service.IssueChanges(project=None),
        action="issue.set_project",
    )


# --- Внутреннее --------------------------------------------------------------------


async def _ensure_key_free(session: AsyncSession, key: str, *, kind: PlanningKind) -> None:
    """Ключ свободен внутри своего вида. Проверка сценария поверх ограничения базы.

    Уникальность держит `UniqueConstraint`, но без этой проверки клиент получал бы
    голый `409 conflict` с именем ограничения вместо внятного «ключ занят».
    """
    existing: PlanningEntity | None
    if kind is PlanningKind.PROJECT:
        existing = await ProjectRepository(session).get_by_key(key)
    else:
        existing = await PortfolioRepository(session).get_by_key(key)
    if existing is not None:
        raise _KEY_TAKEN_ERRORS[kind](details={"key": key})


def _validated_lead(lead: Actor) -> Actor:
    """Ответственным нельзя назначить отключённого актора.

    Уже записанная ссылка при этом остаётся: отключение — способ убрать агента, не
    ломая историю. Запрещено только назначать его заново. То же правило, что у
    исполнителя задачи.
    """
    if not lead.is_active:
        raise ActorInactiveError(details={"key": lead.key, "reason": "cannot_lead_project"})
    return lead


def _validated_members(members: Sequence[Actor], *, kind: PlanningKind) -> list[Actor]:
    """Участники без повторов и без отключённых, с сохранением порядка.

    Повтор — не ошибка запроса, а обычная небрежность клиента, поэтому он отбрасывается
    молча. Отключённый актор отвергается: список участников читают уведомления, и
    молчаливое выбрасывание оставило бы клиента с уверенностью, что он кого-то добавил.
    """
    unique: list[Actor] = []
    seen: set[Any] = set()
    for member in members:
        if member.id in seen:
            continue
        if not member.is_active:
            raise ActorInactiveError(
                details={"key": member.key, "reason": "cannot_join_project"},
            )
        seen.add(member.id)
        unique.append(member)
    if len(unique) > MAX_PLANNING_MEMBERS:
        raise INVALID_ERRORS[kind](
            details={
                "kind": kind.value,
                "field": "members",
                "reason": "too_many",
                "max": MAX_PLANNING_MEMBERS,
                "got": len(unique),
            },
        )
    return unique


def _ensure_portfolio_accepts(portfolio: Portfolio) -> None:
    """В архивный портфель ничего не кладут: приём нового состава запрещён."""
    if portfolio.is_archived:
        raise PortfolioArchivedError(
            details={"key": portfolio.key, "reason": "cannot_accept_content"},
        )


def _ensure_project_accepts(project: Project) -> None:
    """Архивный проект новых задач не принимает."""
    if project.is_archived:
        raise ProjectArchivedError(details={"key": project.key, "reason": "cannot_accept_issues"})


async def _ensure_no_cycle(
    session: AsyncSession,
    portfolio: Portfolio,
    *,
    parent: Portfolio,
) -> None:
    """Вложение не должно замкнуть кольцо портфелей.

    Проверяется подъёмом от будущего родителя вверх: кольцо возникнет ровно тогда,
    когда переносимый портфель уже находится над ним. Сам портфель считается своим
    предком, поэтому «вложить в себя» отсекается тем же условием и отдельной проверки
    не требует.

    Проверка живёт в сценарии, а не в схеме: отсутствие цикла — свойство графа целиком,
    а не строки, и внешним ключом его не выразить. На гонку двух одновременных
    переносов она не рассчитана — от кольца, которое всё-таки возникло, читателей
    защищает ограничитель глубины в обходе.
    """
    if await PortfolioRepository(session).has_ancestor(
        portfolio_id=parent.id,
        ancestor_id=portfolio.id,
    ):
        raise PortfolioCycleError(
            details={"key": portfolio.key, "parent": parent.key, "reason": "would_close_a_cycle"},
        )


def _apply_common(
    entity: PlanningEntity,
    changes: PlanningChanges,
    *,
    kind: PlanningKind,
    recorded: list[IssueChange],
) -> None:
    """Поля, одинаковые у проекта и портфеля: сравнить, записать изменение, присвоить.

    «Было» и «стало» сразу в том виде, в каком уедут в событие: актор — ключом, дата —
    строкой `YYYY-MM-DD`. ORM-объект туда класть нельзя: событие переживает транзакцию,
    а объект — нет.
    """
    error = INVALID_ERRORS[kind]

    if is_set(changes.name):
        name = validate_planning_name(changes.name, kind=kind)
        if name != entity.name:
            _record(recorded, "name", entity.name, name)
            entity.name = name
    if is_set(changes.description):
        description = validate_planning_description(changes.description, kind=kind)
        if description != entity.description:
            _record(recorded, "description", entity.description, description)
            entity.description = description
    if is_set(changes.status) and changes.status is not entity.status:
        _record(recorded, "status", entity.status.value, changes.status.value)
        entity.status = changes.status
    if is_set(changes.lead):
        lead = _validated_lead(changes.lead)
        if lead.id != entity.lead_id:
            _record(recorded, "lead", entity.lead.key, lead.key)
            entity.lead = lead
    if is_set(changes.members):
        members = _validated_members(changes.members, kind=kind)
        before = sorted(member.key for member in entity.members)
        after = sorted(member.key for member in members)
        if before != after:
            _record(recorded, "members", before, after, force=True)
            entity.members = members

    # Период проверяется целиком, а не по одной границе: клиент вправе прислать только
    # `end_date`, и сравнивать её надо с той датой начала, которая останется после
    # правки, а не с той, что была до неё.
    start = changes.start_date if is_set(changes.start_date) else entity.start_date
    end = changes.end_date if is_set(changes.end_date) else entity.end_date
    validate_period(start, end, kind=kind)
    if is_set(changes.start_date) and changes.start_date != entity.start_date:
        _record(recorded, "start_date", _day(entity.start_date), _day(changes.start_date))
        entity.start_date = changes.start_date
    if is_set(changes.end_date) and changes.end_date != entity.end_date:
        _record(recorded, "end_date", _day(entity.end_date), _day(changes.end_date))
        entity.end_date = changes.end_date

    if is_set(changes.tags):
        tags = normalize_tags(changes.tags, error=error)
        if tags_differ(entity.tags, tags):
            _record(recorded, "tags", list(entity.tags), tags, force=True)
            # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации
            # внутри значения, и UPDATE просто не уйдёт. Присваивается новый список.
            entity.tags = tags


async def _set_archived[EntityT: (Project, Portfolio)](
    session: AsyncSession,
    entity: EntityT,
    *,
    initiator: Actor,
    archived: bool,
) -> EntityT:
    """Общее тело архивации и возврата из архива для проекта и портфеля.

    Действие для проверки прав и тип события выводятся из вида объекта и направления —
    отсюда четыре типа событий (`project.archived`, `project.restored` и их аналоги у
    портфеля) и ни одной копии этой функции.
    """
    kind = PlanningKind.PORTFOLIO if isinstance(entity, Portfolio) else PlanningKind.PROJECT
    action = f"{kind.value}.{'archive' if archived else 'restore'}"
    ensure_allowed(initiator, action, target=entity)

    if entity.is_archived == archived:
        return entity

    entity.is_archived = archived
    entity.archived_at = datetime.now(UTC) if archived else None
    repository: ProjectRepository | PortfolioRepository = (
        PortfolioRepository(session)
        if kind is PlanningKind.PORTFOLIO
        else ProjectRepository(session)
    )
    await repository.flush()
    await events_service.record_planning_change(
        session,
        entity,
        initiator=initiator,
        action=action,
        changes=(IssueChange(field="is_archived", before=not archived, after=archived),),
    )
    return entity


def _record(
    recorded: list[IssueChange],
    field: str,
    before: Any,
    after: Any,
    *,
    force: bool = False,
) -> None:
    """Записывает изменение, если оно есть. `force` — для уже сравненных значений.

    Запись — тот же `IssueChange`, что и у задачи, и это не оплошность именования:
    форма «поле, было, стало» одна на весь проект, её кодирует одна функция
    (`encode_changes`), и подписчик обязан разбирать полезную нагрузку события о
    проекте тем же кодом, что и о задаче.
    """
    if not force and before == after:
        return
    recorded.append(IssueChange(field=field, before=before, after=after))


def _key_of(entity: PlanningEntity | None) -> str | None:
    return None if entity is None else entity.key


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()
