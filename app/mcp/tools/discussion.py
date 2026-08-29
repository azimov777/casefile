"""Инструменты обсуждения: лента комментариев и чеклист задачи.

Чеклист — единственное место, где место элемента задаётся **соседом**, а не индексом и
не позицией. Позиции наружу не отдаются вовсе: это внутреннее число разреженной шкалы,
которое меняется при перенумерации списка, и клиент, посчитавший позицию сам, однажды
поставил бы два пункта на одно место (выявлено в задаче 09).
"""

from datetime import datetime
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.sentinels import UNSET, unset_field
from app.db.pagination import MAX_PAGE_SIZE
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import checklists as checklists_service
from app.services import comments as comments_service


class ChecklistItemChangesInput(BaseModel):
    """Частичное изменение пункта чеклиста: применяются только переданные поля.

    `null` осмыслен у исполнителя и дедлайна и означает «очистить». Отметка о
    выполнении сюда не входит намеренно: у неё своё событие, на которое подписана
    автоматика, и своё имя инструмента.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = unset_field(description="New text of the item")
    assignee: str | None = unset_field(description="Actor key, or null to unassign")
    deadline: datetime | None = unset_field(
        description="ISO 8601 with a UTC offset, or null to drop the deadline"
    )


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты комментариев и чеклиста."""

    @server.tool()
    async def list_comments(
        issue: Annotated[str, Field(description="Issue key")],
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """Read the discussion of an issue, oldest first.

        Deleted comments stay in the feed as a placeholder: `body` is null and
        `is_deleted` is set. Long bodies are clipped, and the clip is reported next to
        the text as `body_truncated` with the full length.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            page = await comments_service.list_comments(
                session,
                entry,
                initiator=actor,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (views.comment(item, text_limit=settings.mcp_text_limit) for item in page.items),
                next_cursor=page.next_cursor,
            )

    @server.tool()
    async def add_comment(
        issue: Annotated[str, Field(description="Issue key")],
        body: Annotated[
            str,
            Field(
                description=(
                    "Markdown text. `@actor_key` mentions an actor and notifies them; "
                    "a key that does not exist stays plain text"
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Comment on an issue. Mutating: this writes to the tracker.

        The comment is posted as the actor behind the token. Mentions are parsed once,
        at save time: an actor created later never becomes an addressee of this text.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            posted = await comments_service.add_comment(session, entry, initiator=actor, body=body)
            return views.comment(posted, text_limit=settings.mcp_text_limit)

    @server.tool()
    async def get_checklist(
        issue: Annotated[str, Field(description="Issue key")],
    ) -> dict[str, Any]:
        """Read the checklist of an issue, in order.

        The whole list comes back at once — the number of items is bounded by the
        domain, so there is no cursor. Item positions are deliberately not exposed:
        moving an item is expressed by naming the neighbour it goes after.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            items = await checklists_service.list_items(session, entry, initiator=actor)
            return {"issue": entry.key, "items": [views.checklist_item(item) for item in items]}

    @server.tool()
    async def add_checklist_item(
        issue: Annotated[str, Field(description="Issue key")],
        text: Annotated[str, Field(description="What has to be done")],
        assignee: Annotated[str | None, Field(description="Actor key")] = None,
        deadline: Annotated[
            datetime | None, Field(description="ISO 8601 with a UTC offset")
        ] = None,
    ) -> dict[str, Any]:
        """Add an item to the end of the checklist. Mutating.

        Items are always appended; the place is chosen afterwards with
        `move_checklist_item`.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            item = await checklists_service.add_item(
                session,
                entry,
                initiator=actor,
                text=text,
                assignee=await refs.actor(session, assignee),
                deadline=deadline,
            )
            return views.checklist_item(item)

    @server.tool()
    async def update_checklist_item(
        issue: Annotated[str, Field(description="Issue key")],
        item: Annotated[str, Field(description="Checklist item id from `get_checklist`")],
        changes: ChecklistItemChangesInput,
    ) -> dict[str, Any]:
        """Change the text, assignee or deadline of a checklist item. Mutating.

        Only the fields you pass are applied; `null` clears the assignee or the
        deadline. The done mark has its own tool
        (`check_checklist_item`): it carries its own event, and automation subscribes
        to it.
        """
        given = changes.model_dump(exclude_unset=True)
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            target = await checklists_service.get_item(
                session, entry, refs.identifier(item, "item")
            )
            updated = await checklists_service.update_item(
                session,
                target,
                issue=entry,
                initiator=actor,
                text=given.get("text", UNSET),
                assignee=(
                    await refs.actor(session, given["assignee"]) if "assignee" in given else UNSET
                ),
                deadline=given.get("deadline", UNSET),
            )
            return views.checklist_item(updated)

    @server.tool()
    async def check_checklist_item(
        issue: Annotated[str, Field(description="Issue key")],
        item: Annotated[str, Field(description="Checklist item id from `get_checklist`")],
        is_done: Annotated[bool, Field(description="True marks it done, false unmarks it")] = True,
    ) -> dict[str, Any]:
        """Mark a checklist item done or undone. Mutating.

        Repeating the same value changes nothing and is not an error: the tracker does
        not record an event for a change that did not happen.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            target = await checklists_service.get_item(
                session, entry, refs.identifier(item, "item")
            )
            updated = await checklists_service.set_item_done(
                session, target, issue=entry, initiator=actor, is_done=is_done
            )
            return views.checklist_item(updated)

    @server.tool()
    async def move_checklist_item(
        issue: Annotated[str, Field(description="Issue key")],
        item: Annotated[str, Field(description="Checklist item id to move")],
        after: Annotated[
            str | None,
            Field(
                description=(
                    "Id of the item this one goes after; null moves it to the top of "
                    "the list. There is no index or position: they would go stale the "
                    "moment somebody else reorders the list"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Move a checklist item after another one. Mutating.

        Answers with the whole checklist: the caller asked to change the **order**, and
        one item cannot show it.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            target = await checklists_service.get_item(
                session, entry, refs.identifier(item, "item")
            )
            neighbour = (
                None
                if after is None
                else await checklists_service.get_item(
                    session, entry, refs.identifier(after, "after")
                )
            )
            await checklists_service.move_item(
                session, target, issue=entry, initiator=actor, after=neighbour
            )
            items = await checklists_service.list_items(session, entry, initiator=actor)
            return {"issue": entry.key, "items": [views.checklist_item(each) for each in items]}

    @server.tool()
    async def delete_checklist_item(
        issue: Annotated[str, Field(description="Issue key")],
        item: Annotated[str, Field(description="Checklist item id to remove")],
    ) -> dict[str, Any]:
        """Remove a checklist item for good. Mutating.

        Unlike a comment, the deletion is hard: nothing is left in the list. The fact
        stays in the issue changelog and in the `checklist.item_removed` event.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            target = await checklists_service.get_item(
                session, entry, refs.identifier(item, "item")
            )
            await checklists_service.delete_item(session, target, issue=entry, initiator=actor)
            return {"issue": entry.key, "deleted": str(target.id)}
