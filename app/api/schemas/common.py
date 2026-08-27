"""Оболочки ответов и формат ошибки — общие для всех эндпоинтов.

Соглашение проекта: внешняя структура ответа одинакова везде, меняется только содержимое
`data`. Клиент разбирает любой ответ одним и тем же кодом, не зная, какой эндпоинт его вернул.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.core.sentinels import UNSET, UnsetType, is_set

# Сентинел живёт в `app/core/sentinels.py`, а не здесь: тот же признак нужен сценариям,
# а `services` не имеет права зависеть от `api`. Реэкспорт оставлен, чтобы схемам
# по-прежнему хватало одного импорта.
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


def unset_field(**kwargs: Any) -> Any:
    """Поле схемы `PATCH`, которое можно не передавать.

    Поле объявляется своим настоящим типом (`str`, а не `str | None`), а значением по
    умолчанию получает `UNSET`. Следствия — все три нужные сразу:

    - `null` не проходит валидацию, потому что `None` не входит в тип поля;
    - в OpenAPI поле не помечено nullable, и сгенерированный клиент не даст фронтенду
      отправить `null` там, где он запрещён;
    - `model_dump(exclude_unset=True)` возвращает ровно переданные поля.

    Поле, у которого `null` осмысленно (очистить исполнителя, снять дедлайн),
    объявляется как `T | None` с тем же `unset_field()`: тогда различимы все три
    состояния — не передано, передано значение, передано `null`.

    `default_factory`, а не `default`: значение по умолчанию Pydantic пытается положить
    в JSON-схему, сентинел не сериализуется, и генерация схемы сыпет предупреждениями.
    Фабрику Pydantic при построении схемы не вызывает, поэтому предупреждения нет.
    """
    return Field(default_factory=lambda: UNSET, **kwargs)


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
