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

        Читай точечно: опись из `get_task` показывает заголовки, а сюда приходи за тем,
        что решил прочитать целиком. Фильтры складываются: `types=["summary"]` даёт все
        сводки, `after_no` — всё, что случилось после названной записи, вместе они
        отвечают на вопрос «что произошло после последней сводки».
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

        Пиши её после каждого значимого шага, а не только перед выходом: решение,
        законченная часть работы, провал, меняющий план, — любой момент, когда ты бы
        объяснял коллеге, где находишься. Трекер не выпустит тебя из `in_progress` без
        сводки, но это последняя защита, а не норма: оборванный контекст сводку не
        напишет, и преемник получит только то, что подшито по дороге.

        Заголовок не принимается: им становится первая строка `done`. В описи сводка
        говорит о случившемся, как и все соседние строки.
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
        """Подшивает запись без нагрузки: решение, попытку, находку, артефакт, заметку.

        Ошибочную запись не правь — записи неизменяемы. Подшей новую: «TRK-42#12
        неверно: ...» со ссылкой на неё в `refs`.
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
        """Задаёт вопрос участникам реестра.

        Сначала собери контекст сам: дела родителя, соседей по родителю и решения в
        очереди. Агенты одинаково умны и различаются контекстом — чаще всего ответ уже
        подшит в чьём-то деле, а доставки вопросов в трекере нет.

        Вопрос открыт, пока в этой же задаче нет `answer` с его номером.
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
        """Отвечает на вопрос той же задачи.

        Ответить может кто угодно, в том числе в чужой задаче, если знаешь ответ. Первый
        ответ закрывает вопрос, остальные дополняют. Заголовок не принимается: он
        собирается из ссылки на вопрос.
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

        Неразобранные замечания приезжают в `get_task` целиком, рядом с открытыми
        вопросами: их читают на входе и по каждому называют исход перед выходом.

        Разбирает замечание любой исход, в том числе `needs_detail` — «открыто» означает
        «никто не ответил», а не «ответ недостаточен». Не согласен с замечанием —
        `declined` с причиной в теле: молчание разбором не считается. Заголовок не
        принимается: он собирается из ссылки на замечание и исхода.
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

        Раздел «обзорные проверки» — контракт: выполни ровно то, что в проверке
        написано, и положи в `evidence` доказательство — что запустил, что увидел, ссылку
        на материал. «Выглядит нормально» доказательством не является. `in_progress →
        done` требует, чтобы последний вердикт по каждой проверке был `passed`, и
        считает только вердикты этого захода: подшитые после последнего входа в
        `in_progress`. Задача, которую вернули в `open` и взяли снова, проверяется
        заново.
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
