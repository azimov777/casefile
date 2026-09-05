"""Инструменты по задачам: прочитать, найти, завести, поправить, перевести.

Тонкий слой: каждый инструмент разбирает аргументы, зовёт сценарий и превращает
результат в данные. Своей логики здесь нет и быть не может — иначе агент и человек
получили бы две разные системы поверх одной базы.
"""

from collections.abc import Sequence
from typing import Any

from app.domain.links import LinkKind
from app.domain.search import Operator
from app.domain.tasks import DEFAULT_PRIORITY, TaskPriority, TaskStatus
from app.mcp import views
from app.mcp.arguments import (
    DEFAULT_SEARCH_FIELDS,
    AssigneeArg,
    AssigneesArg,
    BlockedArg,
    CursorArg,
    FieldsArg,
    IdempotencyKeyArg,
    LimitArg,
    OpenBlockingQuestionsArg,
    OpenQuestionsArg,
    ParentKeyArg,
    PrioritiesArg,
    PriorityArg,
    QueryArg,
    QueueKeyArg,
    QueuesArg,
    ReasonArg,
    SectionsArg,
    SortArg,
    StatusesArg,
    TagFilterArg,
    TagsArg,
    TaskChanges,
    TaskDescriptionArg,
    TaskKeyArg,
    TaskSections,
    TaskStatusArg,
    TaskTitleArg,
    TextArg,
    VersionArg,
)
from app.mcp.idempotency import Once
from app.mcp.toolset import Toolset
from app.services import links as links_service
from app.services import queues as queues_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.search import StructuredTerm


def register(tools: Toolset) -> None:
    """Объявляет инструменты набора `task` по задачам."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool()
    async def get_task(key: TaskKeyArg) -> dict[str, Any]:
        """Всё о задаче одним вызовом: карточка, связи, признаки, последняя сводка,
        открытые вопросы, опись дела и переходы по таблице статусов.

        Точка входа. Прочитай сводку и опись, выбери по заголовкам, что читать целиком,
        и возьми тела через `read_entries` — обычно это `decision` и провальные
        `attempt`, чтобы не пересматривать решённое и не повторять тупики.

        `transitions` это цели по таблице из текущего статуса, а не ходы, которые
        пройдут сейчас: разделы, сводку, вердикты, блокеры и детей трекер проверяет в
        момент `transition`. Пустят ли в `in_progress`, говорит признак `blocked`.
        """
        async with runtime.call() as (session, actor):
            return views.task_package(
                await tasks_service.read_task_package(session, key, actor=actor)
            )

    @tools.tool()
    async def search_tasks(
        query: QueryArg = None,
        queue: QueuesArg = None,
        status: StatusesArg = None,
        assignee: AssigneesArg = None,
        tags: TagFilterArg = None,
        priority: PrioritiesArg = None,
        blocked: BlockedArg = None,
        open_questions: OpenQuestionsArg = None,
        open_blocking_questions: OpenBlockingQuestionsArg = None,
        text: TextArg = None,
        sort: SortArg = None,
        fields: FieldsArg = DEFAULT_SEARCH_FIELDS,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> dict[str, Any]:
        """Ищет задачи строкой языка запросов, отдельными условиями или всем сразу.

        Условия из обоих источников складываются по «и» и дают тот же результат, что
        одна строка того же смысла. Отбор без условий законен: это «все задачи».

        Так собирается контекст перед вопросом: решения соседей по родителю и по очереди
        чаще всего уже содержат ответ.
        """
        async with runtime.call() as (session, actor):
            outcome = await search_service.search_tasks(
                session,
                actor=actor,
                query=query,
                structured=_terms(
                    queue=queue,
                    status=status,
                    assignee=assignee,
                    tags=tags,
                    priority=priority,
                    blocked=blocked,
                    open_questions=open_questions,
                    open_blocking_questions=open_blocking_questions,
                    text=text,
                ),
                sort=sort or (),
                fields=fields,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (
                    views.found_task(
                        found,
                        fields=outcome.resolved.fields,
                        text_limit=settings.mcp_text_limit,
                    )
                    for found in outcome.page.items
                ),
                next_cursor=outcome.page.next_cursor,
            )

    @tools.tool(creating=True)
    async def create_task(
        queue: QueueKeyArg,
        title: TaskTitleArg,
        description: TaskDescriptionArg,
        sections: SectionsArg = None,
        parent: ParentKeyArg = None,
        assignee: AssigneeArg = None,
        tags: TagsArg = None,
        priority: PriorityArg = DEFAULT_PRIORITY,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> dict[str, Any]:
        """Заводит задачу в `backlog`. Статус не принимается: новая задача рождается там.

        Заполни все пять разделов сразу, если можешь: без четырёх непустых разделов и
        хотя бы одной проверки задача не откроется. Проверки пиши так, чтобы их можно
        было провалить.

        `parent` делает задачу ребёнком названной — ребёнок рождается со ссылкой на
        родителя, это одно действие, а не два. Родитель не закроется в `done`, пока дети
        не закрыты.
        """
        async with runtime.call() as (session, actor):
            # Всё, что может отказать, — до занятия ключа: отклонённый вызов не должен
            # тратить ключ. Ключи уезжают в отпечаток разрешёнными (`TRK`, а не `trk`):
            # адресация мягкая, и иначе повтор тем же ключом ответил бы конфликтом.
            resolved_queue = await queues_service.get_queue(session, queue)
            parent_task = None if parent is None else await tasks_service.get_task(session, parent)
            parts = sections or TaskSections()

            async def create() -> dict[str, Any]:
                task = await tasks_service.create_task(
                    session,
                    actor=actor,
                    queue=resolved_queue,
                    title=title,
                    description=description,
                    goal=parts.goal,
                    context=parts.context,
                    constraints=parts.constraints,
                    output=parts.output,
                    checks=parts.checks,
                    assignee=assignee,
                    tags=tags or (),
                    priority=priority,
                )
                if parent_task is not None:
                    await links_service.add_link(
                        session, task, parent_task, actor=actor, kind=LinkKind.CHILD
                    )
                return views.task(task)

            return await Once.of(create_task, session, actor, idempotency_key).run(
                request={
                    "queue": resolved_queue.key,
                    "title": title,
                    "description": description,
                    "sections": parts,
                    "parent": None if parent_task is None else parent_task.key,
                    "assignee": assignee,
                    "tags": tags,
                    "priority": priority,
                },
                build=create,
            )

    @tools.tool()
    async def update_task(
        key: TaskKeyArg,
        changes: TaskChanges,
        version: VersionArg = None,
    ) -> dict[str, Any]:
        """Меняет переданные поля задачи; непереданное не трогает.

        Название, описание и пять разделов правятся только в `backlog`. Выяснилось в
        работе, что ограничения или выход неверны — сначала сводка, потом
        `transition(key, "backlog", reason=...)`, потом правка: изменённый контракт
        заслуживает страницы в деле, поэтому путь намеренно не короткий.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            mutation = await tasks_service.update_task(
                session,
                task,
                actor=actor,
                changes=tasks_service.TaskChanges(**changes.model_dump(exclude_unset=True)),
                expected_version=version,
            )
            return views.task(mutation.task)

    @tools.tool()
    async def transition(
        key: TaskKeyArg,
        to: TaskStatusArg,
        reason: ReasonArg = None,
    ) -> dict[str, Any]:
        """Переводит задачу в другой статус по зашитой таблице переходов.

        Трекер откажет, если переход портит журнал: выход из `in_progress` без сводки,
        подшитой после последнего входа в него; `review → done` без положительного
        последнего вердикта по каждой проверке, подшитого после последнего входа в
        `review`; вход в `in_progress` при открытом блокере; `done` при незакрытых
        детях. В отказе — что именно мешает.

        Этих проверок нет в `transitions` у `get_task`: там таблица переходов.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            mutation = await tasks_service.transition_task(
                session, task, actor=actor, to=to, reason=reason
            )
            return views.task(mutation.task)


def _terms(
    *,
    queue: Sequence[str] | None,
    status: Sequence[TaskStatus] | None,
    assignee: Sequence[str] | None,
    tags: Sequence[str] | None,
    priority: Sequence[TaskPriority] | None,
    blocked: bool | None,
    open_questions: int | None,
    open_blocking_questions: int | None,
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
            ("queue", queue),
            ("status", None if status is None else [item.value for item in status]),
            ("assignee", assignee),
            ("tags", tags),
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
        )
        if value is not None
    )
    if text is not None:
        terms.append(StructuredTerm(name="text", values=[text], operator=Operator.CONTAINS))
    return terms
