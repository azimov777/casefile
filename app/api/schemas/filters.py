"""Схемы сохранённых фильтров.

Фильтр описывается **либо** строкой на языке запросов, **либо** списком условий —
ровно одним способом. Почему не обоими сразу: два описания одного отбора немедленно
порождают вопрос «какое из них главное», а расхождение между ними было бы молчаливым.

Условия отдаются и принимаются в каноническом виде (`SearchTermInput`), а не в виде
формы поиска (`IssueFilterInput`). Причина в обратимости: форма сводится к условиям
однозначно, а условия к форме — нет, и фильтр, сохранённый формой, нельзя было бы
показать обратно тем же способом. Удобная форма остаётся у самого поиска, где ничего
хранить не нужно.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import unset_field
from app.api.schemas.search import SearchTermInput, SortDescription
from app.db.models.saved_filter import SavedFilter
from app.domain.search import MAX_QUERY_LENGTH, MAX_SORT_TERMS
from app.services import saved_filters as saved_filters_service
from app.services.saved_filters import MAX_FILTER_NAME_LENGTH

NameField = Field(
    min_length=1,
    max_length=MAX_FILTER_NAME_LENGTH,
    examples=["Мои горящие"],
    description="Unique per owner",
)
QueryDescription = (
    "Query language string. Functions are evaluated when the filter runs, not when it "
    "is saved: `me()` means whoever runs it and `today()` means today"
)
QueryExample = "assignee: me() and deadline: <= today() and status_category: != done"
FilterDescription = "Canonical conditions joined by `and`; the stored form of a structured filter"


class SavedFilterRead(BaseModel):
    """Сохранённый фильтр в ответе."""

    id: uuid.UUID
    name: str = NameField
    description: str = Field(examples=[""], description="Empty string when there is none")
    owner: str = Field(examples=["alice"], description="Key of the actor who owns the filter")
    query: str | None = Field(default=None, description="Set when the filter is a query string")
    filter: list[SearchTermInput] | None = Field(
        default=None,
        description=f"{FilterDescription}. Set when the filter is structured",
    )
    sort: list[str] = Field(default_factory=list, description=SortDescription)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, saved: SavedFilter) -> SavedFilterRead:
        return cls(
            id=saved.id,
            name=saved.name,
            description=saved.description,
            owner=saved.owner.key,
            query=saved.query,
            filter=_terms_of(saved),
            sort=list(saved.sort),
            created_at=saved.created_at,
            updated_at=saved.updated_at,
        )


class SavedFilterCreate(BaseModel):
    """Создание фильтра. Ровно одно из `query` и `filter`."""

    model_config = ConfigDict(extra="forbid")

    name: str = NameField
    description: str = Field(default="", examples=[""])
    query: str | None = Field(
        default=None,
        max_length=MAX_QUERY_LENGTH,
        examples=[QueryExample],
        description=QueryDescription,
    )
    filter: list[SearchTermInput] | None = Field(default=None, description=FilterDescription)
    sort: list[str] = Field(
        default_factory=list,
        max_length=MAX_SORT_TERMS,
        examples=[["-deadline"]],
        description=SortDescription,
    )
    owner: str | None = Field(
        default=None,
        description="Owner actor key; defaults to the actor behind the token",
    )


class SavedFilterUpdate(BaseModel):
    """Частичное обновление. Источник отбора заменяется целиком, а не дополняется.

    Владельца здесь нет: имя уникально у владельца, и передача фильтра другому
    превратилась бы в тихий конфликт имён у него.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = unset_field(min_length=1, max_length=MAX_FILTER_NAME_LENGTH)
    description: str = unset_field(description="Pass an empty string to clear it")
    query: str = unset_field(
        max_length=MAX_QUERY_LENGTH,
        description=f"{QueryDescription}. Replaces the filter body",
    )
    filter: list[SearchTermInput] = unset_field(description=FilterDescription)
    sort: list[str] = unset_field(max_length=MAX_SORT_TERMS, description=SortDescription)


def _terms_of(saved: SavedFilter) -> list[SearchTermInput] | None:
    """Условия из хранилища в схему ответа.

    Список берётся у сценария, а не разбирается здесь: в колонке лежат ровно те
    условия, которые выполняются, и второе толкование формата хранения в HTTP-слое
    однажды показало бы клиенту не тот фильтр, который работает.
    """
    if saved.structured_filter is None:
        return None
    return [
        SearchTermInput(field=term.name, operator=term.operator, values=list(term.values))
        for term in saved_filters_service.terms_of(saved)
    ]
