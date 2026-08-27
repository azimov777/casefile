"""Оболочки ответов и формат ошибки — общие для всех эндпоинтов.

Соглашение проекта: внешняя структура ответа одинакова везде, меняется только содержимое
`data`. Клиент разбирает любой ответ одним и тем же кодом, не зная, какой эндпоинт его вернул.
"""

from typing import Any, Self

from pydantic import BaseModel, Field


class UnsetType:
    """Признак «поле не передано» для схем частичного обновления.

    Соглашения требуют различать «поле не передано» и «поле передано как null» на
    уровне типов, а не договорённостью. Отсюда сентинел: поле объявляется своим
    настоящим типом (`str`, а не `str | None`), а значением по умолчанию получает
    `UNSET`. Следствия — все три нужные сразу:

    - `null` не проходит валидацию, потому что `None` не входит в тип поля;
    - в OpenAPI поле не помечено nullable, и сгенерированный клиент не даст
      фронтенду отправить `null` там, где он запрещён;
    - `model_dump(exclude_unset=True)` возвращает ровно переданные поля.

    Поле, у которого `null` осмысленно (очистить исполнителя, снять дедлайн),
    объявляется как `T | None` с тем же `UNSET` по умолчанию: тогда различимы все
    три состояния — не передано, передано значение, передано `null`.
    """

    __slots__ = ()
    _instance: UnsetType | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


#: Значение по умолчанию для необязательных полей `PATCH`. Тип `Any` — намеренно:
#: сентинел не должен попадать в объявленный тип поля, иначе он утечёт в OpenAPI.
UNSET: Any = UnsetType()


def unset_field(**kwargs: Any) -> Any:
    """Поле схемы `PATCH`, которое можно не передавать.

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
