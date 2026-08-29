"""Инструменты инбокса: забрать уведомления, отметить прочитанными, дождаться новых.

Инбокс — **основной** канал уведомлений и единственный, который работает у любого
клиента. MCP-нотификации (`app/mcp/push.py`) идут поверх и содержимого не несут: они
говорят «в инбоксе что-то появилось», а записи и отметка о прочтении те же самые.
Поэтому агент, разобравший ленту инструментом, не получит её повторно нотификацией.

Своей логики здесь нет: `list_notifications`, `mark_read` и `wait_for_notifications` —
те же сценарии, что зовёт REST (выявлено в задаче 14).
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.core.config import get_settings
from app.db.pagination import MAX_PAGE_SIZE
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import notifications as notifications_service


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты инбокса."""

    @server.tool()
    async def list_notifications(
        unread_only: Annotated[bool, Field(description="Only what has not been read yet")] = True,
        issue: Annotated[
            str | None, Field(description="Issue key: only notifications about this issue")
        ] = None,
        event_type: Annotated[
            str | None,
            Field(
                description=("Event type, for example `issue.status_changed` or `comment.created`")
            ),
        ] = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """Read the inbox of the actor behind the token, oldest first.

        This is your own queue of work: another actor's inbox cannot be read at all.
        Each record carries both a ready text (`body`) and identifiers (`event_type`,
        `issue`, `details`) — decide by the identifiers, not by parsing the text.

        `count` above one means repeats of the same event on the same object were
        merged into one record. Reading does **not** mark anything: call
        `mark_notifications_read` when you are done with what you took.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            page = await notifications_service.list_notifications(
                session,
                initiator=actor,
                is_read=False if unread_only else None,
                issue=await refs.issue(session, issue) if issue is not None else None,
                event_type=event_type,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            unread = await notifications_service.count_unread(session, initiator=actor)
            return views.page(
                (views.notification(item) for item in page.items),
                next_cursor=page.next_cursor,
            ) | {"unread": unread}

    @server.tool()
    async def mark_notifications_read(
        notifications: Annotated[
            list[str] | None,
            Field(description=("Notification ids to mark; omit to mark the whole inbox read")),
        ] = None,
    ) -> dict[str, Any]:
        """Mark notifications as read. Mutating: this changes your inbox.

        Answers with how many records actually changed state. Zero is not an error —
        already read records are not counted again, so repeating the call is safe.

        The mark is shared with the MCP notification channel: what you marked here does
        not come back as a push.
        """
        async with runtime.call() as (session, actor):
            marked = await notifications_service.mark_read(
                session,
                initiator=actor,
                notification_ids=(
                    None
                    if notifications is None
                    else [refs.identifier(item, "notifications") for item in notifications]
                ),
            )
            unread = await notifications_service.count_unread(session, initiator=actor)
            return {"marked": marked, "unread": unread}

    @server.tool()
    async def wait_for_notifications(
        timeout: Annotated[
            float | None,
            Field(
                gt=0,
                description=(
                    "Seconds to block waiting. Bounded from above by the installation "
                    "setting; asking for more is an error (`invalid_wait_timeout`), not "
                    "a silent clamp. Defaults to the installation default"
                ),
            ),
        ] = None,
        limit: Annotated[
            int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="How many to return at most")
        ] = None,
    ) -> dict[str, Any]:
        """Block until new notifications arrive, then return them.

        Returns as soon as something appears. An empty answer with `timed_out: true` is
        a normal outcome, not a failure — check that field, because the call is
        successful either way. `waited` says how long it actually blocked.

        The call does not hold a database connection while it sleeps, so several agents
        may wait at once. It does not mark anything read.
        """
        async with runtime.call() as (session, actor):
            outcome = await notifications_service.wait_for_notifications(
                session,
                initiator=actor,
                timeout=timeout,
                limit=limit,
            )
            return views.inbox_wait(outcome)
