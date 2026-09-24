"""Инструмент ленты: хвост журнала с долгим ожиданием.

Отдельной таблицы событий в трекере нет: журнал всех записей дела и есть лента
(`CONCEPT.md`, 4.1). Фильтр здесь не собирается вручную — ключи задач и очереди
разрешает `journal.resolve_filter`, тот же, что и в REST: опечатка в ключе иначе дала бы
пустую ленту, неотличимую от «ничего не происходит», и ждущий висел бы до таймаута, считая
установку спящей. Там же разбирается и форма `task`: один ключ или список.

Потолки ожидания (`MAX_WAIT_SECONDS`) и числа задач (`MAX_TASK_KEYS`) проверяет домен и
отвечает `journal_wait_too_long` и `journal_too_many_tasks` с числом в подробностях.
Своей ветки условий инструмент не заводит по той же причине, что и `search_tasks`.
"""

from app.domain.journal import JOURNAL_START
from app.mcp import views
from app.mcp.arguments import (
    AfterArg,
    CursorArg,
    JournalQueueArg,
    JournalTaskArg,
    LimitArg,
    TimeoutArg,
)
from app.mcp.tools.case.arguments import EntryTypesArg
from app.mcp.tools.case.views import EntryView, entry
from app.mcp.toolset import READ_ONLY, Toolset
from app.services import journal as journal_service


def register(tools: Toolset) -> None:
    """Объявляет инструмент ленты."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def wait_journal(
        after: AfterArg = JOURNAL_START,
        task: JournalTaskArg = None,
        queue: JournalQueueArg = None,
        types: EntryTypesArg = None,
        timeout: TimeoutArg = 0,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[EntryView]:
        """Returns journal entries after the sequence number `after`, waiting for new ones.

        The journal is every case entry of the installation in one stream, in `seq`
        order; `task`, `queue` and `types` narrow it. The call returns as soon as a
        matching entry appears, and after `timeout` seconds at the latest. The next call
        continues from the `seq` of the last entry received. With `types=["answer"]` and
        `task`, one call covers an answer expected within `timeout`.

        Entries already filed in one case, by number, are returned by `read_entries`.
        """
        async with runtime.call() as (session, actor):
            page = await journal_service.wait_journal(
                session,
                actor=actor,
                journal_filter=await journal_service.resolve_filter(
                    session, task=task, queue=queue, types=types
                ),
                after=after,
                cursor=cursor,
                limit=limit or settings.mcp_page_size,
                wait=timeout,
            )
            return views.page(
                (entry(item.entry, task_key=item.task_key) for item in page.items),
                next_cursor=page.next_cursor,
            )
