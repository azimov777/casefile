"""Оболочки ответов и формат ошибки — общие для всех эндпоинтов.

Соглашение проекта: внешняя структура ответа одинакова везде, меняется только содержимое
`data`. Клиент разбирает любой ответ одним и тем же кодом, не зная, какой эндпоинт его вернул.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.core.sentinels import UNSET, UnsetType, is_set, unset_field

# Сентинел и способ объявить поле с ним живут в `app/core/sentinels.py`, а не здесь:
# тот же признак нужен сценариям и схемам аргументов MCP, а `services` и `mcp` не имеют
# права зависеть от `api`. Реэкспорт оставлен, чтобы схемам хватало одного импорта.
__all__ = [
    "UNSET",
    "CollectionResponse",
    "DataResponse",
    "ErrorDetail",
    "ErrorResponse",
    "PageMeta",
    "UnsetType",
    "is_set",
    "unset_field",
]


class ErrorDetail(BaseModel):
    """Тело ошибки. `code` — стабильный идентификатор, на него завязывается фронтенд."""

    code: str = Field(examples=["task_not_found"])
    message: str = Field(examples=["Task not found"])
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Единый формат ошибки: всё содержательное лежит под ключом `error`."""

    error: ErrorDetail


class PageMeta(BaseModel):
    """Служебные поля коллекции. Всё, что не сам ресурс, живёт здесь, а не рядом с `data`."""

    next_cursor: str | None = Field(
        default=None,
        description="Cursor for the next page; null means there is nothing more to fetch",
    )
    has_more: bool = Field(
        default=False,
        description="Whether another page exists",
    )
    # Поле необязательное, и это решение, а не забывчивость: подсчёт — второй запрос по
    # тому же отбору, и платит за него только та коллекция, которую показывают
    # страницами (сегодня одна — список задач). `null` означает «не считали»; у
    # посчитанной пустой выдачи стоит `0`. Решение и его цена — задача TRK-41.
    total: int | None = Field(
        default=None,
        description=(
            "Total number of rows matching the filter, across all pages; null means this "
            "collection does not count them. Only `GET /api/v1/tasks` fills it in"
        ),
        examples=[98],
    )


class DataResponse[ItemT](BaseModel):
    """Одиночный ресурс: `{"data": {...}}`. Отдавать ресурс «голым» запрещено."""

    data: ItemT


class CollectionResponse[ItemT](BaseModel):
    """Коллекция с курсорной пагинацией: `{"data": [...], "meta": {...}}`.

    Пустая коллекция — это `"data": []` и `meta` с `has_more: false`, а не пустое тело.
    """

    data: list[ItemT]
    meta: PageMeta = Field(default_factory=PageMeta)

    @classmethod
    def of(
        cls,
        items: list[ItemT],
        *,
        next_cursor: str | None = None,
        total: int | None = None,
    ) -> CollectionResponse[ItemT]:
        """Собирает страницу: `has_more` выводится из курсора, а не задаётся руками.

        `total` приходит от того, кто его посчитал, и по умолчанию его нет: коллекция,
        не платившая за подсчёт, обязана отдать `null`, а не `0` — «ноль» означал бы,
        что по отбору не нашлось ничего.
        """
        return cls(
            data=items,
            meta=PageMeta(
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
                total=total,
            ),
        )
