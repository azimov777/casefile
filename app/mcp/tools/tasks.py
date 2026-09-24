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
        """Отдаёт всё о задаче одним вызовом: карточка, родитель и дети, связи с обеих
        сторон, вычисляемые признаки, последняя сводка, открытые вопросы, неразобранные
        замечания, опись дела и переходы по таблице статусов.

        `parent` — родитель этой задачи (или `null`), `children` — её дети. Заводятся
        они тем же `link`, что и остальные связи, но в `links` их нет: там `blocks`,
        `blocked_by` и `relates`, вид назван ролью этой задачи.

        В описи только заголовки: тела записей отдаёт `read_entries`.

        `transitions` это цели по таблице из текущего статуса, а не ходы, которые
        пройдут сейчас: разделы, сводку, вердикты, блокеры и детей трекер проверяет в
        момент `transition`. Пустят ли в `in_progress`, говорит признак `blocked`.
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
        """Ищет задачи строкой языка запросов, отдельными условиями или всем сразу.

        Условия из обоих источников складываются по «и» и дают тот же результат, что
        одна строка того же смысла. Отбор без условий законен: это «все задачи».

        Отказ: строка не разбирается — `invalid_search_query` с позицией символа;
        неизвестное поле, оператор или значение — свой код и допустимые в `details`.

        Здесь строки выборки с полями из `fields`; одна задача целиком, с делом и
        связями, — `get_task`.
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
        """Заводит задачу в `backlog`. Статус не принимается: новая задача рождается там.

        `parent` делает задачу ребёнком названной — ребёнок рождается со ссылкой на
        родителя, это одно действие, а не два. Родитель не закроется — ни в `done`, ни в
        `cancelled`, — пока дети не закрыты. Связь подшивает `link_added` не только в
        дело новой задачи, но и в дело родителя — это его дело меняется, а не только
        дело вызова; номер этой записи называет `parent_entry`.

        Отвечает коротко: ключ новой задачи, статус, версия и номера подшитых записей;
        они сразу видны в ленте и человеку в интерфейсе. Карточку не возвращает — всё,
        что в ней было бы, только что прислал сам вызов. Ключ приходит всегда: его выдал
        трекер, и заранее знать его было неоткуда.

        Отказ: пустое название или описание — `task_fields_invalid`; очереди нет —
        `queue_not_found`; родитель закрыт — `task_closed`.
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
        """Меняет переданные поля задачи; непереданное не трогает.

        Название, описание и пять разделов правятся только в `backlog`: в остальных
        статусах — отказ `task_field_locked`.

        Проверку переписывают точечно: `check={"no": 3, "text": "..."}`. Остальные
        остаются теми же байтами, а служебная запись называет номер — по нему видно,
        какой из подшитых вердиктов перестал относиться к нынешней формулировке.
        Присылать `checks` списком нужно только когда меняется **состав**: проверка
        добавляется, снимается или переставляется. Вместе они не принимаются.

        Отвечает коротко: ключ, статус, новая версия и номера подшитых записей;
        `section_changed` и `field_changed` сразу видны в ленте и человеку в интерфейсе.
        Пустой `entries` означает «прислано то, что уже стоит» — версия тогда не
        выросла.
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
        """Переводит задачу в другой статус по зашитой таблице переходов.

        Трекер откажет, если переход портит журнал: выход из `in_progress` без сводки,
        подшитой после последнего входа в него (`summary_required`); вход в
        `in_progress` без исполнителя (`assignee_required`) или не от него
        (`assignee_mismatch`: исполнитель и подпись просящего в `details`) и при
        открытом блокере (`task_blocked`); `cancelled` при незакрытых детях
        (`task_has_unclosed_children`). В `done` этот вызов не ведёт: закрывает
        `close_task`, а здесь цель `done` отвечает `closing_not_a_transition`. В отказе —
        что именно мешает. Ни в `waiting`, ни из него трекер не переводит сам: оба хода
        делает вызывающий.

        Вход в `in_progress` — из любого статуса, включая `waiting`, — открывает новый
        заход: `in_progress → done` дальше зачтёт только вердикты, подшитые после этого
        перехода, а прежние останутся в деле, но не в счёте. Переход в `cancelled`
        снимает признак `blocked` у задач, которые эта блокировала (`blocks`), — без
        записи в их деле; так же его снимает и `close_task`.

        Этих проверок нет в `transitions` у `get_task`: там таблица переходов.

        Отвечает коротко: ключ, новый статус, новая версия и номер подшитой
        `status_changed`; она сразу видна в ленте и человеку в интерфейсе. Карточку
        целиком не возвращает.
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
        """Подшивает записи, вердикты и финальную сводку и переводит задачу в `done` —
        всё одним вызовом и одной транзакцией.

        Единственная дверь в `done`: у `transition` эта цель отвечает
        `closing_not_a_transition`. Частичного закрытия не бывает — отказ на любой части
        не оставляет в деле ни одной записи и статуса не меняет.

        Финальная сводка на одну часть длиннее промежуточной: сверх четырёх обычных она
        требует `unmeasured` — какую часть цели не измерила ни одна обзорная проверка.
        Пустой она быть не может, как и остальные: `entry_fields_invalid`.

        Каждая запись получает свой номер в описи. Записи немедленно видны в ленте и
        человеку в интерфейсе; будят ждущих `wait_journal`. Порядок подшивки: присланные
        записи, вердикты, сводка.

        Требования выхода прежние и проверяются после подшивки: положительный последний
        вердикт по каждой обзорной проверке среди подшитых после последнего входа в
        `in_progress` (`checks_not_passed`), закрытые дети
        (`task_has_unclosed_children`), задача в `in_progress` (`transition_not_allowed`).
        Вердикты этого вызова в счёт входят наравне с подшитыми раньше по ходу работы.

        Задачи, которые эта блокировала (`blocks`), теряют признак `blocked` — без
        записи в их деле.

        Ответ короткий: ключ, новый статус, новая версия и строка на каждую подшитую
        запись — `no`, `seq`, автор, время и заголовок там, где его собрал трекер.
        Присланное обратно не едет; записи целиком — в `read_entries`.
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
