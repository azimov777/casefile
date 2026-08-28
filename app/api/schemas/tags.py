"""Схемы тегов: словарь заведённых меток и точечные операции над тегами задачи.

Справочника тегов в проекте нет — тег существует ровно до тех пор, пока есть задача с
ним (`app/services/tags.py`). Поэтому словарь отдаётся с числом задач: по нему видно,
какое из похожих написаний прижилось, а какое поставили однажды по ошибке.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.issues import MAX_TAG_LENGTH, MAX_TAGS, TagUsage

TagsField = Field(
    min_length=1,
    max_length=MAX_TAGS,
    examples=[["release", "backend"]],
    description=(
        f"Tags to apply, at most {MAX_TAG_LENGTH} characters each. Matching is "
        "case-insensitive: adding `Release` to an issue tagged `release` changes nothing"
    ),
)


class TagUsageRead(BaseModel):
    """Тег словаря и число задач, которыми он поставлен."""

    tag: str = Field(examples=["release"], description="The tag as it was first written")
    issues: int = Field(
        examples=[12],
        description="How many issues carry this tag, within the requested queue if given",
    )

    @classmethod
    def of(cls, usage: TagUsage) -> TagUsageRead:
        return cls(tag=usage.tag, issues=usage.issues)


class IssueTagsAdd(BaseModel):
    """Добавление тегов к задаче: уже поставленные не трогаются."""

    model_config = ConfigDict(extra="forbid")

    tags: list[str] = TagsField
    version: int | None = Field(
        default=None,
        ge=1,
        description="Version the client last saw; omit it to skip the check",
    )
