"""Выборки и вставки по реестру полей.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.
`flush` вызывать можно — он отправляет запрос, не фиксируя транзакцию.
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import IssueType
from app.db.models.field import Field, FieldIssueType
from app.db.pagination import Page, paginate


class FieldRepository:
    """Доступ к таблицам `fields` и `field_issue_types`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, field_id: uuid.UUID) -> Field | None:
        return await self._session.get(Field, field_id)

    async def get(self, key: str, queue_id: uuid.UUID | None) -> Field | None:
        """Поле по ключу в точно указанной области.

        `queue_id=None` ищет именно глобальное поле, а не «любое с таким ключом»:
        глобальное `severity` и локальное `TRK.severity` — два разных поля, и подмена
        одного другим дала бы задаче значение не того поля.
        """
        statement = select(Field).where(Field.key == key)
        if queue_id is None:
            statement = statement.where(Field.queue_id.is_(None))
        else:
            statement = statement.where(Field.queue_id == queue_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_page(
        self,
        *,
        queue_id: uuid.UUID | None = None,
        include_global: bool = True,
        issue_type_id: uuid.UUID | None = None,
        is_hidden: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Field]:
        """Страница реестра.

        Без очереди видны только глобальные поля: локальное принадлежит своей очереди
        и вне её контекста смысла не имеет.

        Порядок — курсорный, по паре `(created_at, id)`, а не по `display_order`.
        Это осознанно: курсор во всём проекте построен на этой паре, а `display_order`
        не уникален и страницы начали бы терять и дублировать записи. Порядок показа
        применяется там, где набор отдаётся целиком, — в `list_applicable`.
        """
        statement = select(Field).where(*self._scope_conditions(queue_id, include_global))
        if issue_type_id is not None:
            statement = statement.where(self._applicability_condition(issue_type_id))
        if is_hidden is not None:
            statement = statement.where(Field.is_hidden.is_(is_hidden))
        return await paginate(self._session, statement, Field, limit=limit, cursor=cursor)

    async def list_applicable(
        self,
        queue_id: uuid.UUID | None,
        issue_type_id: uuid.UUID | None = None,
        *,
        include_hidden: bool = False,
    ) -> list[Field]:
        """Поля, применимые к связке «очередь + тип задачи», в порядке показа.

        Без пагинации намеренно: это конфигурация, она собирается целиком — ради этого
        и существует эндпоинт конфигурации очереди. Тем же набором пользуется
        валидатор значений, поэтому скрытые поля можно попросить включить: валидатору
        они нужны, чтобы отличить «такого поля нет» от «поле скрыто».
        """
        statement = select(Field).where(*self._scope_conditions(queue_id, include_global=True))
        if issue_type_id is not None:
            statement = statement.where(self._applicability_condition(issue_type_id))
        if not include_hidden:
            statement = statement.where(Field.is_hidden.is_(False))
        statement = statement.order_by(Field.display_order, Field.created_at, Field.id)
        return list((await self._session.scalars(statement)).unique())

    async def count_issue_type_bindings(self, issue_type_id: uuid.UUID) -> int:
        """Сколько полей ограничено этим типом задачи.

        Нужна сценарию справочников: удаление типа задачи каскадом стёрло бы
        ограничения и молча расширило поле «только для багов» до «для всех типов».
        """
        statement = (
            select(func.count())
            .select_from(FieldIssueType)
            .where(FieldIssueType.issue_type_id == issue_type_id)
        )
        return (await self._session.scalar(statement)) or 0

    async def add(self, field: Field) -> Field:
        self._session.add(field)
        await self._session.flush()
        return field

    async def delete(self, field: Field) -> None:
        await self._session.delete(field)
        await self._session.flush()

    async def set_issue_types(self, field: Field, issue_types: list[IssueType]) -> Field:
        """Заменяет набор ограничений целиком. Пустой список снимает их все.

        Через коллекцию связи, а не запросами: коллекция загружена стратегией
        `selectin`, и обновление её через SQL оставило бы объект со старым составом —
        ответ ушёл бы с прежним списком типов.
        """
        field.issue_types = issue_types
        await self._session.flush()
        return field

    def _scope_conditions(self, queue_id: uuid.UUID | None, include_global: bool) -> list[object]:
        if queue_id is None:
            return [Field.queue_id.is_(None)]
        if include_global:
            return [or_(Field.queue_id.is_(None), Field.queue_id == queue_id)]
        return [Field.queue_id == queue_id]

    def _applicability_condition(self, issue_type_id: uuid.UUID) -> object:
        """«Ограничений нет» или «есть ограничение ровно на этот тип».

        Именно в таком виде, а не левым соединением: соединение размножило бы строки
        поля по числу его ограничений, и страница пагинации поехала бы.
        """
        restricted = select(FieldIssueType.id).where(FieldIssueType.field_id == Field.id).exists()
        matches = (
            select(FieldIssueType.id)
            .where(
                FieldIssueType.field_id == Field.id,
                FieldIssueType.issue_type_id == issue_type_id,
            )
            .exists()
        )
        return or_(~restricted, matches)
