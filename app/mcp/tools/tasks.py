"""Инструменты по задачам: прочитать, найти, завести, поправить, перевести.

Тонкий слой: каждый инструмент разбирает аргументы, зовёт сценарий и превращает
результат в данные. Своей логики здесь нет и быть не может — иначе агент и человек
получили бы две разные системы поверх одной базы.
"""

from collections.abc import Sequence

from app.domain.links import LinkKind
from app.domain.search import Operator
from app.domain.tasks import DEFAULT_PRIORITY, CheckEdit, TaskPriority, TaskStatus
from app.mcp import views
from app.mcp.arguments import (
    DEFAULT_SEARCH_FIELDS,
    AssigneeArg,
    AssigneesArg,
    BlockedArg,
    ClosingEntriesArg,
    ClosingSummaryArg,
    ClosingVerdictsArg,
    CursorArg,
    FieldsArg,
    IdempotencyKeyArg,
    KeysArg,
    LimitArg,
    OpenBlockingQuestionsArg,
    OpenQuestionsArg,
    OpenRemarksArg,
    ParentFilterArg,
    ParentKeyArg,
    PrioritiesArg,
    PriorityArg,
    QueryArg,
    QueueKeyArg,
    QueuesArg,
    ReasonArg,
    RemarksInWorkArg,
    SectionsArg,
    SortArg,
    StatusesArg,
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
from app.mcp.toolset import FILING, IDEMPOTENT_TASK_UPDATE, READ_ONLY, Toolset
from app.services import case as case_service
from app.services import links as links_service
from app.services import queues as queues_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.search import StructuredTerm
from app.services.tasks import TaskMutation


def register(tools: Toolset) -> None:
    """Объявляет инструменты набора `task` по задачам."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def get_task(key: TaskKeyArg) -> views.TaskPackageView:
        """Returns everything about one task in a single call: card, parent and children,
        links from both sides, computed features, latest summary, open questions,
        unresolved remarks, case index and transition targets.

        `parent` and `children` are fields of their own and are absent from `links`,
        which holds `blocks`, `blocked_by` and `relates`, each named by this task's
        role. The parent's summary and decisions are in the parent's own case.

        The summary covers the case up to its own `no`; entries with a greater `no` are
        returned by `read_entries` with `after_no`. The index carries titles only, and
        entry bodies come from `read_entries`.

        A remark in `remarks` changes nothing in the task: it does not block
        `in_progress`, does not change the status and does not unlock the sections. It
        stays in `remarks` and in `open_remarks` until `resolve` gives it an outcome.

        `transitions` lists the targets of the transition table from the current status,
        not moves checked in advance: sections, summary, verdicts, blockers and children
        are checked by the `transition` call itself. Whether `in_progress` is open shows
        in the `blocked` feature.
        """
        async with runtime.call() as (session, actor):
            return views.task_package(
                await tasks_service.read_task_package(session, key, actor=actor)
            )

    @tools.tool(annotations=READ_ONLY)
    async def search_tasks(
        query: QueryArg = None,
        key: KeysArg = None,
        queue: QueuesArg = None,
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
    ) -> views.PageView[views.FoundTaskView]:
        """Searches tasks by a query language string, by separate conditions, or by both.

        Conditions from both sources combine with `and` and give the same result as one
        string of the same meaning; no condition at all selects every task. Rows are
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
                    queue=queue,
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

    @tools.tool(annotations=FILING, creating=True)
    async def create_task(
        queue: QueueKeyArg,
        title: TaskTitleArg,
        description: TaskDescriptionArg,
        sections: SectionsArg = None,
        parent: ParentKeyArg = None,
        assignee: AssigneeArg = None,
        priority: PriorityArg = DEFAULT_PRIORITY,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.MutationView:
        """Creates a task in `backlog`; a new task starts in no other status.

        With `parent`, the task is born as the parent's child in the same call: the link
        files `link_added` both in the new task's case and in the parent's case, and
        `parent_entry` in the response is the number of the parent's entry.

        A child task takes a part of the parent's work when the parent's output falls
        into separate results, its checks cannot all pass in one pass, the work does not
        fit one pass, or it depends on something that does not exist yet. These signs
        appear on entry into the parent and after each attempt.

        The response carries the key issued by the tracker. An empty title or
        description is refused with `task_fields_invalid`.
        """
        async with runtime.call() as (session, actor):
            # Всё, что может отказать, — до занятия ключа: отклонённый вызов не должен
            # тратить ключ. Ключи уезжают в отпечаток разрешёнными (`TRK`, а не `trk`):
            # адресация мягкая, и иначе повтор тем же ключом ответил бы конфликтом.
            resolved_queue = await queues_service.get_queue(session, queue)
            parent_task = None if parent is None else await tasks_service.get_task(session, parent)
            parts = sections or TaskSections()

            async def create() -> views.MutationView:
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
                    priority=priority,
                )
                parent_entry: int | None = None
                if parent_task is not None:
                    await links_service.add_link(
                        session, task, parent_task, actor=actor, kind=LinkKind.CHILD
                    )
                    # Номер записи в деле родителя читается из дела, тем же приёмом,
                    # что и у ребёнка ниже: общая блокировка изменений (`app/db/locks.py`,
                    # `lock_changes`) держит транзакцию монопольно до конца вызова, и
                    # никто другой не мог подшить запись в дело родителя между `add_link`
                    # и этим чтением — последняя запись его описи и есть только что
                    # поставленный `link_added`.
                    parent_index = await case_service.case_index(session, parent_task, actor=actor)
                    parent_entry = parent_index[-1].no
                # Номера подшитого читаются из дела, а не собираются по дороге:
                # `create_task` отдаёт задачу, `add_link` — связь, и номерами не
                # заведует ни один из них. У новой задачи в деле одна-две строки, и
                # прочитать их дешевле, чем протаскивать номера через две подписи
                # сценариев ради одного вызова MCP. Заодно ответ называет **всё**, что
                # подшилось, — включая `link_added` у ребёнка.
                filed = await case_service.case_index(session, task, actor=actor)
                return views.mutation(
                    TaskMutation(task=task, entries=tuple(item.no for item in filed)),
                    parent_entry=parent_entry,
                )

            return await Once.of(create_task, session, actor, idempotency_key).run(
                result=views.MutationView,
                request={
                    "queue": resolved_queue.key,
                    "title": title,
                    "description": description,
                    "sections": parts,
                    "parent": None if parent_task is None else parent_task.key,
                    "assignee": assignee,
                    "priority": priority,
                },
                build=create,
            )

    @tools.tool(annotations=IDEMPOTENT_TASK_UPDATE)
    async def update_task(
        key: TaskKeyArg,
        changes: TaskChanges,
        version: VersionArg = None,
    ) -> views.MutationView:
        """Changes the given fields of a task; fields left out stay as they are.

        Title, description and sections are fixed from `open` on. A task past `backlog`
        has them edited by a return to `backlog` through `transition` with a reason,
        this call, and a move forward again to `open` and `in_progress`.

        Each changed field files `section_changed` or `field_changed`, an assignee
        change files `assignee_changed`. An edit of one check names its number, and the
        earlier verdicts on that check become `outdated`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            given = changes.model_dump(exclude_unset=True)
            if "check" in given:
                # Аргумент приезжает словарём, а сценарий ждёт значение домена: перевод
                # стоит здесь, где кончается транспорт.
                given["check"] = CheckEdit(**given["check"])
            mutation = await tasks_service.update_task(
                session,
                task,
                actor=actor,
                changes=tasks_service.TaskChanges(**given),
                expected_version=version,
            )
            return views.mutation(mutation)

    @tools.tool(annotations=FILING)
    async def transition(
        key: TaskKeyArg,
        to: TaskStatusArg,
        reason: ReasonArg = None,
    ) -> views.MutationView:
        """Moves a task to another status along the fixed transition table.

        Refusals: leaving `in_progress` without a summary filed since the last entry
        into it — `summary_required`; entering `in_progress` without an assignee —
        `assignee_required`, by anyone but the assignee — `assignee_mismatch` (assignee
        and caller signature in `details`), with an open blocker — `task_blocked`;
        `open` with incomplete sections — `task_sections_incomplete`; `cancelled` with
        open children — `task_has_unclosed_children`; `done` —
        `closing_not_a_transition`, since a task is closed by `close_task`; a move
        outside the table — `transition_not_allowed`, the allowed targets in
        `details.allowed`.

        The tracker never moves a task into or out of `waiting` by itself: both moves
        are the caller's. Each entry into `in_progress`, from any status including
        `waiting`, starts a new pass of the task.

        `cancelled` takes no verdicts. It clears the `blocked` feature of the tasks this
        one blocked (`blocks`), with no entry in their cases.

        The response names the new status and version and the number of the filed
        `status_changed` entry.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            mutation = await tasks_service.transition_task(
                session, task, actor=actor, to=to, reason=reason
            )
            return views.mutation(mutation)

    @tools.tool(annotations=FILING, creating=True)
    async def close_task(
        key: TaskKeyArg,
        summary: ClosingSummaryArg,
        verdicts: ClosingVerdictsArg = None,
        entries: ClosingEntriesArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.ClosedTaskView:
        """Closes a task: files the given entries, then the verdicts, then the final
        summary, and moves the task to `done`, all in one transaction. It is the only
        way into `done`.

        A refusal of any part files nothing and leaves the status as it was. The exit
        conditions are checked after filing: a passing latest verdict on every review
        check within the current pass (`checks_not_passed`), closed children
        (`task_has_unclosed_children`), the task in `in_progress`
        (`transition_not_allowed`). An empty summary part is refused with
        `entry_fields_invalid`.

        For a parent task the final summary covers the whole work: the children's
        results are in their own closing summaries.

        Tasks this one blocked (`blocks`) lose the `blocked` feature, without an entry
        in their cases.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def close() -> views.ClosedTaskView:
                closure = await tasks_service.close_task(
                    session,
                    task,
                    actor=actor,
                    summary=case_service.SummaryFiling(
                        done=summary.done,
                        remaining=summary.remaining,
                        blockers=summary.blockers,
                        next_step=summary.next_step,
                        unmeasured=summary.unmeasured,
                    ),
                    verdicts=[
                        case_service.VerdictFiling(
                            check_no=item.check_no,
                            outcome=item.outcome,
                            evidence=item.evidence,
                        )
                        for item in verdicts or ()
                    ],
                    entries=[
                        case_service.EntryFiling(
                            type=item.type,
                            title=item.title,
                            body=item.body,
                            refs=item.refs or (),
                        )
                        for item in entries or ()
                    ],
                )
                return views.closed_task(closure)

            return await Once.of(close_task, session, actor, idempotency_key).run(
                result=views.ClosedTaskView,
                request={
                    "task": task.key,
                    "summary": summary,
                    "verdicts": verdicts,
                    "entries": entries,
                },
                build=close,
            )


def _terms(
    *,
    key: Sequence[str] | None,
    queue: Sequence[str] | None,
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
            ("queue", queue),
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
