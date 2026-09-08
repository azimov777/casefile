"""Инструмент ленты: хвост журнала с долгим ожиданием.

Отдельной таблицы событий в трекере нет: журнал всех записей дела и есть лента
(`CONCEPT.md`, 4.1). Фильтр здесь не собирается вручную — ключи задачи и очереди
разрешает `journal.resolve_filter`, тот же, что и в REST: опечатка в ключе иначе дала бы
пустую ленту, неотличимую от «ничего не происходит», и ждущий висел бы до таймаута, считая
установку спящей.

Потолок ожидания (`MAX_WAIT_SECONDS`) проверяет домен и отвечает `journal_wait_too_long` с
числом в подробностях. Своей ветки условий инструмент не заводит по той же причине, что и
`search_tasks`.
"""

from app.domain.journal import JOURNAL_START
from app.mcp import views
from app.mcp.arguments import (
    AfterArg,
    CursorArg,
    EntryTypesArg,
    JournalQueueArg,
    JournalTaskArg,
    LimitArg,
    TimeoutArg,
)
from app.mcp.toolset import Toolset
from app.services import journal as journal_service


def register(tools: Toolset) -> None:
    """Объявляет инструмент ленты."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool()
    async def wait_journal(
        after: AfterArg = JOURNAL_START,
        task: JournalTaskArg = None,
        queue: JournalQueueArg = None,
        types: EntryTypesArg = None,
        timeout: TimeoutArg = 0,
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.EntryView]:
        """Записи журнала после номера `after`, с ожиданием новых.

        Так ждут ответа, не отпуская задачу: `wait_journal(after=<seq>, task=<ключ>,
        types=["answer"], timeout=30)`. Годится, когда ответ ожидается скоро; если нет —
        напиши сводку и уйди в `open`, назначатель вернёт задачу после ответа.

        Ответ приходит, как только появилась первая подходящая запись, и не позже, чем
        через `timeout` секунд. Продолжай с `after`, равного `seq` последней полученной
        записи: записи постоянны, и пропустить их нельзя.
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
                (views.entry(item.entry, task_key=item.task_key) for item in page.items),
                next_cursor=page.next_cursor,
            )
