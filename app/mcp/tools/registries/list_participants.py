"""Инструмент `list_participants`: реестр участников — возможные адресаты вопроса."""

from pydantic import BaseModel

from app.db.models.participant import Participant
from app.mcp.arguments import CursorArg, LimitArg
from app.mcp.enums import ParticipantKindSchema
from app.mcp.toolset import READ_ONLY, Toolset
from app.mcp.views import PageView, page
from app.services import participants as participants_service


class ParticipantView(BaseModel):
    """Registry participant: a possible addressee of a question."""

    kind: ParticipantKindSchema
    name: str
    description: str


def participant(item: Participant) -> ParticipantView:
    """Участник реестра: кому можно адресовать вопрос и что о нём известно."""
    return ParticipantView(kind=item.kind, name=item.name, description=item.description)


def register(tools: Toolset) -> None:
    """Объявляет `list_participants` в наборе `task`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def list_participants(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> PageView[ParticipantView]:
        """Lists the participant registry: humans and permanent agents, the possible
        addressees of a question. Temporary agents are not registered and are absent
        from it.
        """
        async with runtime.call() as (session, actor):
            listed = await participants_service.list_participants(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return page(
                (participant(item) for item in listed.items),
                next_cursor=listed.next_cursor,
            )
