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

Тем же способом и по той же причине размечены **факты строки описи** (`EntryFactsRead`):
форма зависит от типа записи, и один объект со всеми полями всех типов описывал бы не
данные, а их объединение. Разница в том, где стоит разметка: у записи её несёт сама
запись, у фактов — они сами, потому что `facts` путешествует отдельным значением.

## Что принимается в запросе

Подшить можно только запись агента: служебные типы (`status_changed`, `link_added`,
...) в объединение запроса не входят — их подшивает сценарий, выводя тип из действия.
Заголовок принимается лишь там, где его нечем вывести: у `summary` он равен первой
строке `done`, у `answer` и `verdict` собирается из нагрузки.

Границы длин повторяют домен (`app/domain/case.py`): здесь они ради документации и
раннего отсева, настоящую проверку делает домен — одинаково для REST и MCP.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
)

from app.api.schemas.authors import AuthorRead
from app.db.models.entry import Entry
from app.domain.case import (
    CLOSING_SUMMARY_PART,
    MAX_ADDRESSEES,
    MAX_ENTRY_BODY_LENGTH,
    MAX_ENTRY_TITLE_LENGTH,
    MAX_REFS,
    MAX_SUMMARY_PART_LENGTH,
    OUTCOME_WITH_CONTINUATION,
    EntryType,
    RemarkOutcome,
    VerdictOutcome,
)
from app.domain.links import LinkKind
from app.domain.tasks import FIRST_CHECK_NUMBER, TaskField, TaskStatus

_REFS_DESCRIPTION = (
    "References to task entries `KEY-N#M`, project entries `KEY#M`, tasks `KEY-N` and "
    "addresses. Entry and task references must exist; addresses are not checked"
)
_TITLE_DESCRIPTION = "One line; this is what the case index shows"
_BODY_DESCRIPTION = "Markdown; empty for service entries, whose content is the payload"
_NO_DESCRIPTION = (
    "Number inside the owning task or project, from 1; `TRK-42#12` for a task entry, "
    "`TRK#7` for a project entry"
)
_ACTION_ID_DESCRIPTION = (
    "Marks the single call (`update_task`, `close_task`, `link`, ...) that filed this "
    "entry: entries of one call share the same value, entries of another call never "
    "do. A client groups entries by it instead of guessing from a matching "
    "`created_at`. `null` on entries filed before this field existed"
)


# --- Факты строки описи ---------------------------------------------------------------


class _EntryFactsBase(BaseModel):
    """Общее у всех форм фактов: разбор из объекта домена. В OpenAPI не появляется."""

    model_config = ConfigDict(from_attributes=True)


class NoFactsRead(_EntryFactsBase):
    """Фактов нет: заголовок записи пишет её автор, и он осмыслен сам по себе."""

    type: Literal[
        EntryType.SUMMARY,
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.REMARK,
        EntryType.NOTE,
        EntryType.CREATED,
        EntryType.ARCHIVED,
        EntryType.RESTORED,
    ]


class StatusChangedFactsRead(_EntryFactsBase):
    """Переход статуса: оба конца и был ли назван повод."""

    type: Literal[EntryType.STATUS_CHANGED]
    from_status: TaskStatus | None = Field(default=None, description="Status before the move")
    to_status: TaskStatus | None = Field(default=None, description="Status after the move")
    has_reason: bool | None = Field(
        default=None,
        description=(
            "Whether a reason was given. The reason itself is free text and stays in the entry body"
        ),
    )


class SectionChangedFactsRead(_EntryFactsBase):
    """Правка задания: какой раздел. Значения не здесь — раздел бывает длиннее задачи."""

    type: Literal[EntryType.SECTION_CHANGED]
    field: TaskField | None = Field(default=None, description="Which section was edited")
    check_no: int | None = Field(
        default=None,
        examples=[3],
        description=(
            "Which check was reworded, for a point edit of `checks`. Absent when the "
            "whole list was replaced"
        ),
    )


class FieldChangedFactsRead(_EntryFactsBase):
    """Правка обвязки: какое поле. Значения не здесь, они в самой записи."""

    type: Literal[EntryType.FIELD_CHANGED]
    field: TaskField | None = Field(default=None, description="Which field was edited")


class AssigneeChangedFactsRead(_EntryFactsBase):
    """Смена исполнителя: имена участников коротки и видны прямо в описи."""

    type: Literal[EntryType.ASSIGNEE_CHANGED]
    assignee_from: str | None = Field(
        default=None, description="Assignee before, null if there was none"
    )
    assignee_to: str | None = Field(default=None, description="Assignee after, null if unassigned")


class LinkFactsRead(_EntryFactsBase):
    """Связь появилась или снята: её вид и вторая сторона."""

    type: Literal[EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
    link_kind: LinkKind | None = Field(default=None, description="Kind of the link")
    other_key: str | None = Field(
        default=None, examples=["TRK-7"], description="The task on the other side"
    )


class QuestionFactsRead(_EntryFactsBase):
    """Вопрос: кому адресован и держит ли работу."""

    type: Literal[EntryType.QUESTION]
    addressees: list[str] | None = Field(
        default=None, description=f"Who is asked, at most {MAX_ADDRESSEES} names"
    )
    blocking: bool | None = Field(default=None, description="Whether the question holds the work")


class AnswerFactsRead(_EntryFactsBase):
    """Ответ: на какой вопрос той же задачи."""

    type: Literal[EntryType.ANSWER]
    question_no: int | None = Field(
        default=None, examples=[7], description="Number of the question answered"
    )


class VerdictFactsRead(_EntryFactsBase):
    """Вердикт: какая обзорная проверка, чем кончилась и не переписали ли её после."""

    type: Literal[EntryType.VERDICT]
    check_no: int | None = Field(
        default=None, examples=[3], description="Number of the review check"
    )
    outcome: VerdictOutcome | None = Field(default=None, description="How the check ended")
    outdated: bool | None = Field(
        default=None,
        examples=[False],
        description=(
            "Whether the check was reworded after this verdict was filed. A verdict "
            "points at a check by **number**, not by text, so an outdated one reads as "
            "«check 3 passed» while what passed was its previous wording. The record "
            "itself is never touched: this is computed when the case is read"
        ),
    )


class ResolutionFactsRead(_EntryFactsBase):
    """Резолюция: какое замечание разобрано, чем и куда ушла работа."""

    type: Literal[EntryType.RESOLUTION]
    remark_no: int | None = Field(default=None, examples=[7], description="The remark it resolves")
    outcome: RemarkOutcome | None = Field(default=None, description="How the remark was resolved")
    continuation_key: str | None = Field(
        default=None,
        examples=[None],
        description=("Key of the task the work moved to; set only when the outcome is `accepted`"),
    )


class AttributeFactsRead(_EntryFactsBase):
    """Атрибут проекта заведён, изменён или снят: его имя. Значения — в самой записи."""

    type: Literal[
        EntryType.ATTRIBUTE_CREATED, EntryType.ATTRIBUTE_CHANGED, EntryType.ATTRIBUTE_REMOVED
    ]
    name: str | None = Field(default=None, examples=["repo"], description="Attribute name")


# Состав полей каждой формы объявлен схемой, а не угадывается по тому, какие ключи
# пришли непустыми. Разметка повторяет `type` строки описи, и это осознанная плата за
# то, чтобы `facts` читался сам по себе: клиент принимает его отдельным значением — и из
# описи, и собранным из нагрузки записи ленты. Плата — от 17 до 28 байт на запись;
# прежняя форма, один объект со всеми полями всех типов, стоила 339 байт на строку
# вместо ста (`docs/notes/api.md`).
type EntryFactsRead = Annotated[
    NoFactsRead
    | StatusChangedFactsRead
    | SectionChangedFactsRead
    | FieldChangedFactsRead
    | AssigneeChangedFactsRead
    | LinkFactsRead
    | QuestionFactsRead
    | AnswerFactsRead
    | VerdictFactsRead
    | ResolutionFactsRead
    | AttributeFactsRead,
    Field(discriminator="type"),
]
"""Факты записи: размеченное по `type` объединение всех форм."""


class EntryHeadingRead(BaseModel):
    """Строка описи дела: то, что видно о записи, не читая её тела."""

    model_config = ConfigDict(from_attributes=True)

    no: int = Field(examples=[12], description=_NO_DESCRIPTION)
    type: EntryType = Field(examples=[EntryType.STATUS_CHANGED])
    author: AuthorRead
    created_at: datetime
    title: str = Field(examples=["Status changed: backlog -> open"])
    action_id: uuid.UUID | None = Field(
        default=None, examples=[None], description=_ACTION_ID_DESCRIPTION
    )
    facts: EntryFactsRead = Field(
        description=(
            "Length-bounded facts of the entry: enough to name it in any language "
            "without reading the English title the tracker builds. Which fields there "
            "are follows from `type`; entries whose title is written by their author "
            "have none"
        )
    )


# --- Нагрузка по типам ----------------------------------------------------------------


class EmptyPayload(BaseModel):
    """Нагрузки нет: всё содержание записи в её заголовке, теле и ссылках."""

    model_config = ConfigDict(extra="forbid")


class SummaryPartsPayload(BaseModel):
    """Четыре части сводки, все непустые: то, что подшивают посреди работы.

    Это же тело у `POST /tasks/{key}/entries` с типом `summary`, и пятой части здесь
    нет **намеренно**: закрывающая сводка едет не сюда, а в `POST /tasks/{key}/close`.
    Присланный `unmeasured` отвергнет схема, не доводя до домена.
    """

    model_config = ConfigDict(extra="forbid")

    done: str = Field(
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Разобрался, где сгорает номер"],
        description=(
            "What has been done. Its first line becomes the entry title, so make it one "
            "phrase naming what happened; an over-long line is cut at a word boundary"
        ),
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
        description="The next step: one concrete action for whoever picks the case up",
    )


class SummaryPayload(SummaryPartsPayload):
    """Сводка, как её **читают**: четыре части и, у закрывающей, пятая.

    Терпимость к отсутствию `unmeasured` — свойство чтения, а не подшивки: читаются и
    промежуточные сводки, у которых части не бывает, и все дела, закрытые до её
    появления. Отдельной моделью от `SummaryPartsPayload` она стоит именно поэтому:
    пока чтение и создание делили одну модель, необязательное поле уезжало в
    `model_dump()` маршрута создания значением `null` и роняло **всякую** обычную
    сводку — домен честно отвергал часть, которой в промежуточной сводке не место
    (TRK-78). Одна модель на две роли расходится молча; две расходиться не умеют.
    """

    unmeasured: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SUMMARY_PART_LENGTH,
        examples=["Прод-команда экрана не мерилась ни одной проверкой: гонял только дев-путь"],
        description=(
            "Which part of the goal no review check measured, and which risk the author "
            "considers theoretical. Closing summaries only: the key is absent on "
            "summaries filed mid-work and on those filed before this part existed"
        ),
    )

    @model_serializer(mode="wrap")
    def _without_the_absent_part(self, serialize: SerializerFunctionWrapHandler):
        """Часть, которой в записи нет, не показывается ключом со значением `null`.

        Запись дела отдаётся такой, какой её подшили. `null` читался бы как «часть есть,
        и она пуста», а пустых частей у сводки не бывает — их отвергает домен. Без этого
        REST дописывал бы ключ каждой промежуточной сводке и каждому делу, закрытому до
        появления части, и расходился бы с MCP, который отдаёт нагрузку как есть, — а
        совпадение двух дверей проверяется набором.

        **Возвращаемый тип не аннотирован намеренно.** Pydantic строит схему
        сериализации по аннотации возврата, и `dict[str, Any]` стирает её до
        `{"type": "object", "additionalProperties": true}`: в `openapi.json` пропадают
        все четыре части, а сгенерированный клиент получает `unknown` вместо полей —
        ровно то, ради чего нагрузка вообще описана моделью (шапка модуля). Без
        аннотации схема остаётся полной, а ключ всё так же не попадает в вывод.
        """
        data = serialize(self)
        if data.get(CLOSING_SUMMARY_PART) is None:
            data.pop(CLOSING_SUMMARY_PART, None)
        return data


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


class ResolutionPayload(BaseModel):
    """Нагрузка резолюции: какое замечание разобрано, чем и куда ушла работа."""

    model_config = ConfigDict(extra="forbid")

    remark_no: int = Field(
        ge=1,
        examples=[7],
        description="Number of the `remark` entry in the same task",
    )
    outcome: RemarkOutcome = Field(
        examples=[RemarkOutcome.ACCEPTED],
        description=(
            "How the remark was resolved: fixed right away, accepted into a separate "
            "task, needs more detail, or declined"
        ),
    )
    task: str | None = Field(
        default=None,
        examples=["TRK-43"],
        description=(
            "Key of the continuation task; required with `"
            + OUTCOME_WITH_CONTINUATION.value
            + "` and not accepted with any other outcome"
        ),
    )


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
    """Правка названия, описания или раздела в `backlog`: «было» и «стало» целиком.

    У точечной правки проверки «целиком» — это тексты самой проверки, а не всего
    списка, и её номер стоит в `check_no`.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(examples=["goal"])
    check_no: int | None = Field(
        default=None,
        examples=[None],
        description=(
            "Which check was reworded, for a point edit of `checks`. Absent when the "
            "whole list was replaced: then the set could have changed and the numbers "
            "could have shifted"
        ),
    )
    before: str | list[str] | None = Field(
        default=None, description="Previous value; a list for `checks`"
    )
    after: str | list[str] | None = Field(
        default=None, description="New value; a list for `checks`"
    )


class FieldChangedPayload(BaseModel):
    """Правка обвязки задачи: «было» и «стало» целиком.

    Отдельно от `SectionChangedPayload`, хотя поля похожи: там правка задания и только
    в `backlog`, здесь — то, что меняется в любом незакрытом статусе. Одна модель на
    оба случая означала бы «section» у приоритета.

    Значения — строки, а не «строка либо список»: список остался здесь от снятых меток
    (TRK-18), ни одно сегодняшнее поле обвязки списком не является, и записей со списком
    в базе нет ни одной. Пока объединение было плоским, оно только расширяло тип «на
    всякий случай»; появится поле-список — у него будет своя форма, а не общая на всех.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(examples=["priority"])
    before: str | None = Field(default=None, description="Previous value")
    after: str | None = Field(default=None, description="New value")


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


class AttributeCreatedPayload(BaseModel):
    """Атрибут проекта заведён: имя, значение и причина, если её назвали."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(examples=["repo"], description="Attribute name as stored")
    after: str = Field(examples=["https://github.com/azimov777/casefile"], description="Value set")
    reason: str | None = Field(
        default=None,
        examples=[None],
        description="Why the attribute was created; `null` when no reason was given",
    )


class AttributeChangedPayload(BaseModel):
    """Значение атрибута изменено: «было» и «стало» целиком и причина."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(examples=["repo"], description="Attribute name as stored")
    before: str = Field(description="Previous value")
    after: str = Field(description="New value")
    reason: str = Field(
        examples=["Репозиторий переехал в организацию"], description="Why the value changed"
    )


class AttributeRemovedPayload(BaseModel):
    """Атрибут снят: последнее значение и причина."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(examples=["repo"], description="Attribute name as stored")
    before: str = Field(description="Value at the moment of removal")
    reason: str = Field(
        examples=["Проект больше не публикуется в реестре"],
        description="Why the attribute was removed",
    )


class ProjectArchivePayload(BaseModel):
    """Проект архивирован или восстановлен: причина действия."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        examples=["Репозиторий заброшен, работа перенесена в CORE"],
        description="Why the project was archived or restored",
    )


# --- Запись в ответе ------------------------------------------------------------------


class _EntryReadBase(BaseModel):
    """Общие поля любой записи. Отдельной схемой в OpenAPI не появляется."""

    id: uuid.UUID
    seq: int = Field(examples=[1024], description="Tracker-wide monotonic number; journal cursor")
    no: int = Field(examples=[12], description=_NO_DESCRIPTION)
    task_key: str = Field(examples=["TRK-42"])
    # Поле есть у каждого варианта, чтобы форма записи была одна — в REST и в MCP
    # (`EntryView`), — но у типов, которых в деле проекта не бывает, оно всегда `null`.
    project_key: None = Field(
        examples=[None],
        description="Always `null`: entries of this type belong to a task, never to a project",
    )
    author: AuthorRead
    title: str = Field(examples=["Status changed: backlog -> open"], description=_TITLE_DESCRIPTION)
    body: str = Field(examples=[""], description=_BODY_DESCRIPTION)
    refs: list[str] = Field(
        default_factory=list, examples=[["TRK-42#3", "TRK-7"]], description=_REFS_DESCRIPTION
    )
    created_at: datetime
    action_id: uuid.UUID | None = Field(
        default=None, examples=[None], description=_ACTION_ID_DESCRIPTION
    )


class _ProjectOwnableEntryRead(_EntryReadBase):
    """Общие поля записи, которая бывает и в деле задачи, и в деле проекта.

    Владелец записи — задача или проект, и непуст ровно один ключ, как колонки владельца
    в базе (`ck_entries_one_owner`). Оба поля обязательны в схеме, а не пропускаются при
    `null`: форма записи одна в любом ответе (`docs/notes/api.md`). Сужение только у этих
    вариантов: типы, которых в деле проекта не бывает (сводка, вопрос, вердикт, переход и
    прочие), всегда принадлежат задаче — их `task_key` остаётся строкой, а `project_key`
    всегда `null`, и клиенту не нужно проверять на `null` ключ, который `null` быть не может.
    """

    task_key: str | None = Field(  # type: ignore[assignment]
        examples=["TRK-42"],
        description="Key of the owning task; `null` for an entry of a project's case",
    )
    project_key: str | None = Field(  # type: ignore[assignment]
        examples=[None],
        description=(
            "Key of the owning project for an entry of a project's case (`TRK#7`); "
            "`null` for a task entry, whose project is part of `task_key`"
        ),
    )


class _ProjectEntryRead(_EntryReadBase):
    """Общие поля записи, которая бывает только в деле проекта: об атрибутах.

    Сужение в обратную сторону от задачных типов: `task_key` всегда `null`, `project_key`
    всегда строка — атрибутов у задач нет (`CONCEPT.md`, 3.2).
    """

    task_key: None = Field(  # type: ignore[assignment]
        examples=[None],
        description="Always `null`: entries of this type belong to a project, never to a task",
    )
    project_key: str = Field(  # type: ignore[assignment]
        examples=["TRK"], description="Key of the owning project; the entry address is `TRK#7`"
    )


class PlainEntryRead(_ProjectOwnableEntryRead):
    """Запись без нагрузки: решение, попытка, находка, артефакт, заметка, заведение задачи
    или проекта."""

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


class AnsweredQuestionRead(QuestionEntryRead):
    """Вопрос в выдаче поперёк задач (`GET /api/v1/questions`) вместе с ответами.

    Отдельная модель, а не поле у `QuestionEntryRead`: в деле задачи ответ — своя
    запись рядом с вопросом, и вложить его туда значило бы отдать одну запись дважды.
    Здесь дела рядом нет, и без вложения клиенту пришлось бы собирать ответы запросом
    на каждую задачу.
    """

    answers: list[AnswerEntryRead] = Field(
        default_factory=list,
        description=(
            "`answer` entries of the same task that point at this question, by entry "
            "number. The first one closed the question, the rest add to it. Empty means "
            "the question is still open"
        ),
    )


class VerdictEntryRead(_EntryReadBase):
    """Вердикт по обзорной проверке. Тело записи — доказательство."""

    type: Literal[EntryType.VERDICT]
    payload: VerdictPayload


class RemarkEntryRead(_EntryReadBase):
    """Замечание к сделанному. Открыто, пока в деле нет `resolution` с его номером."""

    type: Literal[EntryType.REMARK]
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


class ResolutionEntryRead(_EntryReadBase):
    """Резолюция по замечанию: чем разобрано и куда ушла работа."""

    type: Literal[EntryType.RESOLUTION]
    payload: ResolutionPayload


class StatusChangedEntryRead(_EntryReadBase):
    """Служебная запись о переходе статуса."""

    type: Literal[EntryType.STATUS_CHANGED]
    payload: StatusChangedPayload


class SectionChangedEntryRead(_EntryReadBase):
    """Служебная запись о правке названия, описания или раздела."""

    type: Literal[EntryType.SECTION_CHANGED]
    payload: SectionChangedPayload


class FieldChangedEntryRead(_ProjectOwnableEntryRead):
    """Служебная запись о правке обвязки задачи (`priority`) или карточки проекта
    (название, описание)."""

    type: Literal[EntryType.FIELD_CHANGED]
    payload: FieldChangedPayload


class AssigneeChangedEntryRead(_EntryReadBase):
    """Служебная запись о смене исполнителя."""

    type: Literal[EntryType.ASSIGNEE_CHANGED]
    payload: AssigneeChangedPayload


class LinkEntryRead(_EntryReadBase):
    """Служебная запись о появлении или снятии связи."""

    type: Literal[EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
    payload: LinkPayload


class AttributeCreatedEntryRead(_ProjectEntryRead):
    """Служебная запись: атрибут проекта заведён."""

    type: Literal[EntryType.ATTRIBUTE_CREATED]
    payload: AttributeCreatedPayload


class AttributeChangedEntryRead(_ProjectEntryRead):
    """Служебная запись: значение атрибута проекта изменено."""

    type: Literal[EntryType.ATTRIBUTE_CHANGED]
    payload: AttributeChangedPayload


class AttributeRemovedEntryRead(_ProjectEntryRead):
    """Служебная запись: атрибут проекта снят."""

    type: Literal[EntryType.ATTRIBUTE_REMOVED]
    payload: AttributeRemovedPayload


class ProjectArchiveEntryRead(_ProjectEntryRead):
    """Служебная запись: проект архивирован (`archived`) или восстановлен (`restored`)."""

    type: Literal[EntryType.ARCHIVED, EntryType.RESTORED]
    payload: ProjectArchivePayload


type EntryRead = Annotated[
    PlainEntryRead
    | SummaryEntryRead
    | QuestionEntryRead
    | AnswerEntryRead
    | VerdictEntryRead
    | RemarkEntryRead
    | ResolutionEntryRead
    | StatusChangedEntryRead
    | SectionChangedEntryRead
    | FieldChangedEntryRead
    | AssigneeChangedEntryRead
    | LinkEntryRead
    | AttributeCreatedEntryRead
    | AttributeChangedEntryRead
    | AttributeRemovedEntryRead
    | ProjectArchiveEntryRead,
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
    EntryType.REMARK: RemarkEntryRead,
    EntryType.RESOLUTION: ResolutionEntryRead,
    EntryType.STATUS_CHANGED: StatusChangedEntryRead,
    EntryType.SECTION_CHANGED: SectionChangedEntryRead,
    EntryType.FIELD_CHANGED: FieldChangedEntryRead,
    EntryType.ASSIGNEE_CHANGED: AssigneeChangedEntryRead,
    EntryType.LINK_ADDED: LinkEntryRead,
    EntryType.LINK_REMOVED: LinkEntryRead,
    EntryType.ATTRIBUTE_CREATED: AttributeCreatedEntryRead,
    EntryType.ATTRIBUTE_CHANGED: AttributeChangedEntryRead,
    EntryType.ATTRIBUTE_REMOVED: AttributeRemovedEntryRead,
    EntryType.ARCHIVED: ProjectArchiveEntryRead,
    EntryType.RESTORED: ProjectArchiveEntryRead,
}


def entry_read(
    entry: Entry, *, task_key: str | None = None, project_key: str | None = None
) -> EntryRead:
    """Собирает вариант ответа по типу записи.

    Ключ владельца приходит от вызывающего: у записи связи с задачей и проектом нет,
    только `task_id` или `project_id`. Передаётся ровно один — ключ задачи для записи
    задачи, ключ проекта для записи дела проекта.

    Тип, которого нет в таблице, — это запись без формы нагрузки, то есть дефект
    объединения, а не рабочее состояние: `KeyError` здесь честнее молчаливого
    возврата записи со свободным `payload`, который фронт не разберёт.
    """
    assert (task_key is None) != (project_key is None), "entry owner is exactly one key"
    return _READ_MODELS.get(entry.type, PlainEntryRead)(
        id=entry.id,
        seq=entry.seq,
        no=entry.no,
        task_key=task_key,
        project_key=project_key,
        type=entry.type,
        author=AuthorRead.model_validate(entry.author),
        title=entry.title,
        body=entry.body,
        payload=entry.payload,
        refs=list(entry.refs),
        created_at=entry.created_at,
        action_id=entry.action_id,
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
    """Решение, попытка, находка, артефакт, заметка. Нагрузки нет.

    Замечание сюда не входит: у него свой вариант (`RemarkEntryCreate`), потому что
    `type` — разметка объединения, и один вариант на шесть типов не дал бы фронтенду
    сузить тип до замечания там, где это нужно.
    """

    type: Literal[
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.NOTE,
    ]


class SummaryEntryCreate(_EntryCreateBase):
    """Сводка посреди работы. Заголовок не принимается: он равен первой строке `done`.

    Нагрузка — четыре части и только они: закрывающая сводка сюда не подшивается, у неё
    своя дверь (`POST /tasks/{key}/close`) и своя модель с `unmeasured`.
    """

    type: Literal[EntryType.SUMMARY]
    payload: SummaryPartsPayload


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


class RemarkEntryCreate(_TitledEntryCreate):
    """Замечание: «вышло не то». Нагрузки нет, заголовок пишет автор."""

    type: Literal[EntryType.REMARK]


class ResolutionEntryCreate(_EntryCreateBase):
    """Резолюция. Заголовок не принимается: он собирается из ссылки на замечание и исхода."""

    type: Literal[EntryType.RESOLUTION]
    payload: ResolutionPayload


type EntryCreate = Annotated[
    PlainEntryCreate
    | SummaryEntryCreate
    | QuestionEntryCreate
    | AnswerEntryCreate
    | VerdictEntryCreate
    | RemarkEntryCreate
    | ResolutionEntryCreate,
    Field(discriminator="type"),
]
"""Подшиваемая запись: те же типы, что доступны агенту, размеченные по `type`."""


class ProjectEntryCreate(_TitledEntryCreate):
    """Запись агента или человека в деле проекта: заметка, решение, находка, артефакт.

    Отдельная модель, а не ветвь `EntryCreate`: набор типов у дела проекта свой
    (`CONCEPT.md`, 3.4, «Дело проекта»), и схема показывает его клиенту до запроса, а не
    отказом `entry_fields_invalid` после.
    """

    type: Literal[
        EntryType.NOTE,
        EntryType.DECISION,
        EntryType.FINDING,
        EntryType.ARTIFACT,
    ]


type ClosingEntryCreate = Annotated[
    PlainEntryCreate | RemarkEntryCreate,
    Field(discriminator="type"),
]
"""Запись, которую подшивают закрытием задачи: только та, где нет нагрузки.

Сводка и вердикты в закрытии лежат своими полями. Вопрос, ответ и резолюция закрытием
не подшиваются: вопрос в момент закрытия означает, что задача не закрывается,
резолюция разбирает замечание и стоит своего вызова.
"""
