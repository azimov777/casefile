"""Сценарии тегов: словарь заведённых меток и точечное управление тегами задачи.

## Тег — не объект, а значение

Отдельной таблицы у тегов нет: они лежат плоским списком в `issues.tags`
(`app/db/models/issue.py`). Поэтому «существующие теги» — не справочник, который
кто-то ведёт, а словарь, собираемый по задачам. Отсюда и главное свойство: тег
появляется в словаре вместе с первой задачей и исчезает вместе с последней, а завести
или переименовать его отдельно нельзя.

## Добавление и снятие — обёртки над единой точкой изменения задачи

Полная замена набора уже есть в частичном обновлении (`PATCH` с `tags`). Точечные
сценарии нужны потому, что замена требует прислать весь набор: клиент, добавляющий
одну метку, вынужден сначала прочитать задачу — и затрёт метку, которую тем временем
поставил кто-то другой. Здесь же новый набор считается от текущего состояния.

Обе операции идемпотентны: повторное добавление и снятие отсутствующего тега ничего
не меняют, версию не поднимают и события не порождают. Это следует из правила
«фактических изменений» в `apply_issue_changes`, а не выражено здесь отдельно.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import IssueRepository
from app.domain.issues import TagUsage, normalize_tags
from app.services.issues import IssueChanges, IssueMutation, apply_issue_changes
from app.services.permissions import ensure_allowed


async def list_tags(
    session: AsyncSession,
    *,
    initiator: Actor,
    queue: Queue | None = None,
    query: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[TagUsage]:
    """Страница словаря тегов по алфавиту: сам тег и число задач с ним.

    Нужен, чтобы теги не размножались написаниями: без словаря в одной установке
    заводятся `release`, `Release` и `релиз` про одно и то же. Число задач — признак
    живого тега: по нему видно, какой из похожих вариантов прижился.
    """
    ensure_allowed(initiator, "issue.tags")
    return await IssueRepository(session).list_tags_page(
        queue_id=None if queue is None else queue.id,
        query=query,
        limit=limit,
        cursor=cursor,
    )


async def add_tags(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    tags: Sequence[str],
    expected_version: int | None = None,
) -> IssueMutation:
    """Добавляет теги к задаче, не трогая уже поставленные.

    Новый набор считается от текущего состояния, а повторы отбрасывает нормализация
    (`normalize_tags`) — без учёта регистра и с сохранением первого написания. Поэтому
    добавление `Release` к задаче, где уже есть `release`, оставляет `release`: два
    написания одной метки означали бы два разных фильтра.
    """
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(tags=[*issue.tags, *tags]),
        action="issue.tag",
        expected_version=expected_version,
    )


async def remove_tags(
    session: AsyncSession,
    issue: Issue,
    *,
    initiator: Actor,
    tags: Sequence[str],
    expected_version: int | None = None,
) -> IssueMutation:
    """Снимает теги с задачи. Сравнение без учёта регистра: `Release` снимает `release`.

    Иначе клиент, увидевший тег в одном написании и приславший его в другом, получил
    бы успешный ответ и неснятый тег — молчаливый сбой ровно там, где он незаметен.
    """
    removed = {tag.casefold() for tag in normalize_tags(tags)}
    remaining = [tag for tag in issue.tags if tag.casefold() not in removed]
    return await apply_issue_changes(
        session,
        issue,
        initiator=initiator,
        changes=IssueChanges(tags=remaining),
        action="issue.untag",
        expected_version=expected_version,
    )
