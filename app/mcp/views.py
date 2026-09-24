"""Данные, которые инструмент отдаёт агенту.

Каждое представление — модель pydantic, и она же объявляет форму ответа инструмента.
SDK строит из возвращаемого типа `outputSchema`, кладёт её в `tools/list` и сам
сворачивает результат в `structured_content`. Значит форму ответа модель читает **до**
вызова, а не выводит из ответа задним числом, и опечатка в имени поля ловится там же,
где живёт поле, а не сравнением с REST в конце прогона.

Из этого же следует, чего здесь делать не надо. `datetime` не приводится к строке
руками: это сделает сериализатор pydantic, и сделает так же, как у REST
(`2026-09-04T10:00:00Z`, а не `...+00:00`) — «поле в поле» держится именно на нём.
Перечисления объявлены доменными типами, а не строками: значение на проводе то же
самое, но в схеме появляется список допустимого, и агент видит его до вызова.

## Почему модели живут здесь, а не берутся из `api`

`mcp` не имеет права зависеть от `api` (`docs/CONVENTIONS.md`): расхождение интерфейсов
проект ловит тем, что оба зовут одни сценарии, а не тем, что делят схемы ответов. Общая
модель ответа связала бы их сильнее, чем нужно, и правка ради интерфейса человека
поехала бы к агенту сама. Поэтому имена и смысл полей здесь повторяют
`app/api/schemas/`, а удерживает их вместе тест `tests/test_mcp_tools.py`, сравнивающий
пакет преемника из MCP с ответом REST.

Повторение при этом не бесплатно, и цена названа осознанно: два места правятся вместе, а
несовпадение ловит тест. Обратное — одна схема на два интерфейса — стоило бы дороже:
ответ REST длиннее (`id`, счётчики, времена правки), и агент платил бы за него контекстом
на каждом вызове.

## Почему для этого не нужен агентный фреймворк

Соблазн взять `pydantic-ai` проверен и отвергнут (`TRK-17`). Он решает другую задачу:
это агентный рантайм, и его часть про MCP — **клиент** (подключение чужих серверов как
инструментов агента) плюс приём «агент внутри инструмента». Инструменты сервера в его
примерах объявляются тем же SDK, а типы даёт pydantic — то есть ровно то, что здесь уже
стоит. Тянуть его значило бы добавить рантайм для вызова моделей в бэкенд, который
моделей не зовёт.

## Что совпадает с REST, а что нарочно короче

Пакет преемника (`task_package`) совпадает **целиком**: это вход агента в задачу, и
терять в нём поля нельзя. Справочные представления — очередь и участник — короче: агенту
нужен контекст, а не строка реестра, и `id`, времена правки и подпись заводившего съели
бы контекст, ничего не добавив к решению.

## Почему ответ изменяющего инструмента короче пакета преемника

`transition`, `update_task` и `create_task` отвечают `mutation` — четырьмя полями вместо
карточки. Это продолжение того же правила, и разница здесь не в объёме, а в том, **кто
уже знает содержимое**.

Агент приходит к изменению из `get_task`: описание, пять разделов и список проверок он
прочитал и держит в контексте. Вернуть их снова значит взять с него плату второй раз за
то же самое, и цена растёт с числом переходов: у задачи, идущей `backlog → open →
in_progress → done`, карточка приезжала четыре раза. Замер на живой сессии показал
задачу, чьи разделы приехали восемь раз.

Поэтому в коротком ответе остаётся ровно то, чего агент **не мог знать заранее**: новая
версия (без неё следующий `update_task` упрётся в `version_conflict`), новый статус (его
выбрал не только вызывающий, но и таблица переходов) и номера подшитых записей (их
выдаёт база). Ключ повторяется, потому что ответ должен читаться сам по себе. Всё
остальное агент прислал сам либо уже видел.

У `create_task` причина другая, а вывод тот же. Агент не читал новую задачу — она только
что появилась; он **сам прислал** всё, из чего она собрана: название, описание и пять
разделов приезжали обратно тем же текстом. При декомпозиции на десять детей это десять
карточек в контексте, каждая из которых уже там есть. Ключ здесь не повторение, а
единственное настоящее новое знание: его выдал трекер, и адресовать следующий вызов
иначе нечем. Статус остаётся, хотя он всегда `backlog`: ответ должен читаться сам по
себе, не требуя помнить, куда создание кладёт задачу.

Шесть подшивающих инструментов (`add_summary`, `add_entry`, `ask`, `answer`, `resolve`,
`add_verdict`) отвечают `appended_entry` по той же причине, что `create_task`: агент сам
прислал всё, из чего запись собрана. Цена только выше. Запись целиком — это `body`,
`payload`, `refs` и `type`, приехавшие аргументами того же вызова: сводка возвращала
обратно те же четыре части, `add_entry` с разбором решения — килобайты. Дисциплина
требует подшивать часто, и полный ответ облагал её налогом в размер подшитого: за сессию
с десятью сводками это десять сводок в контексте второй раз.

Остаётся то, чего агент не знал, **и** чем он делает следующий ход: `no` (им адресуют
`answer`, `resolve` и ссылки `TRK-42#12`), `seq` (курсор ленты для `wait_journal`),
`created_at` и подпись автора — её трекер нормализует. `id` не остаётся, хотя агент его
тоже не знал: адресация в MCP идёт парой «ключ и номер», и UUID был бы неизвестным, ходить
которым некуда.

Заголовок — единственное поле, которое возвращается **не всегда**, и это не второй режим, а
разница в том, кто его написал. У сводки, ответа, вердикта и резолюции заголовок не
принимается вовсе: его собирает трекер (`app/domain/case.py`, `_derive_title`), и у сводки
собирает с потерями — первая непустая строка `done`, обрезанная по границе слова. Это
вычисленное значение, а не эхо, и агент видит ровно ту строку, которую преемник прочтёт в
описи. Там, где заголовок прислал агент, в ответе стоит `null`: строка описи — та самая,
что ушла в аргументах.

Ответ закрытия (`close_task`) собран из этих же двух правил и ничего к ним не
добавляет: короткая мутация задачи — ключ, новый статус, новая версия — плюс строка на
каждую подшитую запись тем же `AppendedEntryView`. Записей в нём столько, сколько
подшил вызов, и весь разброс его размера сидит в одном месте — в заголовке сводки,
который трекер вывел из `done` (`docs/notes/mcp.md`).

Второго, полного режима у этих инструментов нет намеренно: параметр вроде `fields` дал бы
два поведения, из которых проверяется одно. Кому нужна карточка целиком — зовёт
`get_task`, запись целиком — `read_entries`, и это сказано в описании каждого инструмента,
чтобы агент не звал их на всякий случай после каждого действия.

Ответы этих инструментов при этом хранятся ключом идемпотентности, и повтор отдаёт
**сохранённое**, а не пересобранное (`app/services/idempotency.py`): сутки после правки
в таблице лежат ответы обеих форм, и на вчерашний вызов придёт вчерашняя карточка или
вчерашняя запись целиком. Это не переходный режим в коде, а свойство хранилища, и
кончается оно само — `KEY_TTL`. Разбирать старую форму при этом никто не обязан и кода
под неё нет: сохранённый ответ поднимает та же модель, что и новый, лишние поля она
отбрасывает, а недостающих у неё нет — прежняя запись была длиннее короткой, не короче.
Расхождение остаётся ровно одно: у вчерашней `add_entry` в поле `title` приедет
присланный тогда заголовок, а не `null`.

REST этого правила не знает и знать не должен: там потребитель другой — интерфейс,
который перерисовывает карточку после каждого действия и ходит за ней в ту же секунду.

## Обрезка длинного текста

Единственное место обрезки — выдача `search_tasks` (`TRACKER_MCP_TEXT_LIMIT`): только там
в одном ответе может оказаться два десятка описаний и разделов. Обрезка объявлена рядом
со значением (`<поле>_truncated`, `<поле>_length`), а полный текст — один вызов
`get_task`. Тела записей дела не обрезаются нигде: их запрашивают по номеру, и взять
полный текст было бы больше неоткуда.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from app.db.models.entry import Entry
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.authors import Author, AuthorKind
from app.domain.case import (
    TITLED_ENTRY_TYPES,
    AnswerFacts,
    AssigneeChangedFacts,
    EntryFacts,
    EntryHeading,
    EntryType,
    FieldChangedFacts,
    LinkFacts,
    NoFacts,
    QuestionFacts,
    RemarkOutcome,
    ResolutionFacts,
    SectionChangedFacts,
    StatusChangedFacts,
    VerdictFacts,
    VerdictOutcome,
)
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.search import FEATURES_FIELD, MANDATORY_FIELD, PARENT_FIELD
from app.domain.tasks import TaskFeatures, TaskField, TaskParent, TaskPriority, TaskStatus
from app.services.links import TaskLink
from app.services.search import FoundTask
from app.services.tasks import TaskClosure, TaskMutation, TaskPackage

#: Поля задачи, которые бывают длинными: описание и пять разделов. Обрезаются только они
#: и только в выдаче поиска.
LONG_TEXT_FIELDS: frozenset[str] = frozenset(
    {"description", "goal", "context", "constraints", "output"}
)


class AuthorView(BaseModel):
    """Кто сделал действие: род и подпись. У самого трекера подписи нет."""

    kind: AuthorKind
    signature: str | None


def author(value: Author) -> AuthorView:
    """Кто сделал действие: род и подпись. У самого трекера подписи нет."""
    return AuthorView(kind=value.kind, signature=value.signature)


class QueueRefView(BaseModel):
    """Очередь одной строкой: ключ и название."""

    key: str
    title: str


def queue_ref(queue: Queue) -> QueueRefView:
    """Очередь одной строкой: ключ и название. Описание запрашивают `get_queue`.

    Одно представление на карточку задачи и на выдачу `list_queues`: очередь, названная
    коротко, обязана выглядеть одинаково везде, где она не главный предмет ответа.
    """
    return QueueRefView(key=queue.key, title=queue.title)


class TaskView(BaseModel):
    """Карточка задачи — тот же набор полей, что у `TaskRead` в REST."""

    id: str
    key: str
    queue: QueueRefView
    title: str
    description: str
    goal: str
    context: str
    constraints: str
    output: str
    checks: list[str]
    status: TaskStatus
    assignee: str | None
    priority: TaskPriority
    version: int
    created_by: AuthorView
    created_at: datetime
    updated_at: datetime


def task(item: Task) -> TaskView:
    """Карточка задачи — тот же набор полей, что у `TaskRead` в REST."""
    return TaskView(
        id=str(item.id),
        key=item.key,
        queue=queue_ref(item.queue),
        title=item.title,
        description=item.description,
        goal=item.goal,
        context=item.context,
        constraints=item.constraints,
        output=item.output,
        checks=list(item.checks),
        status=item.status,
        assignee=item.assignee,
        priority=item.priority,
        version=item.version,
        created_by=author(item.created_by),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class MutationView(BaseModel):
    """Ответ изменяющего инструмента: что стало и чем это подшито, без карточки."""

    key: str
    status: TaskStatus
    version: int
    entries: list[int]
    parent_entry: int | None = Field(
        default=None,
        description=(
            "Number of the `link_added` entry filed into the parent task's own case "
            "when `create_task` was given `parent`. `null` when no `parent` was given, "
            "and always `null` for `transition` and `update_task`: they touch no other "
            "task's case."
        ),
    )


def mutation(value: TaskMutation, *, parent_entry: int | None = None) -> MutationView:
    """Ответ изменяющего инструмента: что стало и чем это подшито, без карточки.

    Почему не карточка — в шапке модуля. Здесь важно, что `entries` бывает пустым, и
    это законный ответ: клиент прислал то, что уже стоит, — версия не выросла, дело не
    пополнилось. Отличать «применилось» от «уже так было» агент будет именно по нему,
    поэтому отдельного поля `changed` рядом нет: два способа узнать один факт разошлись
    бы при первой же правке.

    `parent_entry` называет номер записи в **чужом** деле — родителя, которого дал
    `create_task`; `entries`, наоборот, всегда о деле **своей** задачи, и смешивать два
    дела в одном списке значило бы отдать номер без адреса, к какому делу он относится.
    У `transition` и `update_task` параметр не передаётся и остаётся `null`: они не
    трогают чужих дел вовсе.
    """
    return MutationView(
        key=value.task.key,
        status=value.task.status,
        version=value.task.version,
        entries=list(value.entries),
        parent_entry=parent_entry,
    )


class FeaturesView(BaseModel):
    """Вычисляемые признаки задачи (`CONCEPT.md`, 4.3)."""

    blocked: bool
    open_questions: int
    open_blocking_questions: int
    open_remarks: int
    last_summary_at: datetime | None
    last_entry_at: datetime | None


def features(value: TaskFeatures) -> FeaturesView:
    """Вычисляемые признаки задачи (`CONCEPT.md`, 4.3)."""
    return FeaturesView(
        blocked=value.blocked,
        open_questions=value.open_questions,
        open_blocking_questions=value.open_blocking_questions,
        open_remarks=value.open_remarks,
        last_summary_at=value.last_summary_at,
        last_entry_at=value.last_entry_at,
    )


class ParentView(BaseModel):
    """Родитель задачи в строке выдачи: ключ и название (`CONCEPT.md`, 4.4)."""

    key: str
    title: str


def parent_row(value: TaskParent) -> ParentView:
    """Родитель задачи в строке выдачи: ключ и название (`CONCEPT.md`, 4.4)."""
    return ParentView(key=value.key, title=value.title)


class FoundTaskView(BaseModel):
    """Строка выдачи поиска: карточка задачи, у которой любое поле может отсутствовать.

    Единственная модель слоя с необязательными полями, и это не послабление типизации, а
    её предмет. Список умеет отдавать подмножество полей (`fields`), и схема обязана
    честно это показывать — ровно так же, как `TaskSearchRead` в REST.

    Отсюда же сериализатор ниже. SDK сворачивает результат вызовом
    `model_dump(mode="json")` — **без** `exclude_unset`, — и незапрошенное поле приезжало
    бы агенту как `null`. Это не то же самое, что «поля нет»: пакет обязан совпадать с
    ответом REST поле в поле, а тот отдаётся с `response_model_exclude_unset`.

    Схему сериализатор не портит, и это проверено: SDK строит `outputSchema` через
    `TypeAdapter(...).json_schema()`, у которого режим по умолчанию — **валидация**, а
    обёрточный сериализатор действует только на схему сериализации. У FastAPI режим
    противоположный, поэтому предупреждение заметки `docs/notes/api.md` («Отбросить
    пустые поля в ответе — значит потерять схему у клиента») сюда не переносится.
    """

    key: str
    id: str | None = None
    queue: QueueRefView | None = None
    title: str | None = None
    description: str | None = None
    goal: str | None = None
    context: str | None = None
    constraints: str | None = None
    output: str | None = None
    checks: list[str] | None = None
    status: TaskStatus | None = None
    assignee: str | None = None
    priority: TaskPriority | None = None
    version: int | None = None
    created_by: AuthorView | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    features: FeaturesView | None = None
    parent: ParentView | None = None
    # Обрезка объявляется рядом со значением, поэтому у каждого длинного поля своя пара
    # признаков. Пять полей, десять имён — перечислены, а не собраны генератором:
    # схему инструмента читает модель, и имя поля в ней должно быть видно как имя.
    description_truncated: bool | None = None
    description_length: int | None = None
    goal_truncated: bool | None = None
    goal_length: int | None = None
    context_truncated: bool | None = None
    context_length: int | None = None
    constraints_truncated: bool | None = None
    constraints_length: int | None = None
    output_truncated: bool | None = None
    output_length: int | None = None

    @model_serializer(mode="wrap")
    def _only_what_was_asked(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Оставляет в ответе только заданные поля: «поля нет» — не то же, что `null`."""
        return {
            name: value for name, value in handler(self).items() if name in self.model_fields_set
        }


def found_task(found: FoundTask, *, fields: Sequence[str], text_limit: int) -> FoundTaskView:
    """Строка выдачи поиска: только запрошенные поля, длинные тексты с потолком.

    Пустой набор полей означает «вся задача» — то же правило, что в REST. Ключ остаётся
    всегда: выдача без него бесполезна, по ней нельзя ни прочитать задачу, ни сослаться
    на неё.

    Признаки идут вложенным объектом, тем же, что в пакете преемника: агент, выбирающий
    задачу из списка, видит `blocked` и открытые вопросы сразу, а не вызывает `get_task`
    на каждую строку. Их нет в ответе, если их не просили (`fields` без `features`).
    Родитель — по тому же правилу: ключ и название, `null` у задачи верхнего уровня, и
    поля нет вовсе, если его не просили.

    Карточка разбирается на словарь через `dict()`, а не собирается вторым списком
    полей: набор полей строки — это набор полей `TaskView`, и второе его перечисление
    разъехалось бы с первым на первом же новом поле.
    """
    payload: dict[str, Any] = dict(task(found.task))
    if found.features is not None:
        payload[FEATURES_FIELD] = features(found.features)
    if found.parent is not None:
        asked = found.parent.value
        payload[PARENT_FIELD] = None if asked is None else parent_row(asked)
    if fields:
        selected = {*fields, MANDATORY_FIELD}
        payload = {name: value for name, value in payload.items() if name in selected}
    for name in LONG_TEXT_FIELDS & payload.keys():
        _clip_into(payload, name, text_limit)
    return FoundTaskView(**payload)


class LinkOtherView(BaseModel):
    """Задача на другом конце связи."""

    key: str
    title: str
    status: TaskStatus


class LinkView(BaseModel):
    """Связь со стороны своей задачи: вид назван ролью **этой** задачи."""

    kind: LinkKind
    other: LinkOtherView
    author: AuthorView
    created_at: datetime


def link_other(value: TaskLink) -> LinkOtherView:
    """Задача на другом конце связи: ключ, название и статус — родитель или ребёнок."""
    return LinkOtherView(key=value.other.key, title=value.other.title, status=value.other.status)


def link(value: TaskLink) -> LinkView:
    """Связь со стороны своей задачи: вид назван ролью **этой** задачи.

    В `other` лежит задача на **другом** конце — сторону вычислил сценарий, и определять
    её здесь во второй раз не нужно и неверно: канонизация могла записать связь в
    обратном порядке (`docs/notes/mcp.md`).
    """
    return LinkView(
        kind=value.kind,
        other=LinkOtherView(
            key=value.other.key, title=value.other.title, status=value.other.status
        ),
        author=author(value.author),
        created_at=value.created_at,
    )


class UnlinkView(BaseModel):
    """Ответ `unlink`: какая связь снята и с какой стороны её назвали."""

    key: str
    kind: LinkKind
    other: str
    removed: bool


class NoFactsView(BaseModel):
    """Фактов нет: заголовок записи пишет её автор."""

    type: Literal[
        EntryType.SUMMARY,
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.REMARK,
        EntryType.NOTE,
        EntryType.CREATED,
    ]


class StatusChangedFactsView(BaseModel):
    """Переход статуса: оба конца и был ли назван повод."""

    type: Literal[EntryType.STATUS_CHANGED]
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    has_reason: bool | None


class SectionChangedFactsView(BaseModel):
    """Правка задания: какой раздел, и какая проверка при точечной правке."""

    type: Literal[EntryType.SECTION_CHANGED]
    field: TaskField | None
    check_no: int | None


class FieldChangedFactsView(BaseModel):
    """Правка обвязки: какое поле."""

    type: Literal[EntryType.FIELD_CHANGED]
    field: TaskField | None


class AssigneeChangedFactsView(BaseModel):
    """Смена исполнителя: оба имени."""

    type: Literal[EntryType.ASSIGNEE_CHANGED]
    assignee_from: str | None
    assignee_to: str | None


class LinkFactsView(BaseModel):
    """Связь появилась или снята: её вид и вторая сторона."""

    type: Literal[EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
    link_kind: LinkKind | None
    other_key: str | None


class QuestionFactsView(BaseModel):
    """Вопрос: кому адресован и держит ли работу."""

    type: Literal[EntryType.QUESTION]
    addressees: list[str] | None
    blocking: bool | None


class AnswerFactsView(BaseModel):
    """Ответ: на какой вопрос той же задачи."""

    type: Literal[EntryType.ANSWER]
    question_no: int | None


class VerdictFactsView(BaseModel):
    """Вердикт: какая проверка, чем кончилась и не переписали ли её после."""

    type: Literal[EntryType.VERDICT]
    check_no: int | None
    outcome: VerdictOutcome | None
    outdated: bool | None


class ResolutionFactsView(BaseModel):
    """Резолюция: какое замечание разобрано, чем и куда ушла работа."""

    type: Literal[EntryType.RESOLUTION]
    remark_no: int | None
    outcome: RemarkOutcome | None
    continuation_key: str | None


type FactsView = Annotated[
    NoFactsView
    | StatusChangedFactsView
    | SectionChangedFactsView
    | FieldChangedFactsView
    | AssigneeChangedFactsView
    | LinkFactsView
    | QuestionFactsView
    | AnswerFactsView
    | VerdictFactsView
    | ResolutionFactsView,
    Field(discriminator="type"),
]
"""Факты записи: те же формы и те же поля в том же порядке, что в схеме REST."""


def facts(value: EntryFacts) -> FactsView:
    """Факты записи для описи: те же формы и поля, что в схеме REST.

    Пакет преемника обязан совпадать с ответом REST поле в поле (обзорная проверка
    задачи 03, `tests/test_mcp_tools.py`), поэтому «отдать факты только интерфейсу»
    нельзя: расхождение здесь означало бы два разных описания одного дела. Разметка по
    `type` едет и сюда — по ней агент видит состав полей своей записи в `outputSchema`
    инструмента, до вызова, а не по тому, какие ключи пришли непустыми.

    Разбор — по форме факта, а не по типу записи: типов восемнадцать, а форм десять, и
    сопоставление одного с другим живёт в одном месте, в домене.
    """
    match value:
        case NoFacts():
            return NoFactsView(type=value.type)
        case StatusChangedFacts():
            return StatusChangedFactsView(
                type=value.type,
                from_status=value.from_status,
                to_status=value.to_status,
                has_reason=value.has_reason,
            )
        case SectionChangedFacts():
            return SectionChangedFactsView(
                type=value.type, field=value.field, check_no=value.check_no
            )
        case FieldChangedFacts():
            return FieldChangedFactsView(type=value.type, field=value.field)
        case AssigneeChangedFacts():
            return AssigneeChangedFactsView(
                type=value.type,
                assignee_from=value.assignee_from,
                assignee_to=value.assignee_to,
            )
        case LinkFacts():
            return LinkFactsView(
                type=value.type, link_kind=value.link_kind, other_key=value.other_key
            )
        case QuestionFacts():
            return QuestionFactsView(
                type=value.type,
                addressees=None if value.addressees is None else list(value.addressees),
                blocking=value.blocking,
            )
        case AnswerFacts():
            return AnswerFactsView(type=value.type, question_no=value.question_no)
        case VerdictFacts():
            return VerdictFactsView(
                type=value.type,
                check_no=value.check_no,
                outcome=value.outcome,
                outdated=value.outdated,
            )
        case ResolutionFacts():
            return ResolutionFactsView(
                type=value.type,
                remark_no=value.remark_no,
                outcome=value.outcome,
                continuation_key=value.continuation_key,
            )
    # Форма фактов, заведённая в домене без представления здесь, — дефект объединения, а
    # не рабочее состояние: молча вернуть `None` значило бы отдать агенту опись без строки.
    raise TypeError(f"форма фактов без представления MCP: {type(value).__name__}")


class HeadingView(BaseModel):
    """Строка описи дела: то, что видно о записи, не читая её тела."""

    no: int
    type: EntryType
    author: AuthorView
    created_at: datetime
    title: str
    action_id: str | None = Field(
        default=None,
        description=(
            "Marks the single call that filed this entry: entries of one call share "
            "the same value, entries of another call never do. `null` on entries "
            "filed before this field existed"
        ),
    )
    facts: FactsView


def heading(value: EntryHeading) -> HeadingView:
    """Строка описи дела: то, что видно о записи, не читая её тела."""
    return HeadingView(
        no=value.no,
        type=value.type,
        author=author(value.author),
        created_at=value.created_at,
        title=value.title,
        action_id=None if value.action_id is None else str(value.action_id),
        facts=facts(value.facts),
    )


class EntryView(BaseModel):
    """Запись дела целиком.

    `payload` — единственное поле слоя без объявленной формы, и это то же исключение,
    что и в схеме REST (`docs/notes/api.md`, «`payload` записи дела — исключение из
    типизации, названное по месту»): нагрузка своя у каждого типа записи, и типизирует
    её отдельная задача — сразу в обоих интерфейсах, иначе они разойдутся. `JsonValue`,
    а не `Any`: форма свободна, но значение обязано быть представимо в JSON.
    """

    id: str
    seq: int
    no: int
    task_key: str
    type: EntryType
    author: AuthorView
    title: str
    body: str
    payload: dict[str, JsonValue]
    refs: list[str]
    created_at: datetime
    action_id: str | None = Field(
        default=None,
        description=(
            "Marks the single call that filed this entry: entries of one call share "
            "the same value, entries of another call never do. `null` on entries "
            "filed before this field existed"
        ),
    )


def entry(value: Entry, *, task_key: str) -> EntryView:
    """Запись дела целиком. Ключ задачи приходит извне: у записи только `task_id`."""
    return EntryView(
        id=str(value.id),
        seq=value.seq,
        no=value.no,
        task_key=task_key,
        type=value.type,
        author=author(value.author),
        title=value.title,
        body=value.body,
        payload=dict(value.payload),
        refs=list(value.refs),
        created_at=value.created_at,
        action_id=None if value.action_id is None else str(value.action_id),
    )


class AppendedEntryView(BaseModel):
    """Ответ подшивающего инструмента: чем запись адресуют, без самой записи.

    `title` непуст только там, где заголовок собрал трекер: у сводки, ответа, вердикта и
    резолюции его не принимают вовсе (`app/domain/case.py`, `TITLED_ENTRY_TYPES`). Где
    заголовок прислал агент, здесь стоит `null` — «в описи ровно то, что ты прислал».
    """

    no: int
    seq: int
    task_key: str
    author: AuthorView
    title: str | None
    created_at: datetime


def appended_entry(value: Entry, *, task_key: str) -> AppendedEntryView:
    """Ответ подшивающего инструмента: чем запись адресуют, без самой записи.

    Почему не запись целиком — в шапке модуля. Здесь важно, откуда берётся `title`:
    из принадлежности типа к `TITLED_ENTRY_TYPES`, а не из списка типов, переписанного
    по месту. Заголовок, выведенный у нового типа записи, приедет сюда сам.
    """
    return AppendedEntryView(
        no=value.no,
        seq=value.seq,
        task_key=task_key,
        author=author(value.author),
        title=None if value.type in TITLED_ENTRY_TYPES else value.title,
        created_at=value.created_at,
    )


class ClosedTaskView(BaseModel):
    """Ответ закрытия: чем стала задача и чем это подшито, без карточки и без записей.

    Элемент списка — то же `AppendedEntryView`, каким отвечает подшивающий инструмент,
    поэтому ключ задачи повторяется в каждом: восьмое представление ради двадцати
    сэкономленных байт развело бы две формы одной и той же записи, которые разойдутся
    при первой правке.

    Поле, добавленное сюда позже, обязано иметь значение по умолчанию: ответ создающего
    инструмента живёт сутки в ключах идемпотентности, и вчерашнее тело без нового поля
    не поднимется (`docs/notes/mcp.md`, «Сузить форму ответа создающего инструмента
    можно, расширить — нельзя»).
    """

    key: str
    status: TaskStatus
    version: int
    entries: list[AppendedEntryView] = Field(default_factory=list)


def closed_task(closure: TaskClosure) -> ClosedTaskView:
    """Ответ закрытия: чем стала задача и чем это подшито, без карточки и без записей.

    Записи идут в порядке подшивки и кончаются `status_changed`: то, что задача закрыта,
    — такая же страница дела, как вердикт, и её номер приезжает тем же списком.
    """
    return ClosedTaskView(
        key=closure.task.key,
        status=closure.task.status,
        version=closure.task.version,
        entries=[appended_entry(item, task_key=closure.task.key) for item in closure.entries],
    )


class TaskPackageView(BaseModel):
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом."""

    task: TaskView
    #: Родитель и дети — полями, а не видами в `links` (TRK-135): имя поля и есть ответ
    #: на «кто родитель», направление разбирать не нужно.
    parent: LinkOtherView | None
    children: list[LinkOtherView]
    links: list[LinkView]
    features: FeaturesView
    summary: EntryView | None
    questions: list[EntryView]
    remarks: list[EntryView]
    transitions: list[TaskStatus]
    index: list[HeadingView]


def task_package(package: TaskPackage) -> TaskPackageView:
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.

    Совпадает с `GET /api/v1/tasks/{key}` поле в поле, и это проверяется тестом. Не
    ради красоты: агент и человек обязаны видеть одну и ту же задачу, иначе разбор
    «почему агент решил иначе, чем показывал интерфейс» упирается в два разных ответа.
    """
    key = package.task.key
    return TaskPackageView(
        task=task(package.task),
        parent=None if package.parent is None else link_other(package.parent),
        children=[link_other(item) for item in package.children],
        links=[link(item) for item in package.links],
        features=features(package.features),
        summary=None if package.summary is None else entry(package.summary, task_key=key),
        questions=[entry(question, task_key=key) for question in package.questions],
        remarks=[entry(remark, task_key=key) for remark in package.remarks],
        transitions=list(package.transitions),
        index=[heading(item) for item in package.index],
    )


class QueueView(BaseModel):
    """Очередь с описанием — общим контекстом всех её задач."""

    key: str
    title: str
    description: str


def queue(item: Queue) -> QueueView:
    """Очередь с описанием — общим контекстом всех её задач.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом.
    """
    return QueueView(key=item.key, title=item.title, description=item.description)


class ParticipantView(BaseModel):
    """Участник реестра: кому можно адресовать вопрос и что о нём известно."""

    kind: ParticipantKind
    name: str
    description: str


def participant(item: Participant) -> ParticipantView:
    """Участник реестра: кому можно адресовать вопрос и что о нём известно."""
    return ParticipantView(kind=item.kind, name=item.name, description=item.description)


class PageView[ItemT](BaseModel):
    """Страница выдачи. Форма одна у всех инструментов, которые её отдают."""

    items: list[ItemT]
    next_cursor: str | None


def page[ItemT](items: Iterable[ItemT], *, next_cursor: str | None) -> PageView[ItemT]:
    """Страница выдачи. Форма одна у всех инструментов, которые её отдают.

    `next_cursor` пуст — дальше ничего нет. Отдельного признака «есть ещё» здесь нет
    намеренно: два поля об одном и том же однажды разойдутся, а у REST он существует
    ради интерфейса, который рисует кнопку.

    Чем страница наполнена, объявляет инструмент своим возвращаемым типом
    (`PageView[EntryView]`), и по нему же SDK строит схему результата.
    """
    return PageView(items=list(items), next_cursor=next_cursor)


def _clip_into(payload: dict[str, Any], name: str, limit: int) -> None:
    """Обрезает поле и объявляет обрезку рядом с ним.

    Признак отдельным полем, а не многоточием в тексте: агент, сравнивающий строки, не
    должен принимать метку за часть значения. Полная длина сообщается тем же ответом —
    по ней видно, сколько осталось за краем.
    """
    text = payload[name]
    if not isinstance(text, str) or len(text) <= limit:
        return
    payload[name] = text[:limit]
    payload[f"{name}_truncated"] = True
    payload[f"{name}_length"] = len(text)
