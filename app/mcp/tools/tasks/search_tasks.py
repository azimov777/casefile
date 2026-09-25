"""Инструмент `search_tasks`: отбор задач языком запросов, отдельными условиями или тем и другим.

## Обрезка длинного текста

Единственное место обрезки — выдача `search_tasks` (`TRACKER_MCP_TEXT_LIMIT`): только там
в одном ответе может оказаться два десятка описаний и разделов. Обрезка объявлена рядом
со значением (`<поле>_truncated`, `<поле>_length`), а полный текст — один вызов
`get_task`. Тела записей дела не обрезаются нигде: их запрашивают по номеру, и взять
полный текст было бы больше неоткуда.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from app.domain.query_language import QUERY_EXAMPLES, QUERY_RIGHT_SHAPE, QUERY_WRONG_SHAPE
from app.domain.search import (
    FEATURES_FIELD,
    MANDATORY_FIELD,
    PARENT_FIELD,
    Operator,
    searchable_names,
    selectable_names,
    sortable_names,
)
from app.domain.tasks import TaskParent, TaskPriority, TaskStatus, feature_names
from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.enums import TaskPrioritySchema, TaskStatusSchema
from app.mcp.tools.tasks.views import FeaturesView, features, task
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import AuthorView, PageView, ProjectRefView, page, project_ref
from app.services import search as search_service
from app.services.search import FoundTask, StructuredTerm

#: Что `search_tasks` просит по умолчанию. Узкий набор не оптимизация, а требование:
#: полная задача с пятью разделами на страницу в двадцать пять строк съедает контекст
#: ровно там, где агент выбирает, что брать.
#:
#: Признаки в набор входят: они короткие, а решение «брать ли задачу» без них не
#: принимается — иначе агент звал бы `get_task` на каждую строку выдачи, чтобы узнать,
#: не заблокирована ли она.
#:
#: Родитель входит по той же причине: без него агент не видит, к какой программе
#: относится задача, и читает `get_task` построчно. Цена замерена (TRK-95#7, тогда ещё
#: списком): у задачи верхнего уровня — `"parent":null`, у ребёнка — ключ и название.
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = (
    "key",
    "title",
    "status",
    "assignee",
    "priority",
    FEATURES_FIELD,
    PARENT_FIELD,
)

QueryArg = Annotated[
    str | None,
    Field(
        description=(
            "Query language string. A condition is written `name: [operator] values`: the "
            "operator stands **after** the colon, unlike SQL — "
            f"`{QUERY_RIGHT_SHAPE}`, not `{QUERY_WRONG_SHAPE}`. Parentheses group "
            "conditions, not values.\n\n"
            "Without an operator a condition means equality, and comma-separated values "
            "mean membership: `status: open, in_progress` equals "
            f"`{QUERY_RIGHT_SHAPE}`.\n\n"
            "Fields: " + ", ".join(f"`{name}`" for name in searchable_names()) + ". "
            "Operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` (substring), `!~`, `in`, "
            "`not in`; `empty()` matches tasks without a value. Conditions combine with "
            "`and` and `or`.\n\n"
            "Examples:\n"
            + "\n".join(f"- `{example}`" for example in QUERY_EXAMPLES)
            + "\n\nA string that does not parse is refused with `invalid_search_query` "
            "and the character position, plus the correct form in `details.hint` where "
            "the error position determines it"
        ),
        examples=list(QUERY_EXAMPLES),
    ),
]

SortArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Sort order, most significant key first; a leading `-` sorts descending. "
            "Allowed: " + ", ".join(f"`{name}`" for name in sortable_names())
        ),
        examples=[["-updated_at"]],
    ),
]

# Домен значений называется целиком и собирается из домена, а не переписывается словами:
# описание и `details.allowed` отказа обязаны быть одним списком в одном порядке, иначе
# агент решит, что набор зависит от вызова. Место здесь дорогое — описание `search_tasks`
# самое длинное в установке, — поэтому названы имена и ничего больше.
FieldsArg = Annotated[
    list[str],
    Field(
        description=(
            "Fields to return: "
            + ", ".join(f"`{name}`" for name in selectable_names())
            + ". The key always comes back; an empty list returns whole tasks. "
            "`features` brings the computed features: "
            + ", ".join(f"`{name}`" for name in feature_names())
            + ". `parent` is the parent's key and title, or `null`"
        )
    ),
]

# Структурный отбор: по аргументу на поле. Значения одного аргумента складываются по
# «или», аргументы между собой — по «и». Тот же разбор значений, что и у языка, поэтому
# `assignee: ["empty()"]` и строка `assignee: empty()` значат буквально одно и то же:
# своя ветка условий здесь развела бы MCP с REST на первом же краевом случае.
KeysArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Task keys: several named tasks in one call. An unknown key is refused with "
            "`search_value_invalid`, `reason: task_not_found`, rather than left out"
        ),
        examples=[["TRK-42", "TRK-43"]],
    ),
]

ProjectsArg = Annotated[list[str] | None, Field(description="Project keys", examples=[["TRK"]])]


StatusesArg = Annotated[list[TaskStatusSchema] | None, Field(description="Task statuses")]


AssigneesArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Assignee names, exact match; `empty()` matches tasks without an assignee. A "
            "name covers every session signed with it: no value selects the tasks of one "
            "session"
        )
    ),
]

ParentFilterArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Parent task keys: their **direct** children, one level down. `empty()` "
            "matches tasks without a parent, the top level of a project. An unknown key is "
            "refused rather than read as «no children»"
        ),
        examples=[["TRK-7"]],
    ),
]

PrioritiesArg = Annotated[list[TaskPrioritySchema] | None, Field(description="Priorities")]


BlockedArg = Annotated[
    bool | None,
    Field(
        description=(
            "Whether the task has `blocked_by` on a task that is neither `done` nor `cancelled`"
        )
    ),
]

OpenQuestionsArg = Annotated[
    int | None,
    Field(description="Exact number of unanswered questions; ranges go in `query`"),
]

OpenBlockingQuestionsArg = Annotated[
    int | None,
    Field(description="Exact number of unanswered `blocking` questions; `0` means none blocks"),
]

OpenRemarksArg = Annotated[
    int | None,
    Field(description="Exact number of unresolved remarks; ranges go in `query`"),
]

RemarksInWorkArg = Annotated[
    int | None,
    Field(
        description=(
            "Number of remarks resolved as `accepted` whose continuation task is not closed yet"
        )
    ),
]

TextArg = Annotated[
    str | None,
    Field(description="Substring of the title or description, case-insensitive"),
]

#: Поля задачи, которые бывают длинными: описание и пять разделов. Обрезаются только они
#: и только в выдаче поиска.
LONG_TEXT_FIELDS: frozenset[str] = frozenset(
    {"description", "goal", "context", "constraints", "output"}
)


# Родитель задачи в строке выдачи: ключ и название (`CONCEPT.md`, 4.4).
class ParentView(BaseModel):
    """Parent task: key and title."""

    key: str
    title: str


def parent_row(value: TaskParent) -> ParentView:
    """Родитель задачи в строке выдачи: ключ и название (`CONCEPT.md`, 4.4)."""
    return ParentView(key=value.key, title=value.title)


# Строка выдачи поиска: карточка задачи, у которой любое поле может отсутствовать.
#
# Единственная модель слоя с необязательными полями, и это не послабление типизации, а
# её предмет. Список умеет отдавать подмножество полей (`fields`), и схема обязана
# честно это показывать — ровно так же, как `TaskSearchRead` в REST.
#
# Отсюда же сериализатор ниже. SDK сворачивает результат вызовом
# `model_dump(mode="json")` — **без** `exclude_unset`, — и незапрошенное поле приезжало
# бы агенту как `null`. Это не то же самое, что «поля нет»: пакет обязан совпадать с
# ответом REST поле в поле, а тот отдаётся с `response_model_exclude_unset`.
#
# Схему сериализатор не портит, и это проверено: SDK строит `outputSchema` через
# `TypeAdapter(...).json_schema()`, у которого режим по умолчанию — **валидация**, а
# обёрточный сериализатор действует только на схему сериализации. У FastAPI режим
# противоположный, поэтому предупреждение заметки `docs/notes/api.md` («Отбросить
# пустые поля в ответе — значит потерять схему у клиента») сюда не переносится.
class FoundTaskView(BaseModel):
    """Search result row: the requested fields of one task."""

    key: str
    id: str | None = None
    previous_keys: list[str] | None = None
    project: ProjectRefView | None = None
    title: str | None = None
    description: str | None = None
    goal: str | None = None
    context: str | None = None
    constraints: str | None = None
    output: str | None = None
    checks: list[str] | None = None
    status: TaskStatusSchema | None = None
    assignee: str | None = None
    priority: TaskPrioritySchema | None = None
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
    # Проект строкой выдачи — ключ и название, без описания карточки: одно и то же
    # описание на каждой строке стоило бы контекста без новой информации.
    payload["project"] = project_ref(found.task.project)
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


def register(tools: Toolset) -> None:
    """Объявляет `search_tasks` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def search_tasks(
        query: QueryArg = None,
        key: KeysArg = None,
        project: ProjectsArg = None,
        parent: ParentFilterArg = None,
        status: StatusesArg = None,
        assignee: AssigneesArg = None,
        priority: PrioritiesArg = None,
        blocked: BlockedArg = None,
        open_questions: OpenQuestionsArg = None,
        open_blocking_questions: OpenBlockingQuestionsArg = None,
        open_remarks: OpenRemarksArg = None,
        remarks_in_work: RemarksInWorkArg = None,
        text: TextArg = None,
        sort: SortArg = None,
        fields: FieldsArg = DEFAULT_SEARCH_FIELDS,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[FoundTaskView]:
        """Searches tasks by a query language string, by separate conditions, or by both.

        Conditions from both sources combine with `and` and give the same result as one
        string of the same meaning; no condition at all selects every task of the
        projects that are not archived. A task of an archived project is found only when
        the search names it with `=` or `in`: its project in `project`, the task itself in
        `key`, or its parent in `parent`. Rows are
        ordered by `sort`, by key when it is left out. A long text is cut at the
        installation limit and marked by `<field>_truncated` and `<field>_length`; one
        task in full, with its case and links, is returned by `get_task`.

        An unknown field, operator or value is refused with `search_field_unknown`,
        `search_operator_not_supported` or `search_value_invalid`, the allowed values
        listed in `details`.
        """
        async with runtime.call() as (session, actor):
            outcome = await search_service.search_tasks(
                session,
                actor=actor,
                query=query,
                structured=_terms(
                    key=key,
                    project=project,
                    parent=parent,
                    status=status,
                    assignee=assignee,
                    priority=priority,
                    blocked=blocked,
                    open_questions=open_questions,
                    open_blocking_questions=open_blocking_questions,
                    open_remarks=open_remarks,
                    remarks_in_work=remarks_in_work,
                    text=text,
                ),
                sort=sort or (),
                fields=fields,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return page(
                (
                    found_task(
                        found,
                        fields=outcome.resolved.fields,
                        text_limit=settings.mcp_text_limit,
                    )
                    for found in outcome.page.items
                ),
                next_cursor=outcome.page.next_cursor,
            )


def _terms(
    *,
    key: Sequence[str] | None,
    project: Sequence[str] | None,
    parent: Sequence[str] | None,
    status: Sequence[TaskStatus] | None,
    assignee: Sequence[str] | None,
    priority: Sequence[TaskPriority] | None,
    blocked: bool | None,
    open_questions: int | None,
    open_blocking_questions: int | None,
    open_remarks: int | None,
    remarks_in_work: int | None,
    text: str | None,
) -> list[StructuredTerm]:
    """Аргументы отбора → условия фильтра. Одно место перевода, как `TaskFilters` в REST.

    Своего разбора значений здесь нет: он общий с языком запросов и живёт в
    `app/services/search.py`. Отсюда уезжают только имена полей и оператор, и оба
    совпадают с REST — иначе `assignee: ["empty()"]` и строка `assignee: empty()`
    однажды ответили бы по-разному на один и тот же по смыслу вопрос.

    `None` означает «не отбирать по этому полю»; пустой список — тоже, иначе снятая в
    интерфейсе галочка обнуляла бы выдачу. Перечисления отдаются строками: значение
    уезжает в тот же разбор, что и значение языка.
    """
    terms: list[StructuredTerm] = [
        StructuredTerm(name=name, values=values)
        for name, values in (
            ("key", key),
            ("project", project),
            ("parent", parent),
            ("status", None if status is None else [item.value for item in status]),
            ("assignee", assignee),
            ("priority", None if priority is None else [item.value for item in priority]),
        )
        if values
    ]
    terms.extend(
        StructuredTerm(name=name, values=[value])
        for name, value in (
            ("blocked", blocked),
            ("open_questions", open_questions),
            ("open_blocking_questions", open_blocking_questions),
            ("open_remarks", open_remarks),
            ("remarks_in_work", remarks_in_work),
        )
        if value is not None
    )
    if text is not None:
        terms.append(StructuredTerm(name="text", values=[text], operator=Operator.CONTAINS))
    return terms
