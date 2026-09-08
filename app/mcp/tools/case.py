"""Инструменты по делу: прочитать записи и подшить свою.

Один инструмент — один вид записи. Составного «подшить и перевести» здесь нет: у
составного вызова отказ второй половины оставляет первую применённой, а агент видит одну
ошибку и не знает, что именно случилось.

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
from app.mcp.toolset import Toolset
from app.services import case as case_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет инструменты набора `task` по делу."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool()
    async def read_entries(
        key: TaskKeyArg,
        nos: EntryNosArg = None,
        types: EntryTypesArg = None,
        after_no: AfterNoArg = None,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.EntryView]:
        """Тела записей дела с нагрузкой, в порядке номеров.

        Фильтры складываются по «и»: `types=["summary"]` даёт все сводки, `after_no` —
        всё, что подшито после названной записи, вместе — всё подшитое после неё этих
        типов.
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

    @tools.tool(creating=True)
    async def add_summary(
        key: TaskKeyArg,
        done: SummaryDoneArg,
        remaining: SummaryRemainingArg,
        blockers: SummaryBlockersArg,
        next_step: SummaryNextStepArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.EntryView:
        """Подшивает сводку: справку при передаче дела.

        Запись немедленно видна в ленте и человеку в интерфейсе; будит ждущих
        `wait_journal`. Отказ: пустая часть — `entry_fields_invalid` со списком полей.

        Заголовок не принимается: им становится первая строка `next_step`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.EntryView:
                entry = await case_service.add_summary(
                    session,
                    task,
                    actor=actor,
                    done=done,
                    remaining=remaining,
                    blockers=blockers,
                    next_step=next_step,
                )
                return views.entry(entry, task_key=task.key)

            return await Once.of(add_summary, session, actor, idempotency_key).run(
                result=views.EntryView,
                request={
                    "task": task.key,
                    "done": done,
                    "remaining": remaining,
                    "blockers": blockers,
                    "next_step": next_step,
                },
                build=append,
            )

    @tools.tool(creating=True)
    async def add_entry(
        key: TaskKeyArg,
        type: EntryTypeArg,
        title: EntryTitleArg,
        body: EntryBodyArg = "",
        refs: EntryRefsArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.EntryView:
        """Подшивает запись без нагрузки: решение, попытку, находку, артефакт,
        замечание, заметку.

        Записи неизменяемы: правки и удаления нет ни здесь, ни в REST — есть только
        следующая запись со ссылкой на прежнюю в `refs`.

        Запись немедленно видна в ленте и человеку в интерфейсе; будит ждущих
        `wait_journal`. Отказ: тип не из списка, пустой заголовок, ссылка в никуда —
        `entry_fields_invalid` со списком полей.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.EntryView:
                entry = await case_service.add_entry(
                    session,
                    task,
                    actor=actor,
                    type=type,
                    title=title,
                    body=body,
                    refs=refs or (),
                )
                return views.entry(entry, task_key=task.key)

            return await Once.of(add_entry, session, actor, idempotency_key).run(
                result=views.EntryView,
                request={
                    "task": task.key,
                    "type": type,
                    "title": title,
                    "body": body,
                    "refs": refs,
                },
                build=append,
            )

    @tools.tool(creating=True)
    async def ask(
        key: TaskKeyArg,
        addressees: AddresseesArg,
        title: EntryTitleArg,
        blocking: BlockingArg,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.EntryView:
        """Задаёт вопрос участникам реестра. Доставки в трекере нет: адресат увидит
        вопрос, читая ленту или свою входящую.

        Вопрос открыт, пока в этой же задаче нет `answer` с его номером, и держит
        признак `open_questions`, а с `blocking` — и `open_blocking_questions`.

        Запись немедленно видна в ленте и человеку в интерфейсе; будит ждущих
        `wait_journal`. Отказ: адресата нет в реестре — `entry_fields_invalid`,
        `reason: unknown_participant`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.EntryView:
                entry = await case_service.ask(
                    session,
                    task,
                    actor=actor,
                    addressees=addressees,
                    title=title,
                    body=body,
                    blocking=blocking,
                )
                return views.entry(entry, task_key=task.key)

            return await Once.of(ask, session, actor, idempotency_key).run(
                result=views.EntryView,
                request={
                    "task": task.key,
                    "addressees": addressees,
                    "title": title,
                    "body": body,
                    "blocking": blocking,
                },
                build=append,
            )

    @tools.tool(creating=True)
    async def answer(
        key: TaskKeyArg,
        question_no: QuestionNoArg,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.EntryView:
        """Отвечает на вопрос той же задачи. Отвечает любой держатель токена `task`, в
        том числе в чужой задаче.

        Первый ответ закрывает вопрос, остальные дополняют; статус задачи ответ не
        меняет. Заголовок не принимается: он собирается из ссылки на вопрос.

        Запись немедленно видна в ленте и человеку в интерфейсе; будит ждущих
        `wait_journal`. Отказ: номер не указывает на `question` этой задачи —
        `entry_fields_invalid`, `reason: unknown_entry` или `not_a_question`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.EntryView:
                entry = await case_service.answer(
                    session, task, actor=actor, question_no=question_no, body=body
                )
                return views.entry(entry, task_key=task.key)

            return await Once.of(answer, session, actor, idempotency_key).run(
                result=views.EntryView,
                request={"task": task.key, "question_no": question_no, "body": body},
                build=append,
            )

    @tools.tool(creating=True)
    async def resolve(
        key: TaskKeyArg,
        remark_no: RemarkNoArg,
        outcome: RemarkOutcomeArg,
        task: ContinuationKeyArg = None,
        body: EntryBodyArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.EntryView:
        """Разбирает замечание к задаче: чем кончилось и куда ушла работа.

        Разбирает замечание любой исход, в том числе `needs_detail`: резолюция снимает
        замечание с признака `open_remarks`, а `accepted` держит его в `remarks_in_work`,
        пока задача-продолжение не закрыта. Заголовок не принимается: он собирается из
        ссылки на замечание и исхода.

        Запись немедленно видна в ленте и человеку в интерфейсе; будит ждущих
        `wait_journal`. Отказ: номер не указывает на `remark` этой задачи, `accepted`
        без `task` или `task` при другом исходе — `entry_fields_invalid`.
        """
        async with runtime.call() as (session, actor):
            entry_task = await tasks_service.get_task(session, key)

            async def append() -> views.EntryView:
                entry = await case_service.resolve(
                    session,
                    entry_task,
                    actor=actor,
                    remark_no=remark_no,
                    outcome=outcome,
                    continuation=task,
                    body=body,
                )
                return views.entry(entry, task_key=entry_task.key)

            return await Once.of(resolve, session, actor, idempotency_key).run(
                result=views.EntryView,
                request={
                    "task": entry_task.key,
                    "remark_no": remark_no,
                    "outcome": outcome,
                    "continuation": task,
                    "body": body,
                },
                build=append,
            )

    @tools.tool(creating=True)
    async def add_verdict(
        key: TaskKeyArg,
        check_no: CheckNoArg,
        outcome: VerdictOutcomeArg,
        evidence: EvidenceArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.EntryView:
        """Подшивает исход одной обзорной проверки.

        `in_progress → done` смотрит на последний вердикт по каждой проверке и считает
        только вердикты этого захода — подшитые после последнего входа в `in_progress`.
        Вердикты прошлых заходов остаются в деле, но в счёт не идут.

        Запись немедленно видна в ленте и человеку в интерфейсе; будит ждущих
        `wait_journal`. Отказ: проверки с таким номером в задаче нет —
        `entry_fields_invalid`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)

            async def append() -> views.EntryView:
                entry = await case_service.add_verdict(
                    session,
                    task,
                    actor=actor,
                    check_no=check_no,
                    outcome=outcome,
                    evidence=evidence,
                )
                return views.entry(entry, task_key=task.key)

            return await Once.of(add_verdict, session, actor, idempotency_key).run(
                result=views.EntryView,
                request={
                    "task": task.key,
                    "check_no": check_no,
                    "outcome": outcome,
                    "evidence": evidence,
                },
                build=append,
            )
