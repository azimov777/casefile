"""Инструменты связей и дерева подзадач.

Связь хранится один раз, а называется по-разному с двух сторон: строка, заведённая как
«TRK-2 depends_on TRK-1», у TRK-1 приезжает типом `blocks`. Поэтому и создавать связь
можно с любой стороны — сторону выбирает тип, а не порядок аргументов.

Эпик — это **тип задачи**, а не тип связи: задачи входят в эпик обычной иерархической
связью (`subtask_of`), и отдельного «положить в эпик» здесь нет и не будет.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from app.core.config import get_settings
from app.db.pagination import MAX_PAGE_SIZE
from app.domain.links import DEFAULT_TREE_DEPTH, MAX_TREE_DEPTH, LinkType
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import links as links_service


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты связей."""

    @server.tool()
    async def list_links(
        issue: Annotated[str, Field(description="Issue key")],
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List the links of an issue, named as this issue sees them.

        `depends_on` means this issue waits for the other one, `blocks` is the same
        edge seen from the other end. `subtask_of` and `parent_of` are the hierarchy.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            page = await links_service.list_issue_links(
                session,
                entry,
                initiator=actor,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (views.link(item) for item in page.items), next_cursor=page.next_cursor
            )

    @server.tool()
    async def link_issues(
        issue: Annotated[str, Field(description="Issue key the link starts from")],
        link_type: Annotated[
            LinkType,
            Field(
                description=(
                    "How the first issue relates to the second one: `relates`, "
                    "`depends_on` (waits for it), `blocks`, `subtask_of` (the second "
                    "one is the parent), `parent_of`, `duplicates`, `duplicated_by`"
                )
            ),
        ],
        other: Annotated[str, Field(description="Key of the issue on the other end")],
    ) -> dict[str, Any]:
        """Link two issues. Mutating: this writes to the tracker.

        Reads as a sentence: `<issue> <link_type> <other>`. A link that already exists
        is refused with `link_already_exists` instead of silently passing — a repeat
        usually means the side or the type is wrong.

        Hierarchy is checked further: an issue has at most one parent, an epic has none
        at all, and a cycle is refused at any depth.
        """
        async with runtime.call() as (session, actor):
            source = await refs.issue(session, issue)
            target = await refs.issue(session, other)
            link = await links_service.create_link(
                session,
                initiator=actor,
                source=source,
                link_type=link_type,
                target=target,
            )
            return views.link(links_service.link_view(link, source))

    @server.tool()
    async def unlink_issues(
        issue: Annotated[str, Field(description="Issue key the link is listed on")],
        link: Annotated[str, Field(description="Link id from `list_links`")],
    ) -> dict[str, Any]:
        """Remove a link between two issues. Mutating.

        Both issues get a changelog entry. A link that belongs to another pair answers
        `link_not_found`: from the caller's side «exists but not yours» is the same as
        «does not exist».
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            target = await links_service.get_issue_link(
                session, entry, refs.identifier(link, "link")
            )
            await links_service.delete_link(session, target, initiator=actor)
            return {"issue": entry.key, "deleted": str(target.id)}

    @server.tool()
    async def get_issue_tree(
        issue: Annotated[str, Field(description="Issue key at the root of the tree")],
        depth: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TREE_DEPTH,
                description="How many levels of subtasks to return",
            ),
        ] = DEFAULT_TREE_DEPTH,
    ) -> dict[str, Any]:
        """Read the subtask tree below an issue.

        The output is bounded twice — by depth and by the number of nodes — and a node
        whose children did not fit comes back with `has_more_children` set, so a
        trimmed tree is never mistaken for a complete one.
        """
        async with runtime.call() as (session, actor):
            entry = await refs.issue(session, issue)
            tree = await links_service.build_tree(session, entry, initiator=actor, depth=depth)
            return views.tree(tree)
