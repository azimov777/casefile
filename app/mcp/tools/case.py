"""Инструменты по делу: прочитать записи и подшить свою.

Один инструмент — один вид записи. Составного «подшить и перевести» здесь нет: у
составного вызова отказ второй половины оставляет первую применённой, а агент видит одну
ошибку и не знает, что именно случилось.

Исключение ровно одно, и оно не отсюда: закрытие задачи (`app/mcp/tools/tasks.py`,
`close_task`) подшивает вердикты, записи и сводку и переводит задачу в `done` одной
транзакцией. Довод выше его не запрещает, а объясняет: там половин не бывает — отказ
любой части не оставляет ни одной записи, и ошибка приходит одна, потому что действие
одно.

Каждый инструмент зовёт **свою обёртку** сценария (`app/services/case.py`,
`add_summary`, `ask`, `answer`, `add_verdict`, `add_entry`), а не собирает нагрузку сам:
форма нагрузки — знание домена, и второй его копией в слое MCP она разошлась бы с
первой на первой же правке.
"""

from app.mcp import views
from app.mcp.arguments import (
    AddresseesArg,
    AfterNoArg,
    BlockingArg,
    CheckNoArg,
    ContinuationKeyArg,
    CursorArg,
    EntryBodyArg,
    EntryNosArg,
    EntryRefsArg,
    EntryTitleArg,
    EntryTypeArg,
    EntryTypesArg,
    EvidenceArg,
    IdempotencyKeyArg,
    LimitArg,
    QuestionNoArg,
    RemarkNoArg,
    RemarkOutcomeArg,
    SummaryBlockersArg,
    SummaryDoneArg,
    SummaryNextStepArg,
    SummaryRemainingArg,
    TaskKeyArg,
    VerdictOutcomeArg,
)
from app.mcp.idempotency import Once
from app.mcp.toolset import FILING, READ_ONLY, Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет инструменты набора `task` по делу."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def read_entries(
        key: TaskKeyArg,
        nos: EntryNosArg = None,
        types: EntryTypesArg = None,
        after_no: AfterNoArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.EntryView]:
        """Returns entry bodies of one task's case, with payload, in number order.

        Filters combine with `and`: `types=["summary"]` gives every summary, `after_no`
        everything filed after the named entry, and both together the entries of those
        types filed after it. `decision` and `attempt` entries hold the choices already
        made and the attempts already tried, failed ones included.

        Entries of many cases in one stream, with a wait for new ones, come from
        `wait_journal`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            page = await case_service.list_entries(
                session,
                task,
                actor=actor,
                nos=nos,
                types=types,
                after_no=after_no,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (views.entry(item, task_key=task.key) for item in page.items),
                next_cursor=page.next_cursor,
            )

    @tools.tool(annotations=FILING, creating=True)
    async def add_summary(
        key: TaskKeyArg,
        done: SummaryDoneArg,
        remaining: SummaryRemainingArg,
        blockers: SummaryBlockersArg,
        next_step: SummaryNextStepArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.AppendedEntryView:
        """Files a summary: the handover note of a case, in four parts, none of them empty
        (`entry_fields_invalid` lists the empty ones).

        A summary follows each significant step: a decision made, a finished part of the
        work, a failure that changes the plan, any point where a colleague would need an
        explanation of where the work stands.

        Its index title is the first line of `done`, returned in the response. The final
        summary, with `unmeasured`, is filed by `close_task`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.AppendedEntryView:
                entry = await case_service.add_summary(
                    session,
                    task,
                    actor=actor,
                    done=done,
                    remaining=remaining,
                    blockers=blockers,
                    next_step=next_step,
                )
                return views.appended_entry(entry, task_key=task.key)

            return await Once.of(add_summary, session, actor, idempotency_key).run(
                result=views.AppendedEntryView,
                request={
                    "task": task.key,
                    "done": done,
                    "remaining": remaining,
                    "blockers": blockers,
                    "next_step": next_step,
                },
                build=append,
            )

    @tools.tool(annotations=FILING, creating=True)
    async def add_entry(
        key: TaskKeyArg,
        type: EntryTypeArg,
        title: EntryTitleArg,
        body: EntryBodyArg = "",
        refs: EntryRefsArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.AppendedEntryView:
        """Files an entry without payload: a decision, attempt, finding, artifact, remark
        or note.

        Entries are immutable: no call edits or deletes one, and a mistaken entry is
        corrected by a new entry that references it in `refs`. Summaries, questions,
        answers, verdicts and resolutions have their own tools: `add_summary`, `ask`,
        `answer`, `add_verdict`, `resolve`.

        An empty title is refused with `entry_fields_invalid`, which lists the fields.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.AppendedEntryView:
                entry = await case_service.add_entry(
                    session,
                    task,
                    actor=actor,
                    type=type,
                    title=title,
                    body=body,
                    refs=refs or (),
                )
                return views.appended_entry(entry, task_key=task.key)

            return await Once.of(add_entry, session, actor, idempotency_key).run(
                result=views.AppendedEntryView,
                request={
                    "task": task.key,
                    "type": type,
                    "title": title,
                    "body": body,
                    "refs": refs,
                },
                build=append,
            )

    @tools.tool(annotations=FILING, creating=True)
    async def ask(
        key: TaskKeyArg,
        addressees: AddresseesArg,
        title: EntryTitleArg,
        blocking: BlockingArg,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.AppendedEntryView:
        """Files a question to registry participants. The tracker delivers nothing: an
        addressee sees the question when reading the feed or their inbox.

        A question stays open until an `answer` with its number is filed in the same
        task; it counts toward `open_questions`, and with `blocking` toward
        `open_blocking_questions`.

        What the cases of the parent, its ancestors and sibling tasks already record is
        readable through `get_task` and `read_entries`, without a question.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.AppendedEntryView:
                entry = await case_service.ask(
                    session,
                    task,
                    actor=actor,
                    addressees=addressees,
                    title=title,
                    body=body,
                    blocking=blocking,
                )
                return views.appended_entry(entry, task_key=task.key)

            return await Once.of(ask, session, actor, idempotency_key).run(
                result=views.AppendedEntryView,
                request={
                    "task": task.key,
                    "addressees": addressees,
                    "title": title,
                    "body": body,
                    "blocking": blocking,
                },
                build=append,
            )

    @tools.tool(annotations=FILING, creating=True)
    async def answer(
        key: TaskKeyArg,
        question_no: QuestionNoArg,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.AppendedEntryView:
        """Answers a question of the same task. Any holder of a `task` token answers, in
        any task.

        The first answer closes the question and later ones add to it; neither a
        question nor an answer changes the task status. The tracker builds the title
        from the question reference.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.AppendedEntryView:
                entry = await case_service.answer(
                    session, task, actor=actor, question_no=question_no, body=body
                )
                return views.appended_entry(entry, task_key=task.key)

            return await Once.of(answer, session, actor, idempotency_key).run(
                result=views.AppendedEntryView,
                request={"task": task.key, "question_no": question_no, "body": body},
                build=append,
            )

    @tools.tool(annotations=FILING, creating=True)
    async def resolve(
        key: TaskKeyArg,
        remark_no: RemarkNoArg,
        outcome: RemarkOutcomeArg,
        task: ContinuationKeyArg = None,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.AppendedEntryView:
        """Resolves a remark on a task: its outcome and where the work went.

        Any outcome resolves the remark, `needs_detail` included: the resolution removes
        it from `open_remarks`, while `accepted` keeps it in `remarks_in_work` until the
        continuation task is closed. Its title is made of the remark reference and the
        outcome.
        """
        async with runtime.call() as (session, actor):
            entry_task = await tasks_service.get_task(session, key)

            async def append() -> views.AppendedEntryView:
                entry = await case_service.resolve(
                    session,
                    entry_task,
                    actor=actor,
                    remark_no=remark_no,
                    outcome=outcome,
                    continuation=task,
                    body=body,
                )
                return views.appended_entry(entry, task_key=entry_task.key)

            return await Once.of(resolve, session, actor, idempotency_key).run(
                result=views.AppendedEntryView,
                request={
                    "task": entry_task.key,
                    "remark_no": remark_no,
                    "outcome": outcome,
                    "continuation": task,
                    "body": body,
                },
                build=append,
            )

    @tools.tool(annotations=FILING, creating=True)
    async def add_verdict(
        key: TaskKeyArg,
        check_no: CheckNoArg,
        outcome: VerdictOutcomeArg,
        evidence: EvidenceArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.AppendedEntryView:
        """Files the outcome of one review check, as run by the task's assignee within the
        current pass.

        A pass starts with each entry into `in_progress`, a return from `waiting`
        included. Only verdicts of the current pass count for closing, and the latest
        verdict on a check replaces the earlier ones: a `failed` verdict is filed when
        it happens, like a `passed` one. Verdicts of earlier passes stay in the case
        without counting. `close_task` also takes verdicts, together with the closing.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.AppendedEntryView:
                entry = await case_service.add_verdict(
                    session,
                    task,
                    actor=actor,
                    check_no=check_no,
                    outcome=outcome,
                    evidence=evidence,
                )
                return views.appended_entry(entry, task_key=task.key)

            return await Once.of(add_verdict, session, actor, idempotency_key).run(
                result=views.AppendedEntryView,
                request={
                    "task": task.key,
                    "check_no": check_no,
                    "outcome": outcome,
                    "evidence": evidence,
                },
                build=append,
            )
