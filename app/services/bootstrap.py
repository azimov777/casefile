"""Первый экран одним запросом.

Интерфейс человека начинается с трёх вопросов: кто я, какие есть проекты и сколько
вопросов ждут моего ответа. По отдельности всё это уже отдают `GET /participants/{name}`,
`GET /projects` и `GET /questions`, но три запроса ради первой отрисовки — это три круга
задержки и три состояния загрузки в интерфейсе, который ещё ничего не показал.

«Кто я» — это участник, его учётная запись (TRK-113) **и сам токен**: его набор и
идентификатор (TRK-65). Набор —
единственное право в трекере (`CONCEPT.md`, 3.1): по нему интерфейс с первого кадра
решает, открыта ли запись вообще. Идентификатор — «я» в списке токенов, как имя
участника — «я» в записях дела: по нему интерфейс узнаёт собственный ключ, отзыв
которого оборвал бы сеанс.

Сценарий ничего не считает сам: он складывает результаты трёх существующих сценариев и
то, что аутентификация уже знает о токене. Своей логики здесь нет намеренно — иначе
счётчик первого экрана начал бы жить отдельно от «входящей» и однажды показал бы другое
число на тех же данных.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models.account import Account
from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.pagination import MAX_PAGE_SIZE
from app.domain.tokens import TokenScope
from app.services import accounts as accounts_service
from app.services import case as case_service
from app.services import projects as projects_service
from app.services.auth import Actor


@dataclass(frozen=True, slots=True)
class Bootstrap:
    """Состояние установки глазами того, кто только что открыл интерфейс."""

    #: Участник за токеном. Пуст у общего агентского токена: за ним стоит временный
    #: агент, которого в реестре нет.
    participant: Participant | None
    #: Учётная запись участника, если она есть: у агентов и у людей, заведённых до
    #: учётных записей и не получивших её, — нет. По флагу администратора интерфейс
    #: решает, показывать ли управление людьми (`CONCEPT.md`, 5.4).
    account: Account | None
    #: Токен, которым сделан запрос: тот же идентификатор, что в списке токенов. Есть у
    #: любого запроса снаружи, в том числе с общим агентским токеном.
    token_id: uuid.UUID
    #: Набор этого токена. У общего агентского токена участника нет, а набор есть.
    scope: TokenScope
    projects: list[Project]
    #: Открытые вопросы, адресованные `participant`. Ноль при пустом участнике — это
    #: факт, а не умолчание: адресовать временного агента нельзя (`CONCEPT.md`, 3.6),
    #: поэтому вопросов ему не приходит и прийти не может.
    open_questions: int


async def read_bootstrap(
    session: AsyncSession, *, actor: Actor, include_archived: bool = False
) -> Bootstrap:
    """Текущий участник, его токен с набором, проекты установки и число вопросов к нему.

    Архивные проекты в списке — только с `include_archived`, как у `list_projects`: это
    тот же сценарий. Вопросы в задачах архивных проектов счётчик не считает никогда — их
    не считает и «входящая» (`CONCEPT.md`, 3.6), а на ответ ей нечего предложить.

    Проекты читаются одной страницей с общим потолком размера: проект — единственный
    уровень группировки, и установка, у которой их больше двух сотен, первым экраном
    всё равно не описывается. Такой установке нужен `GET /api/v1/projects` с курсором;
    поле `projects_total` здесь не заводится, потому что объём первого экрана закрыт
    (`TRK-29`): текущий участник и его токен (`TRK-65`), проекты, число вопросов.

    Первый экран описывает токен, поэтому без токена отвечать нечем. Снаружи так не
    бывает — аутентификация без токена не проходит, и `Actor.token_id` пуст только у
    самого трекера, — но отдать вместо токена пустоту значило бы завести в контракте
    случай, который клиент обязан разбирать и не встретит никогда.
    """
    if actor.token_id is None:
        raise UnauthorizedError(
            message="The first screen describes a token, and this action has none",
            details={"reason": "first_screen_requires_token"},
        )
    page = await projects_service.list_projects(
        session, actor=actor, include_archived=include_archived, limit=MAX_PAGE_SIZE
    )
    open_questions = (
        0
        if actor.participant is None
        else await case_service.count_open_questions(session, participant=actor.participant)
    )
    return Bootstrap(
        participant=actor.participant,
        account=await accounts_service.account_of(session, actor.participant),
        token_id=actor.token_id,
        scope=actor.scope,
        projects=page.items,
        open_questions=open_questions,
    )
