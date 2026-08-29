"""Инструменты досок: что в колонках и как двигать карточки.

Своего отбора у доски нет: задачи колонки — это фильтр доски плюс статусы колонки,
склеенные по `and`, и считает их тот же поиск. Поэтому `query` может сузить выдачу
языком запросов, но не может вывести её за пределы колонки (выявлено в задаче 11).

Порядок карточек задаёт ранг доски, и параметра сортировки у колонки нет намеренно:
возможность переопределить порядок сделала бы перетаскивание бессмысленным.

Движений карточки два, и они разные. `rank_card` меняет только порядок: статус не
трогается, версия задачи не растёт, в историю ничего не попадает. `move_card_to_column`
меняет статус и потому идёт **переходом воркфлоу** со всеми его проверками — и может
законно отказать.
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.sentinels import UNSET, unset_field
from app.db.pagination import MAX_PAGE_SIZE
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import boards as boards_service
from app.services import issues as issues_service


class CardAnchorInput(BaseModel):
    """Место карточки: ровно один сосед, `null` — край списка.

    Два поля, а не одно со знаком, потому что различать надо три состояния: «после
    задачи X», «в самое начало» (`after: null`) и «в самый конец» (`before: null`).
    Индекса и позиции здесь нет намеренно: индекс разошёлся бы с доской, которую тем
    временем изменил кто-то ещё, а позиция — внутреннее число шкалы, и, отдав его,
    сервер позвал бы клиента считать место самому.
    """

    model_config = ConfigDict(extra="forbid")

    after: str | None = unset_field(
        description="Issue key this card goes after; null puts it first"
    )
    before: str | None = unset_field(
        description="Issue key this card goes before; null puts it last"
    )


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты досок."""

    @server.tool()
    async def list_boards(
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List boards with their columns.

        A board takes its issues from a saved filter and lays them out by status. The
        cards of one column come from `list_column_issues`.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            page = await boards_service.list_boards(
                session,
                initiator=actor,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (views.board(item) for item in page.items), next_cursor=page.next_cursor
            )

    @server.tool()
    async def get_board(
        board: Annotated[str, Field(description="Board id from `list_boards`")],
    ) -> dict[str, Any]:
        """Read a board: its settings and its columns with their statuses.

        The cards are not included: one board can pull thousands of issues, so every
        column is paged on its own by `list_column_issues`.
        """
        async with runtime.call() as (session, actor):
            entry = await boards_service.read_board(
                session, refs.identifier(board, "board"), initiator=actor
            )
            return views.board(entry)

    @server.tool()
    async def list_column_issues(
        board: Annotated[str, Field(description="Board id")],
        column: Annotated[str, Field(description="Column id from `get_board`")],
        query: Annotated[
            str,
            Field(
                description=(
                    "Query language string that narrows the column further; it cannot "
                    "widen the selection beyond the board filter and the column statuses"
                )
            ),
        ] = "",
        fields: Annotated[
            list[str] | None,
            Field(description="Fields to return; omit for the brief set, `['*']` for whole issues"),
        ] = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List the cards of one board column, in board rank order.

        There is no sort parameter on purpose: the order is the board rank, and it is
        changed by `rank_card`, not by sorting.
        """
        settings = get_settings()
        selected = views.BRIEF_FIELDS if not fields else () if "*" in fields else tuple(fields)
        async with runtime.call() as (session, actor):
            entry = await boards_service.read_board(
                session, refs.identifier(board, "board"), initiator=actor
            )
            target = boards_service.get_column(entry, refs.identifier(column, "column"))
            outcome = await boards_service.list_column_issues(
                session,
                entry,
                target,
                initiator=actor,
                query=query or None,
                fields=selected,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (
                    views.issue(
                        item,
                        fields=outcome.resolved.fields,
                        value_refs=outcome.resolved.value_refs,
                        text_limit=settings.mcp_text_limit,
                    )
                    for item in outcome.page.items
                ),
                next_cursor=outcome.page.next_cursor,
            )

    @server.tool()
    async def move_card_to_column(
        board: Annotated[str, Field(description="Board id")],
        column: Annotated[str, Field(description="Target column id from `get_board`")],
        issue: Annotated[str, Field(description="Issue key of the card")],
        status: Annotated[
            str | None,
            Field(
                description=(
                    "Status reference to move into; required when the column holds "
                    "more than one status, because choosing for the caller would put "
                    "the issue into a status nobody asked for"
                )
            ),
        ] = None,
        resolution: Annotated[
            str | None,
            Field(description="Resolution reference; required when the target status is `done`"),
        ] = None,
        version: Annotated[
            int | None, Field(ge=1, description="Version the caller last saw")
        ] = None,
    ) -> dict[str, Any]:
        """Move a card to another column. Mutating.

        This is a **workflow transition**, not a status write, so it can be refused the
        same way any status change can: `transition_not_allowed`,
        `transition_requirements_not_met`, `issue_resolution_required`. Take the reason
        as it is — the board deliberately cannot write a status directly, and there is
        no other path to force the change.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            entry = await boards_service.read_board(
                session, refs.identifier(board, "board"), initiator=actor
            )
            target = boards_service.get_column(entry, refs.identifier(column, "column"))
            card = await issues_service.read_issue(session, issue, initiator=actor)
            mutation = await boards_service.move_issue_to_column(
                session,
                entry,
                card,
                target,
                initiator=actor,
                status=await refs.optional_status(session, status, initiator=actor),
                resolution=(
                    await refs.resolution(session, resolution, initiator=actor)
                    if resolution is not None
                    else UNSET
                ),
                expected_version=version,
            )
            return views.issue(mutation.issue, text_limit=settings.mcp_text_limit)

    @server.tool()
    async def rank_card(
        board: Annotated[str, Field(description="Board id")],
        issue: Annotated[str, Field(description="Issue key of the card to move")],
        anchor: CardAnchorInput,
    ) -> dict[str, Any]:
        """Put a card before or after another one on a board. Mutating.

        Order only: the status is not touched, the issue version does not grow and
        nothing is written to its changelog. The anchor carries exactly one of `after`
        and `before`; both at once and neither are both refused. The rank belongs to
        the board, so the same issue can stand first here and twentieth on another
        board.
        """
        given = anchor.model_dump(exclude_unset=True)
        async with runtime.call() as (session, actor):
            entry = await boards_service.read_board(
                session, refs.identifier(board, "board"), initiator=actor
            )
            card = await issues_service.read_issue(session, issue, initiator=actor)
            await boards_service.rank_issue(
                session,
                entry,
                card,
                initiator=actor,
                after=(await _neighbour(session, given["after"]) if "after" in given else UNSET),
                before=(await _neighbour(session, given["before"]) if "before" in given else UNSET),
            )
            return {"board": str(entry.id), "issue": card.key, "ranked": True}


async def _neighbour(session: Any, key: str | None) -> Any:
    """Сосед по ключу; `None` остаётся `None` — это край списка, а не отсутствие места."""
    return None if key is None else await refs.issue(session, key)
