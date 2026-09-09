"""Внешняя оболочка ответа одинакова у всех эндпоинтов: `data` и, для коллекций, `meta`.

Тесты на схемы, а не на маршруты: содержательных эндпоинтов ещё нет, но форма контракта
задаётся сейчас, и следующие задачи обязаны её соблюдать.
"""

from pydantic import BaseModel

from app.api.schemas.common import CollectionResponse, DataResponse


class Sample(BaseModel):
    """Модель на один тест: оболочка проверяется на форме, а не на домене."""

    key: str


def test_single_resource_is_wrapped_into_data() -> None:
    response = DataResponse[Sample](data=Sample(key="TRK-1"))

    assert response.model_dump() == {"data": {"key": "TRK-1"}}


def test_collection_puts_pagination_into_meta() -> None:
    response = CollectionResponse[Sample].of([Sample(key="TRK-1")], next_cursor="eyJpZCI6...")

    assert response.model_dump() == {
        "data": [{"key": "TRK-1"}],
        "meta": {"next_cursor": "eyJpZCI6...", "has_more": True, "total": None},
    }


def test_empty_collection_is_an_empty_list_not_an_empty_body() -> None:
    response = CollectionResponse[Sample].of([])

    assert response.model_dump() == {
        "data": [],
        "meta": {"next_cursor": None, "has_more": False, "total": None},
    }
