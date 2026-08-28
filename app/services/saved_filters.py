"""Сценарии сохранённых фильтров: именованные запросы, которые переиспользуют все три интерфейса.

Фильтр хранит **описание** отбора, а не его результат, и ровно одним способом: либо
строкой на языке запросов, либо структурным набором условий. Почему не обоими сразу —
в `app/db/models/saved_filter.py`.

## Фильтр проверяется в момент сохранения

Описание разбирается и разрешается против реестра полей и справочников прямо здесь.
Стоит это одного лишнего прохода, а взамен опечатка в имени поля становится ошибкой
сохранения, а не пустой выдачей через неделю — в правиле автоматики, у которого никто
не смотрит логи.

Обратная сторона названа прямо: фильтр может протухнуть. Удалили поле, на которое он
ссылается, — сохранённый фильтр начнёт отвечать ошибкой при запуске. Это лучше тихой
пустой выдачи, и именно поэтому реестр не даёт удалить поле со значениями.

## Структурный фильтр хранится во внутреннем виде

В JSONB лежит список условий (`{"terms": [{"name": ..., "operator": ..., "values": ...}]}`),
а не тело HTTP-запроса. Схема API вправе меняться, а сохранённые фильтры обязаны
пережить её изменение; плюс тот же вид приходит из MCP, где никакого тела запроса нет.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.saved_filter import SavedFilter
from app.db.pagination import Page
from app.db.repositories import SavedFilterRepository
from app.domain.errors import (
    InvalidSavedFilterError,
    SavedFilterNameTakenError,
    SavedFilterNotFoundError,
)
from app.domain.query_language import parse_query, parse_sort_terms
from app.domain.search import MAX_QUERY_LENGTH, Operator, SearchFilter
from app.services import search as search_service
from app.services.permissions import ensure_allowed

MAX_FILTER_NAME_LENGTH = 255

#: Ключ, под которым в JSONB лежит список условий. Именованный, а не голый массив:
#: у описания фильтра появятся другие части (например, группировка), и менять форму
#: колонки ради этого не придётся.
_TERMS_KEY = "terms"


def filter_of(saved: SavedFilter) -> SearchFilter:
    """Сохранённое описание → внутреннее представление фильтра.

    Одна функция и для запуска фильтра, и для его проверки при сохранении: два разбора
    одного и того же описания однажды разошлись бы, и фильтр начал бы работать не так,
    как его проверили.
    """
    sort = parse_sort_terms(saved.sort)
    if saved.query is not None:
        parsed = parse_query(saved.query)
        return SearchFilter(root=parsed.root, sort=sort)
    return search_service.filter_from_structured(terms_of(saved), sort=saved.sort)


async def get_saved_filter(session: AsyncSession, filter_id: uuid.UUID) -> SavedFilter:
    """Фильтр по идентификатору или `saved_filter_not_found`.

    Прав не проверяет: точка входа интерфейса — `read_saved_filter`, а поиск зовёт эту
    функцию уже после проверки собственного действия.
    """
    saved = await SavedFilterRepository(session).get_by_id(filter_id)
    if saved is None:
        raise SavedFilterNotFoundError(details={"id": str(filter_id)})
    return saved


async def read_saved_filter(
    session: AsyncSession,
    filter_id: uuid.UUID,
    *,
    initiator: Actor,
) -> SavedFilter:
    ensure_allowed(initiator, "saved_filter.read")
    return await get_saved_filter(session, filter_id)


async def list_saved_filters(
    session: AsyncSession,
    *,
    initiator: Actor,
    owner: Actor | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[SavedFilter]:
    """Страница фильтров: без владельца — все, с владельцем — только его."""
    ensure_allowed(initiator, "saved_filter.list")
    return await SavedFilterRepository(session).list_page(
        owner_id=None if owner is None else owner.id,
        limit=limit,
        cursor=cursor,
    )


async def create_saved_filter(
    session: AsyncSession,
    *,
    initiator: Actor,
    name: str,
    description: str = "",
    query: str | None = None,
    structured: Sequence[search_service.StructuredTerm] | None = None,
    sort: Sequence[str] = (),
    owner: Actor | None = None,
) -> SavedFilter:
    """Заводит фильтр. Владелец по умолчанию — тот, кто его создаёт.

    Описание проверяется целиком до записи: разбирается язык, разрешаются имена полей
    и значения. Фильтр, который нельзя выполнить, сохранять незачем.
    """
    ensure_allowed(initiator, "saved_filter.create")
    stored_name = _validated_name(name)
    stored_owner = owner or initiator

    repository = SavedFilterRepository(session)
    if await repository.get_by_name(stored_owner.id, stored_name) is not None:
        raise SavedFilterNameTakenError(details={"name": stored_name, "owner": stored_owner.key})

    stored_query, stored_terms = await _validated_definition(
        session,
        query=query,
        structured=structured,
        sort=sort,
        initiator=initiator,
    )
    return await repository.add(
        SavedFilter(
            name=stored_name,
            description=description.strip(),
            owner=stored_owner,
            query=stored_query,
            structured_filter=stored_terms,
            sort=list(sort),
        )
    )


async def update_saved_filter(
    session: AsyncSession,
    saved: SavedFilter,
    *,
    initiator: Actor,
    name: str = UNSET,
    description: str = UNSET,
    query: str | None = UNSET,
    structured: Sequence[search_service.StructuredTerm] | None = UNSET,
    sort: Sequence[str] = UNSET,
) -> SavedFilter:
    """Меняет фильтр. Не переданное поле не трогается.

    Источник отбора заменяется целиком: передали строку — фильтр стал текстовым и
    структурная часть снята, передали условия — наоборот. Иначе в строке остались бы
    оба описания, а вопрос «какое из них главное» ответа не имеет.

    Владелец не меняется: имя уникально у владельца, и передача фильтра другому
    превратилась бы в тихий конфликт имён у него. Нужен другой владелец — заводится
    новый фильтр.
    """
    ensure_allowed(initiator, "saved_filter.update", target=saved)

    if is_set(name):
        stored_name = _validated_name(name)
        if stored_name != saved.name:
            existing = await SavedFilterRepository(session).get_by_name(saved.owner_id, stored_name)
            if existing is not None:
                raise SavedFilterNameTakenError(
                    details={"name": stored_name, "owner": saved.owner.key},
                )
        saved.name = stored_name
    if is_set(description):
        saved.description = description.strip()
    if is_set(sort):
        saved.sort = list(sort)

    if is_set(query) or is_set(structured):
        stored_query, stored_terms = await _validated_definition(
            session,
            query=query if is_set(query) else None,
            structured=structured if is_set(structured) else None,
            sort=saved.sort,
            initiator=initiator,
        )
        saved.query = stored_query
        saved.structured_filter = stored_terms
    elif is_set(sort):
        # Порядок — часть описания, и его тоже надо проверить: имя поля сортировки
        # может не разрешаться, а узнать об этом при запуске фильтра поздно.
        await _validated_definition(
            session,
            query=saved.query,
            structured=terms_of(saved) or None,
            sort=saved.sort,
            initiator=initiator,
        )

    await SavedFilterRepository(session).flush()
    return saved


async def delete_saved_filter(
    session: AsyncSession,
    saved: SavedFilter,
    *,
    initiator: Actor,
) -> None:
    """Удаляет фильтр насовсем: описание отбора истории не образует."""
    ensure_allowed(initiator, "saved_filter.delete", target=saved)
    await SavedFilterRepository(session).delete(saved)


# --- Внутреннее --------------------------------------------------------------------


def _validated_name(name: str) -> str:
    stored = name.strip()
    if not stored:
        raise InvalidSavedFilterError(details={"field": "name", "reason": "required"})
    if len(stored) > MAX_FILTER_NAME_LENGTH:
        raise InvalidSavedFilterError(
            details={
                "field": "name",
                "reason": "too_long",
                "max": MAX_FILTER_NAME_LENGTH,
                "got": len(stored),
            },
        )
    return stored


async def _validated_definition(
    session: AsyncSession,
    *,
    query: str | None,
    structured: Sequence[search_service.StructuredTerm] | None,
    sort: Sequence[str],
    initiator: Actor,
) -> tuple[str | None, dict[str, Any] | None]:
    """Проверяет описание и возвращает пару колонок: ровно одна из них заполнена."""
    has_query = bool(query and query.strip())
    has_terms = bool(structured)
    if has_query == has_terms:
        raise InvalidSavedFilterError(
            details={
                "reason": "single_source_required",
                "hint": "pass either a query string or a structured filter",
            },
        )
    if has_query and len(query or "") > MAX_QUERY_LENGTH:
        raise InvalidSavedFilterError(
            details={"field": "query", "reason": "too_long", "max": MAX_QUERY_LENGTH},
        )

    parsed = (
        parse_query(query or "")
        if has_query
        else search_service.filter_from_structured(structured or ())
    )
    if parsed.root is None:
        raise InvalidSavedFilterError(
            details={"reason": "no_conditions", "hint": "a saved filter must narrow something"},
        )
    if sort:
        parsed = SearchFilter(root=parsed.root, sort=parse_sort_terms(sort))
    # Разрешение против реестра и справочников: имена полей и значения проверяются
    # тем же кодом, что и при выполнении поиска. Второй проверки «попроще» здесь быть
    # не должно — она разошлась бы с настоящей.
    await search_service.resolve_filter(session, parsed, initiator=initiator)

    if has_query:
        return (query or "").strip(), None
    return None, _encode_terms(structured or ())


def _encode_terms(terms: Sequence[search_service.StructuredTerm]) -> dict[str, Any]:
    return {
        _TERMS_KEY: [
            {"name": term.name, "operator": term.operator.value, "values": list(term.values)}
            for term in terms
        ]
    }


def terms_of(saved: SavedFilter) -> list[search_service.StructuredTerm]:
    """Условия структурного фильтра из хранилища. Пустой список — фильтр текстовый.

    Публичная, потому что тот же список нужен схеме ответа: в колонке лежат ровно те
    условия, которые выполняются, и разбирать JSONB вторым способом в HTTP-слое
    значило бы завести второе толкование формата хранения.
    """
    payload = saved.structured_filter or {}
    return [
        search_service.StructuredTerm(
            name=item["name"],
            operator=Operator(item.get("operator", Operator.EQ.value)),
            values=item.get("values", []),
        )
        for item in payload.get(_TERMS_KEY, [])
    ]
