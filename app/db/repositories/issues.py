"""Выборки и изменения по задачам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
`flush` вызывать можно — он отправляет запрос, не фиксируя транзакцию.

Здесь же лежат все подсчёты «сколько задач ссылается на X»: на них держится защита
справочников и реестра полей (`app/services/issue_usage.py`). Собраны они в одном
классе намеренно — запрос по `values JSONB` должен ложиться на GIN-индекс, и второй
такой запрос, написанный в другом модуле по памяти, потерял бы индекс молча.
"""

import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.issue import Issue
from app.db.pagination import Page, paginate


class IssueRepository:
    """Доступ к таблице `issues` и к её счётчикам использования."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, issue_id: uuid.UUID) -> Issue | None:
        return await self._session.get(Issue, issue_id)

    async def get_by_key(self, key: str) -> Issue | None:
        statement = select(Issue).where(Issue.key == key)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def existing_keys(self, keys: set[str]) -> set[str]:
        """Какие из ключей принадлежат существующим задачам.

        Одним запросом на весь набор: значения кастомных полей со ссылками на задачи
        проверяются пачкой при каждом сохранении, и отдельный `SELECT` на ссылку
        превратил бы это в десяток запросов.
        """
        if not keys:
            return set()
        statement = select(Issue.key).where(Issue.key.in_(keys))
        return set((await self._session.scalars(statement)).all())

    async def list_page(
        self,
        *,
        queue_id: uuid.UUID | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Issue]:
        """Страница задач в порядке создания.

        Фильтр здесь ровно один — очередь. Полноценный отбор (статус, исполнитель,
        значения кастомных полей, язык запросов) строит задача 12, и заводить сейчас
        половину её параметров значило бы получить два разных набора фильтров в одном
        API.
        """
        statement = select(Issue)
        if queue_id is not None:
            statement = statement.where(Issue.queue_id == queue_id)
        return await paginate(self._session, statement, Issue, limit=limit, cursor=cursor)

    async def add(self, issue: Issue) -> Issue:
        self._session.add(issue)
        await self._session.flush()
        return issue

    async def delete(self, issue: Issue) -> None:
        await self._session.delete(issue)
        await self._session.flush()

    async def set_followers(self, issue: Issue, followers: list[Actor]) -> Issue:
        """Заменяет набор наблюдателей целиком.

        Через коллекцию связи, а не запросами: коллекция загружена стратегией
        `selectin`, и обновление её через SQL оставило бы объект со старым составом —
        ответ ушёл бы с прежним списком наблюдателей.
        """
        issue.followers = followers
        await self._session.flush()
        return issue

    # --- Счётчики использования --------------------------------------------------

    async def count_by_status(self, status_id: uuid.UUID) -> int:
        return await self._count(Issue.status_id == status_id)

    async def count_by_issue_type(self, issue_type_id: uuid.UUID) -> int:
        return await self._count(Issue.issue_type_id == issue_type_id)

    async def count_by_resolution(self, resolution_id: uuid.UUID) -> int:
        return await self._count(Issue.resolution_id == resolution_id)

    async def count_in_queue(self, queue_id: uuid.UUID) -> int:
        return await self._count(Issue.queue_id == queue_id)

    async def count_with_field(self, field_ref: str) -> int:
        """Сколько задач имеет значение этого поля.

        `values ? :ref` — проверка наличия ключа в JSONB; оператор ложится на GIN-индекс
        `ix_issues_values`. Адресация ссылкой (`severity`, `TRK.severity`), потому что
        именно она служит ключом в `values` — см. `app/domain/fields.py`.
        """
        return await self._count(Issue.values.has_key(field_ref))

    async def count_with_field_value(self, field_ref: str, value: Any) -> int:
        """Сколько задач держит в этом поле именно это значение.

        Проверяются оба варианта хранения: одиночное поле держит скаляр, множественное —
        массив. `@>` («содержит») для массива истинно, если значение есть среди
        элементов, поэтому одного выражения на оба случая не хватает.
        """
        scalar = Issue.values.contains({field_ref: value})
        inside_array = Issue.values.contains({field_ref: [value]})
        return await self._count(scalar | inside_array)

    async def keys_referencing(self, field_refs: list[str], key: str) -> list[str]:
        """Ключи задач, у которых в одном из полей стоит ссылка на эту задачу.

        Поля-ссылки перечисляются вызывающим: какие поля хранят ссылку на задачу, знает
        реестр, а не эта таблица. Проверяются оба варианта хранения — скаляр и массив, —
        по той же причине, что и в `count_with_field_value`.
        """
        if not field_refs:
            return []
        conditions = [
            Issue.values.contains({ref: key}) | Issue.values.contains({ref: [key]})
            for ref in field_refs
        ]
        statement = select(Issue.key).where(or_(*conditions)).order_by(Issue.key)
        return list(await self._session.scalars(statement))

    async def move_to_status(
        self,
        *,
        from_status_id: uuid.UUID,
        to_status_id: uuid.UUID,
        queue_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID, str]]:
        """Переносит задачи между статусами и возвращает идентификатор и ключ каждой.

        Версия задачи увеличивается тем же запросом. Иначе клиент, прочитавший задачу
        до переноса, прошёл бы проверку оптимистичной блокировки и записал бы поверх
        нового статуса, ничего не заметив.

        `RETURNING` появился в задаче 06: перенос обязан оставить запись в истории
        каждой затронутой задачи, а для этого нужны их идентификаторы. Цена известна и
        принята: перенос ста тысяч задач вернёт сто тысяч строк в память. Считать это
        ограничением стоит с самого начала — перенос делается ради удаления статуса, и
        такие объёмы в нём реальны.

        `synchronize_session=False`: массовый `UPDATE` идёт мимо объектов сессии, и
        загруженные задачи после него держат старый статус. Для сценария переноса это
        безопасно — он отдаёт ключи, а не объекты, — но помнить об этом обязательно.
        """
        statement = (
            update(Issue)
            .where(Issue.status_id == from_status_id)
            .values(status_id=to_status_id, version=Issue.version + 1, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
        if queue_id is not None:
            statement = statement.where(Issue.queue_id == queue_id)
        result = await self._session.execute(statement.returning(Issue.id, Issue.key))
        return [(row.id, row.key) for row in result]

    async def _count(self, condition: Any) -> int:
        statement = select(func.count()).select_from(Issue).where(condition)
        return (await self._session.scalar(statement)) or 0
