"""Оболочки ответов и формат ошибки — общие для всех эндпоинтов.

Соглашение проекта: внешняя структура ответа одинакова везде, меняется только содержимое
`data`. Клиент разбирает любой ответ одним и тем же кодом, не зная, какой эндпоинт его вернул.
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Тело ошибки. `code` — стабильный идентификатор, на него завязывается фронтенд."""

    code: str = Field(examples=["issue_not_found"])
    message: str = Field(examples=["Issue TRK-123 not found"])
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
    ) -> CollectionResponse[ItemT]:
        """Собирает страницу: `has_more` выводится из курсора, а не задаётся руками."""
        return cls(
            data=items, meta=PageMeta(next_cursor=next_cursor, has_more=next_cursor is not None)
        )
