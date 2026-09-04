"""Схемы записей дела.

## Почему запись — размеченное объединение, а не объект со свободной нагрузкой

Форма `payload` зависит от типа записи (`CONCEPT.md`, 3.4). Описать её словарём
значило бы отдать фронтенду `Record<string, unknown>` и обесценить генерацию клиента
ровно там, где данных больше всего. Поэтому запись объявлена объединением по `type`:
у каждого варианта своя модель нагрузки, а `type` — разметка, по которой и Pydantic, и
сгенерированный TypeScript сужают тип.

Варианты сгруппированы по форме нагрузки, а не по типам: у `decision`, `attempt`,
`finding`, `artifact`, `note` и служебной `created` нагрузки нет, и шесть одинаковых
моделей отличались бы только строкой разметки.

## Что принимается в запросе

Подшить можно только запись агента: служебные типы (`status_changed`, `link_added`,
...) в объединение запроса не входят — их подшивает сценарий, выводя тип из действия.
Заголовок принимается лишь там, где его нечем вывести: у `summary` он равен первой
строке `next_step`, у `answer` и `verdict` собирается из нагрузки.

Границы длин повторяют домен (`app/domain/case.py`): здесь они ради документации и
раннего отсева, настоящую проверку делает домен — одинаково для REST и MCP.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.api.schemas.authors import AuthorRead
from app.db.models.entry import Entry
from app.domain.case import (
    MAX_ADDRESSEES,
    MAX_ENTRY_BODY_LENGTH,
    MAX_ENTRY_TITLE_LENGTH,
    MAX_REFS,
    MAX_SUMMARY_PART_LENGTH,
    EntryType,
    VerdictOutcome,
)
from app.domain.tasks import FIRST_CHECK_NUMBER

_REFS_DESCRIPTION = (
    "References to entries `KEY-N#M`, tasks `KEY-N` and addresses. Entry and task "
    "references must exist; addresses are not checked"
)
_TITLE_DESCRIPTION = "One line; this is what the case index shows"
_BODY_DESCRIPTION = "Markdown; empty for service entries, whose content is the payload"
_NO_DESCRIPTION = "Number inside the task, from 1; `TRK-42#12`"


class EntryHeadingRead(BaseModel):
    """Строка описи дела: то, что видно о записи, не читая её тела."""

    model_config = ConfigDict(from_attributes=True)

    no: int = Field(examples=[12], description=_NO_DESCRIPTION)
    type: EntryType = Field(examples=[EntryType.STATUS_CHANGED])
    author: AuthorRead
    created_at: datetime
    title: str = Field(examples=["Status changed: backlog -> open"])


# --- Нагрузка по типам ----------------------------------------------------------------


class EmptyPayload(BaseModel):
    """Нагрузки нет: всё содержание записи в её заголовке, теле и ссылках."""

    model_config = ConfigDict(extra="forbid")


class SummaryPayload(BaseModel):
    """Справка при передаче. Четыре части, все непустые."""

    model_config = ConfigDict(extra="forbid")

    done: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Разобрался, где сгорает номер"],
        description="What has been done",
    )
    remaining: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Перенести выдачу номера после валидации"],
        description="What is left",
    )
    blockers: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Нет"],
        description="What is in the way; write `нет` rather than leaving it empty",
    )
    next_step: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Перенести вызов next_task_number в конец create_task"],
        description="The next step; its first line becomes the entry title",
    )


class QuestionPayload(BaseModel):
    """Вопрос участникам реестра."""

    model_config = ConfigDict(extra="forbid")

    addressees: list[str] = Field(
        min_length=1,
        max_length=MAX_ADDRESSEES,
        examples=[["owner"]],
        description=(
            "Participant names from the registry, at least one. Temporary agents "
            "cannot be addressed: they have no registry row"
        ),
    )
    blocking: bool = Field(
        examples=[True],
        description="Whether work can continue without an answer. Required, no default",
    )


class AnswerPayload(BaseModel):
    """Ответ на вопрос той же задачи."""

    model_config = ConfigDict(extra="forbid")

    question_no: int = Field(
        ge=1,
        examples=[7],
        description="Number of a `question` entry of the same task",
    )


class VerdictPayload(BaseModel):
    """Исход одной обзорной проверки."""

    model_config = ConfigDict(extra="forbid")

    check_no: int = Field(
        ge=FIRST_CHECK_NUMBER,
        examples=[3],
        description="Position in the task `checks` list, numbered from 1",
    )
    outcome: VerdictOutcome = Field(examples=[VerdictOutcome.PASSED])


class StatusChangedPayload(BaseModel):
    """Переход статуса. `from` — ключевое слово Python, поэтому поле объявлено псевдонимом."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_status: str = Field(alias="from", examples=["backlog"])
    to: str = Field(examples=["open"])
    reason: str | None = Field(
        default=None,
        examples=["Нужны уточнения по разделу context"],
        description="Why the task moved; required for a step back and for `cancelled`",
    )


class SectionChangedPayload(BaseModel):
    """Правка названия, описания или раздела в `backlog`: «было» и «стало» целиком."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(examples=["goal"])
    before: str | list[str] | None = Field(
        default=None, description="Previous value; a list for `checks`"
    )
    after: str | list[str] | None = Field(
        default=None, description="New value; a list for `checks`"
    )


class AssigneeChangedPayload(BaseModel):
    """Смена исполнителя. `null` с любой стороны означает «исполнителя не было»."""

    model_config = ConfigDict(extra="forbid")

    before: str | None = Field(default=None, examples=[None])
    after: str | None = Field(default=None, examples=["release_bot"])


class LinkPayload(BaseModel):
    """Связь между задачами. Подшивается в дело обеих сторон под своим именем.

    Модель объявлена здесь, а не в задаче 24 вместе со связями: объединение по `type`
    обязано покрывать **все** типы записей, иначе первая же запись о связи развалила бы
    чтение дела целиком.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(examples=["blocked_by"])
    other: str = Field(examples=["TRK-7"], description="Key of the task on the other side")


# --- Запись в ответе ------------------------------------------------------------------


class _EntryReadBase(BaseModel):
    """Общие поля любой записи. Отдельной схемой в OpenAPI не появляется."""

    id: uuid.UUID
    seq: int = Field(examples=[1024], description="Tracker-wide monotonic number; journal cursor")
    no: int = Field(examples=[12], description=_NO_DESCRIPTION)
    task_key: str = Field(examples=["TRK-42"])
    author: AuthorRead
    title: str = Field(examples=["Status changed: backlog -> open"], description=_TITLE_DESCRIPTION)
    body: str = Field(examples=[""], description=_BODY_DESCRIPTION)
    refs: list[str] = Field(
        default_factory=list, examples=[["TRK-42#3", "TRK-7"]], description=_REFS_DESCRIPTION
    )
    created_at: datetime


class PlainEntryRead(_EntryReadBase):
    """Запись без нагрузки: решение, попытка, находка, артефакт, заметка, заведение задачи."""

    type: Literal[
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.NOTE,
        EntryType.CREATED,
    ]
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


class SummaryEntryRead(_EntryReadBase):
    """Сводка: точка входа преемника. Последняя главнее предыдущих."""

    type: Literal[EntryType.SUMMARY]
    payload: SummaryPayload


class QuestionEntryRead(_EntryReadBase):
    """Вопрос участникам. Открыт, пока в деле нет `answer` с его номером."""

    type: Literal[EntryType.QUESTION]
    payload: QuestionPayload


class AnswerEntryRead(_EntryReadBase):
    """Ответ на вопрос. Ответить может кто угодно; первый ответ закрывает вопрос."""

    type: Literal[EntryType.ANSWER]
    payload: AnswerPayload


class VerdictEntryRead(_EntryReadBase):
    """Вердикт по обзорной проверке. Тело записи — доказательство."""

    type: Literal[EntryType.VERDICT]
    payload: VerdictPayload


class StatusChangedEntryRead(_EntryReadBase):
    """Служебная запись о переходе статуса."""

    type: Literal[EntryType.STATUS_CHANGED]
    payload: StatusChangedPayload


class SectionChangedEntryRead(_EntryReadBase):
    """Служебная запись о правке названия, описания или раздела."""

    type: Literal[EntryType.SECTION_CHANGED]
    payload: SectionChangedPayload


class AssigneeChangedEntryRead(_EntryReadBase):
    """Служебная запись о смене исполнителя."""

    type: Literal[EntryType.ASSIGNEE_CHANGED]
    payload: AssigneeChangedPayload


class LinkEntryRead(_EntryReadBase):
    """Служебная запись о появлении или снятии связи."""

    type: Literal[EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
    payload: LinkPayload


type EntryRead = Annotated[
    PlainEntryRead
    | SummaryEntryRead
    | QuestionEntryRead
    | AnswerEntryRead
    | VerdictEntryRead
    | StatusChangedEntryRead
    | SectionChangedEntryRead
    | AssigneeChangedEntryRead
    | LinkEntryRead,
    Field(discriminator="type"),
]
"""Запись дела целиком: размеченное по `type` объединение всех форм нагрузки."""


def entry_read_schema() -> dict[str, Any]:
    """Схема записи для ответа, который FastAPI описать за нас не может.

    Нужна ровно одному месту — кадру потока `GET /api/v1/journal/stream`. Тип
    содержимого там `text/event-stream`, поэтому ответ объявлен вручную, а модели в
    таком объявлении FastAPI не разбирает: `$ref` пришлось бы писать строкой и он
    разошёлся бы с объединением при первом новом типе записи.

    Схема поэтому собирается из самого объединения, а определения вариантов
    (`$defs`) отбрасываются: те же модели уже лежат в компонентах схемы — их приносит
    туда лента `GET /api/v1/journal`, у которой ответ обычный. Кадр и страница ленты
    от этого описаны буквально одним типом, а не двумя похожими.
    """
    schema = TypeAdapter(EntryRead).json_schema(ref_template="#/components/schemas/{model}")
    schema.pop("$defs", None)
    return schema


_READ_MODELS: dict[EntryType, type[_EntryReadBase]] = {
    EntryType.SUMMARY: SummaryEntryRead,
    EntryType.QUESTION: QuestionEntryRead,
    EntryType.ANSWER: AnswerEntryRead,
    EntryType.VERDICT: VerdictEntryRead,
    EntryType.STATUS_CHANGED: StatusChangedEntryRead,
    EntryType.SECTION_CHANGED: SectionChangedEntryRead,
    EntryType.ASSIGNEE_CHANGED: AssigneeChangedEntryRead,
    EntryType.LINK_ADDED: LinkEntryRead,
    EntryType.LINK_REMOVED: LinkEntryRead,
}


def entry_read(entry: Entry, *, task_key: str) -> EntryRead:
    """Собирает вариант ответа по типу записи.

    Ключ задачи приходит от вызывающего: у записи связи с задачей нет, только `task_id`.

    Тип, которого нет в таблице, — это запись без формы нагрузки, то есть дефект
    объединения, а не рабочее состояние: `KeyError` здесь честнее молчаливого
    возврата записи со свободным `payload`, который фронт не разберёт.
    """
    return _READ_MODELS.get(entry.type, PlainEntryRead)(
        id=entry.id,
        seq=entry.seq,
        no=entry.no,
        task_key=task_key,
        type=entry.type,
        author=AuthorRead.model_validate(entry.author),
        title=entry.title,
        body=entry.body,
        payload=entry.payload,
        refs=list(entry.refs),
        created_at=entry.created_at,
    )


# --- Запись в запросе -----------------------------------------------------------------


class _EntryCreateBase(BaseModel):
    """Общее у всех подшиваемых записей: тело и ссылки."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(
        default="",
        max_length=MAX_ENTRY_BODY_LENGTH,
        description="Markdown body of the entry",
    )
    refs: list[str] = Field(
        default_factory=list,
        max_length=MAX_REFS,
        examples=[[]],
        description=_REFS_DESCRIPTION,
    )


class _TitledEntryCreate(_EntryCreateBase):
    """Записи, у которых заголовок пишет автор: вывести его не из чего."""

    title: str = Field(
        min_length=1,
        max_length=MAX_ENTRY_TITLE_LENGTH,
        examples=["Номер задачи выдаётся до валидации"],
        description=_TITLE_DESCRIPTION,
    )


class PlainEntryCreate(_TitledEntryCreate):
    """Решение, попытка, находка, артефакт, заметка. Нагрузки нет."""

    type: Literal[
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.NOTE,
    ]


class SummaryEntryCreate(_EntryCreateBase):
    """Сводка. Заголовок не принимается: он равен первой строке `next_step`."""

    type: Literal[EntryType.SUMMARY]
    payload: SummaryPayload


class QuestionEntryCreate(_TitledEntryCreate):
    """Вопрос участникам реестра."""

    type: Literal[EntryType.QUESTION]
    payload: QuestionPayload


class AnswerEntryCreate(_EntryCreateBase):
    """Ответ. Заголовок не принимается: он собирается из ссылки на вопрос."""

    type: Literal[EntryType.ANSWER]
    payload: AnswerPayload


class VerdictEntryCreate(_EntryCreateBase):
    """Вердикт. Заголовок не принимается; тело записи — доказательство исхода."""

    type: Literal[EntryType.VERDICT]
    payload: VerdictPayload


type EntryCreate = Annotated[
    PlainEntryCreate
    | SummaryEntryCreate
    | QuestionEntryCreate
    | AnswerEntryCreate
    | VerdictEntryCreate,
    Field(discriminator="type"),
]
"""Подшиваемая запись: те же типы, что доступны агенту, размеченные по `type`."""
