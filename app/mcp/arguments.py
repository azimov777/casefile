"""Аргументы инструментов: общие аннотации и вложенные модели.

Описание аргумента — это то, что модель читает вместо документации, поэтому оно короткое
и несёт **дисциплину**, а не пересказ типа: «подшить в дело то, что должен знать
преемник» полезнее, чем «строка markdown». Пересказ схемы модель и так видит в самой
схеме.

## Границы значений здесь не повторяются

У схем REST границы длины продублированы ради документации и раннего отсева
(`app/api/schemas/`). Здесь их нет намеренно: проверку делает домен, и его отказ приезжает
агенту предметным кодом со списком полей (`entry_fields_invalid`, `details.fields`), а не
сообщением pydantic о нарушенной схеме. Пустая часть сводки, отсечённая `min_length=1`,
дала бы агенту ошибку валидации аргументов вместо ответа «поле `blockers` обязательно» —
то есть отобрала бы у него имя поля, по которому он чинит вызов.

## Частичное изменение — вложенная модель

У инструмента нет способа отличить пропущенный аргумент от `null`, если у параметра есть
значение по умолчанию (`docs/notes/mcp.md`). Поэтому изменения задачи приезжают объектом
`changes`, поля которого объявлены через `unset_field`, а `model_dump(exclude_unset=True)`
отдаёт ровно переданные ключи. Без этого правка тегов каждый раз снимала бы исполнителя,
а снять его было бы нечем.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.sentinels import unset_field
from app.domain.case import EntryType, RemarkOutcome, VerdictOutcome
from app.domain.idempotency import KEY_TTL
from app.domain.journal import JOURNAL_START, MAX_WAIT_SECONDS
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.search import FEATURES_FIELD, searchable_names, sortable_names
from app.domain.tasks import TaskPriority, TaskStatus

# --- Адресация ------------------------------------------------------------------------

TaskKeyArg = Annotated[
    str,
    Field(description="Ключ задачи, например `TRK-42`. Регистр не важен", examples=["TRK-42"]),
]
QueueKeyArg = Annotated[
    str,
    Field(description="Ключ очереди, например `TRK`. Регистр не важен", examples=["TRK"]),
]
ParticipantNameArg = Annotated[
    str,
    Field(description="Имя участника из реестра. Регистр не важен", examples=["release_bot"]),
]
ParentKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Ключ родительской задачи. Ребёнок рождается со ссылкой на родителя; "
            "родитель не уйдёт в `done`, пока дети не закрыты"
        ),
        examples=["TRK-42"],
    ),
]
VersionArg = Annotated[
    int | None,
    Field(
        description=(
            "Версия задачи, которую ты видел. Присланная обратно, она превращает "
            "потерянное чужое изменение в отказ `version_conflict` вместо тихой "
            "перезаписи. Не передавай, если задачу только что прочитал сам"
        ),
        examples=[3],
    ),
]

# --- Поля задачи ----------------------------------------------------------------------

TaskTitleArg = Annotated[
    str,
    Field(description="Название задачи одной строкой", examples=["Починить выдачу ключей задач"]),
]
TaskDescriptionArg = Annotated[
    str,
    Field(
        description="Описание задачи: что случилось и почему это задача",
        examples=["Ключ выдаётся до валидации и сгорает на неудачном запросе"],
    ),
]
AssigneeArg = Annotated[
    str | None,
    Field(
        description=(
            "Имя участника или метка временного агента. Трекер это поле не проверяет и "
            "сам не меняет: назначение агентов живёт вне трекера"
        ),
        examples=["release_bot"],
    ),
]
PriorityArg = Annotated[
    TaskPriority,
    Field(description="Приоритет задачи", examples=[TaskPriority.NORMAL]),
]
ReasonArg = Annotated[
    str | None,
    Field(
        description=(
            "Почему задача идёт туда. Обязательна для любого шага назад по цепочке "
            "`backlog < open < in_progress < done`, для `cancelled` и для `waiting`; в "
            "остальных переходах необязательна. У `waiting` она называет, чего ждём, — "
            "больше это записать негде. Попадает в дело записью `status_changed`"
        ),
        examples=["Жду ответа на TRK-42#7"],
    ),
]

# --- Страницы -------------------------------------------------------------------------

LimitArg = Annotated[
    int | None,
    Field(
        description=(
            "Сколько записей вернуть за раз. Без значения — размер страницы установки; "
            "каждая лишняя строка оплачена твоим контекстом"
        ),
        examples=[25],
    ),
]
CursorArg = Annotated[
    str | None,
    Field(description="Продолжение выдачи: значение `next_cursor` из прошлого ответа"),
]

# --- Идемпотентность ------------------------------------------------------------------

IdempotencyKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Ключ повтора, который ты придумываешь сам (обычно UUID). Повтор вызова с тем "
            "же ключом и теми же аргументами отвечает первым результатом и второго объекта "
            "не заводит; тот же ключ с другими аргументами отклоняется. Ключ живёт в паре "
            f"с твоим токеном и помнится {int(KEY_TTL.total_seconds() // 3600)} часа"
        ),
        examples=["6b1f0c34-9b2e-4b0a-9a5f-3f1d6c8e0a11"],
    ),
]

# --- Дело -----------------------------------------------------------------------------

EntryBodyArg = Annotated[
    str,
    Field(
        description=(
            "Тело записи в markdown: столько, сколько нужно преемнику, и не больше. "
            "Содержимое файлов и длинные выводы команд в дело не кладут — положи указатель"
        )
    ),
]
EntryRefsArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Ссылки: записи `TRK-42#12`, задачи `TRK-7`, адреса. Ссылайся на запись, "
            "которую дополняешь или опровергаешь; записи и задачи проверяются на существование"
        ),
        examples=[["TRK-42#3"]],
    ),
]

#: Типы, которые подшивает `add_entry`, — те, у которых нет нагрузки. Структурные записи
#: идут своими инструментами: у сводки, вопроса, ответа и вердикта нагрузка есть, и
#: принимать её свободным словарём значило бы отдать проверку формы агенту.
#:
#: Набор объявлен `Literal` прямо в аннотации, а не проверкой в теле инструмента: агент
#: видит допустимые значения в самой схеме и не узнаёт о них из отказа.
EntryTypeArg = Annotated[
    Literal[
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.REMARK,
        EntryType.NOTE,
    ],
    Field(
        description=(
            "Что случилось: `decision` — выбран вариант из нескольких, `attempt` — "
            "попытка и чем кончилась (провал ценнее успеха), `finding` — установленный "
            "факт с источником, `artifact` — указатель на результат, `remark` — "
            "замечание «вышло не то» к чужой сделанной работе, `note` — всё остальное, "
            "и это последний выбор. Сводка, вопрос, ответ, вердикт и резолюция "
            "подшиваются своими инструментами"
        ),
        examples=[EntryType.DECISION],
    ),
]
EntryTitleArg = Annotated[
    str,
    Field(
        description=(
            "Строка описи: по ней преемник решает, читать ли тело. Пиши «что», а не «как»"
        ),
        examples=["Выбран asyncpg вместо psycopg: нужен LISTEN без потока"],
    ),
]
VerdictOutcomeArg = Annotated[
    VerdictOutcome,
    Field(description="Исход проверки. Третьего состояния нет", examples=[VerdictOutcome.PASSED]),
]
EntryNosArg = Annotated[
    list[int] | None,
    Field(description="Только эти номера записей", examples=[[3, 12]]),
]
EntryTypesArg = Annotated[
    list[EntryType] | None,
    Field(description="Только записи этих типов", examples=[["decision", "attempt"]]),
]
AfterNoArg = Annotated[
    int | None,
    Field(description="Только записи после этого номера — что случилось с тех пор", examples=[12]),
]

# --- Сводка ---------------------------------------------------------------------------

SummaryDoneArg = Annotated[
    str,
    Field(
        description="Что сделано с прошлой сводки, со ссылками на артефакты",
        examples=["Разобрался, где сгорает номер задачи"],
    ),
]
SummaryRemainingArg = Annotated[
    str,
    Field(
        description="Что осталось до выхода задачи",
        examples=["Перенести выдачу номера после валидации"],
    ),
]
SummaryBlockersArg = Annotated[
    str,
    Field(
        description="Что мешает. Пиши «ничего», если ничего: пустым это поле быть не может",
        examples=["Ничего"],
    ),
]
SummaryNextStepArg = Annotated[
    str,
    Field(
        description=(
            "Одно конкретное действие, с которого начнёт преемник. Его первая строка "
            "становится заголовком записи в описи"
        ),
        examples=["Перенести вызов next_task_number в конец create_task"],
    ),
]

# --- Вопросы и вердикты ---------------------------------------------------------------

AddresseesArg = Annotated[
    list[str],
    Field(
        description=(
            "Имена участников из `list_participants`, хотя бы одно. Временного агента "
            "адресовать нельзя: строки в реестре у него нет"
        ),
        examples=[["owner"]],
    ),
]
BlockingArg = Annotated[
    bool,
    Field(
        description=(
            "Можно ли продолжать работу без ответа. Значения по умолчанию нет намеренно: "
            "это знаешь только ты. `true` — назначатель не возьмёт задачу, пока нет ответа"
        ),
        examples=[True],
    ),
]
QuestionNoArg = Annotated[
    int,
    Field(description="Номер записи `question` в этой же задаче", examples=[7]),
]
RemarkNoArg = Annotated[
    int,
    Field(description="Номер записи `remark` в этой же задаче", examples=[7]),
]
RemarkOutcomeArg = Annotated[
    RemarkOutcome,
    Field(
        description=(
            "Чем разобрано замечание: `fixed` — поправлено сразу, `accepted` — принято "
            "в работу отдельной задачей (тогда обязателен `task`), `needs_detail` — "
            "нужно уточнение, `declined` — менять не будем, причина в теле"
        ),
        examples=[RemarkOutcome.ACCEPTED],
    ),
]
ContinuationKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Ключ задачи, в которую ушла работа. Только с исходом `accepted` и там "
            "обязателен: «приняли» без адреса это обещание без ссылки"
        ),
        examples=["TRK-43"],
    ),
]
CheckNoArg = Annotated[
    int,
    Field(description="Номер обзорной проверки в списке задачи, с 1", examples=[3]),
]
EvidenceArg = Annotated[
    str,
    Field(
        description="Доказательство исхода: что запустил, что увидел, ссылка на материал",
        examples=["docker compose run --rm test: 214 passed"],
    ),
]

# --- Связи ----------------------------------------------------------------------------

LinkKindArg = Annotated[
    LinkKind,
    Field(
        description=(
            "Кем приходится задача из `key` задаче из `other`, а не наоборот: "
            "`link(key='TRK-1', kind='blocks', other='TRK-7')` — это «TRK-1 блокирует "
            "TRK-7». В карточке TRK-7 та же связь показана как `blocked_by TRK-1`"
        ),
        examples=[LinkKind.BLOCKED_BY],
    ),
]
OtherTaskKeyArg = Annotated[
    str,
    Field(description="Ключ задачи на другой стороне связи", examples=["TRK-7"]),
]

# --- Вложенные модели -----------------------------------------------------------------


class TaskSections(BaseModel):
    """Пять разделов задачи. Правятся только в `backlog`, дальше неизменяемы."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(default="", description="Зачем задача нужна и что изменится")
    context: str = Field(
        default="", description="Что уже есть, на что опираться, какие заметки читать"
    )
    constraints: str = Field(
        default="", description="Чего не делать, что не входит, чего нельзя менять"
    )
    output: str = Field(default="", description="Что должно существовать по завершении")
    checks: list[str] = Field(
        default_factory=list,
        description=(
            "Обзорные проверки по порядку, нумерация с 1. Каждую пиши так, чтобы её можно "
            "было провалить: что запустить и что должно получиться"
        ),
        examples=[["docker compose run --rm test: весь набор зелёный"]],
    )


SectionsArg = Annotated[
    TaskSections | None,
    Field(
        description=(
            "Пять разделов задачи. Без четырёх непустых разделов и хотя бы одной "
            "проверки задача не откроется; дописать их можно потом, пока она в `backlog`"
        )
    ),
]


class TaskChanges(BaseModel):
    """Что поменять в задаче. Непереданное поле не трогается.

    Статуса здесь нет — он меняется `transition`; ключа нет — он неизменяем. У
    `assignee` осмыслен `null`: он снимает исполнителя. У остальных полей `null` смысла
    не имеет, и схема его не пропустит.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = unset_field(description="Название задачи; только в `backlog`")
    description: str = unset_field(description="Описание задачи; только в `backlog`")
    goal: str = unset_field(description="Раздел «цель»; только в `backlog`")
    context: str = unset_field(description="Раздел «контекст»; только в `backlog`")
    constraints: str = unset_field(description="Раздел «ограничения»; только в `backlog`")
    output: str = unset_field(description="Раздел «выход»; только в `backlog`")
    checks: list[str] = unset_field(
        description="Обзорные проверки целиком, списком; только в `backlog`"
    )
    assignee: str | None = unset_field(
        description="Имя участника или метка временного агента; `null` снимает исполнителя",
        examples=["release_bot"],
    )
    priority: TaskPriority = unset_field(description="Приоритет", examples=[TaskPriority.HIGH])


# --- Отбор задач ----------------------------------------------------------------------

#: Что `search_tasks` просит по умолчанию. Узкий набор не оптимизация, а требование:
#: полная задача с пятью разделами на страницу в двадцать пять строк съедает контекст
#: ровно там, где агент выбирает, что брать.
#:
#: Признаки в набор входят: они короткие, а решение «брать ли задачу» без них не
#: принимается — иначе агент звал бы `get_task` на каждую строку выдачи, чтобы узнать,
#: не заблокирована ли она.
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = (
    "key",
    "title",
    "status",
    "assignee",
    "priority",
    FEATURES_FIELD,
)

QueryArg = Annotated[
    str | None,
    Field(
        description=(
            "Строка языка запросов: `queue: TRK and status: open and blocked: false and "
            "open_blocking_questions: 0`. Поля: "
            + ", ".join(f"`{name}`" for name in searchable_names())
            + ". Операторы `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` (вхождение), `!~`, `in`, "
            "`not in`; `empty()` находит задачи без значения. Условия связываются `and`, "
            "`or` и скобками. Ошибка разбора приходит с позицией символа"
        ),
        examples=["queue: TRK and status: open and blocked: false"],
    ),
]
SortArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Порядок, старший ключ первым; `-` в начале — по убыванию. Допустимы: "
            + ", ".join(f"`{name}`" for name in sortable_names())
        ),
        examples=[["-updated_at"]],
    ),
]
FieldsArg = Annotated[
    list[str],
    Field(
        description=(
            "Какие поля вернуть. Ключ приходит всегда. `features` отдаёт вычисляемые "
            "признаки строки: `blocked`, `open_questions`, `open_blocking_questions`, "
            "`open_remarks`, "
            "`last_summary_at` и `last_entry_at`. Пустой список означает «задачу целиком» — "
            "проси его, "
            "только когда действительно нужны разделы: они длинные"
        )
    ),
]

# Структурный отбор: по аргументу на поле. Значения одного аргумента складываются по
# «или», аргументы между собой — по «и». Тот же разбор значений, что и у языка, поэтому
# `assignee: ["empty()"]` и строка `assignee: empty()` значат буквально одно и то же:
# своя ветка условий здесь развела бы MCP с REST на первом же краевом случае.
QueuesArg = Annotated[
    list[str] | None,
    Field(description="Ключи очередей", examples=[["TRK"]]),
]
StatusesArg = Annotated[
    list[TaskStatus] | None,
    Field(description="Статусы задач", examples=[[TaskStatus.OPEN]]),
]
AssigneesArg = Annotated[
    list[str] | None,
    Field(
        description="Исполнители, точным совпадением; `empty()` находит задачи без исполнителя",
        examples=[["release_bot"]],
    ),
]
PrioritiesArg = Annotated[
    list[TaskPriority] | None,
    Field(description="Приоритеты", examples=[[TaskPriority.HIGH]]),
]
BlockedArg = Annotated[
    bool | None,
    Field(
        description=(
            "Есть ли у задачи `blocked_by` на задачу не в `done` и не в `cancelled`. "
            "Вход в `in_progress` при `true` отклоняется"
        )
    ),
]
OpenQuestionsArg = Annotated[
    int | None,
    Field(description="Ровно столько вопросов без ответа. Для диапазонов есть язык запросов"),
]
OpenBlockingQuestionsArg = Annotated[
    int | None,
    Field(description="Из них помеченных `blocking`; `0` означает «ничто не мешает»"),
]
OpenRemarksArg = Annotated[
    int | None,
    Field(description="Ровно столько замечаний без резолюции. Для диапазонов есть язык запросов"),
]
RemarksInWorkArg = Annotated[
    int | None,
    Field(
        description=(
            "Замечаний, принятых в работу, чья задача-продолжение ещё не закрыта: "
            "«разобрано, но работа не доделана»"
        )
    ),
]
TextArg = Annotated[
    str | None,
    Field(
        description="Подстрока в названии или описании, без учёта регистра",
        examples=["выдача ключей"],
    ),
]

# --- Лента --------------------------------------------------------------------------

AfterArg = Annotated[
    int,
    Field(
        ge=JOURNAL_START,
        description=(
            "Сквозной номер `seq`, после которого читать. 0 — с самого начала: записи "
            "постоянны, слишком старого курсора не бывает"
        ),
        examples=[1024],
    ),
]
JournalTaskArg = Annotated[
    str | None,
    Field(description="Только записи этой задачи", examples=["TRK-42"]),
]
JournalQueueArg = Annotated[
    str | None,
    Field(description="Только записи задач этой очереди", examples=["TRK"]),
]
TimeoutArg = Annotated[
    float,
    Field(
        description=(
            "Сколько секунд ждать первую подходящую запись, если хвост пуст; не больше "
            f"{MAX_WAIT_SECONDS:.0f}. 0 — ответить сразу. Пустой список по истечении "
            "ожидания означает «ничего не случилось» и ошибкой не является"
        ),
        examples=[30],
    ),
]

# --- Реестры ------------------------------------------------------------------------

ParticipantKindArg = Annotated[
    ParticipantKind,
    Field(description="Человек или постоянный агент", examples=[ParticipantKind.AGENT]),
]
ParticipantDescriptionArg = Annotated[
    str,
    Field(
        description="Кто это. Всё, что читающий дело узнает об авторе записи",
        examples=["Релизный бот, ведёт задачи выкладки"],
    ),
]
QueueTitleArg = Annotated[
    str,
    Field(description="Название очереди", examples=["Трекер"]),
]
QueueDescriptionArg = Annotated[
    str,
    Field(
        description=(
            "Общий контекст всех задач очереди в markdown: где лежит код, на какие "
            "документы смотреть, чего не делать"
        ),
        examples=["Бэкенд трекера. Код в `app/`, соглашения в `docs/CONVENTIONS.md`"],
    ),
]
# Отдельные аннотации для правки: `None` здесь означает «не передано». Осмысленного
# `null` ни у названия, ни у описания нет, поэтому третьего состояния и не нужно — в
# отличие от исполнителя задачи, который `null` как раз снимается.
QueueTitleChangeArg = Annotated[
    str | None,
    Field(description="Новое название. Не передавай, чтобы оставить прежнее", examples=["Трекер"]),
]
QueueDescriptionChangeArg = Annotated[
    str | None,
    Field(description="Новое описание. Не передавай, чтобы оставить прежнее"),
]
TaskStatusArg = Annotated[
    TaskStatus,
    Field(description="Целевой статус", examples=[TaskStatus.OPEN]),
]
