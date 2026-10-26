"""Область проектов агента в запросах: одно условие на все выборки и штамп на сессии.

Слово владельца — TRK~28#6: на участнике-агенте стоит режим доступа к проектам
(`app/domain/project_access.py`). Здесь два места, через которые он доходит до кода:

- `open_to` — условие «проект открыт этому доступу» для выборок: поиск, лента, входящая,
  обсуждения, список проектов. Выборка, не вызвавшая его, читает всё, поэтому условие одно
  на всех, а полный перечень выборок стережёт `tests/test_project_access_selections.py`;
- штамп на сессии (`stamp`, `access_of`) — для чтения по адресу. `authenticate` кладёт
  доступ в `session.info` той самой сессии, в которой идёт запрос, и каждое чтение проекта,
  области, обсуждения или задачи по адресу сверяется с ним в `app/services/projects.py` и
  `app/services/tasks.py`. Так забытое место вызова не открывает закрытый проект: проверка
  стоит в самом чтении, а не у каждого из ~80 вызывающих. Сессия живёт один запрос или
  один вызов MCP, поэтому доступ одного вызова другому не достаётся.

Сессия без штампа — вызов без ограничений: люди, общий агентский ключ, временные агенты,
команда и тесты (`UNRESTRICTED`).
"""

from typing import Any

from sqlalchemy import true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.project import Project
from app.domain.errors import ProjectNotAllowedError
from app.domain.project_access import UNRESTRICTED, ProjectAccess, ProjectAccessMode, is_open

_INFO_KEY = "project_access"


def stamp(session: AsyncSession, access: ProjectAccess) -> None:
    """Кладёт доступ вызова на сессию; читают его `access_of` и проверки чтения по адресу."""
    session.info[_INFO_KEY] = access


def access_of(session: AsyncSession) -> ProjectAccess:
    """Доступ вызова на этой сессии; без штампа — без ограничений."""
    found: ProjectAccess = session.info.get(_INFO_KEY, UNRESTRICTED)
    return found


def open_to(access: ProjectAccess, project_id: Any) -> ColumnElement[bool]:
    """Условие «проект с этим идентификатором открыт доступу» — одно на все выборки.

    `all` не сужает ничего (`true()`), `only` берёт названные, `except` отбрасывает
    названные. Пустой `only` не открывает ничего: `IN ()` у SQLAlchemy — ложь.
    """
    if access.mode is ProjectAccessMode.ONLY:
        return project_id.in_(sorted(access.project_ids))
    if access.mode is ProjectAccessMode.EXCEPT and access.project_ids:
        return project_id.not_in(sorted(access.project_ids))
    return true()


def require_open(session: AsyncSession, project: Project) -> None:
    """Проект открыт доступу вызова или `project_not_allowed` с ключом проекта.

    Доступ лежит на сессии, поэтому проверку не обойти, забыв передать автора: её делает
    само чтение по адресу. Без штампа проект открыт всегда.
    """
    if not is_open(access_of(session), project.id):
        raise ProjectNotAllowedError(details={"project": project.key})
