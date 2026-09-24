"""Инструмент `update_participant`: описание участника, только набором `main`."""

from typing import Annotated

from pydantic import Field

from app.domain.tokens import TokenScope
from app.mcp.tools.registries.arguments import ParticipantDescriptionArg
from app.mcp.tools.registries.views import ParticipantNameView, participant_name
from app.mcp.toolset import OVERWRITING_UPDATE, Toolset
from app.services import participants as participants_service

ParticipantNameArg = Annotated[
    str,
    Field(
        description=(
            "Participant name, case-insensitive. An unknown name is refused with "
            "`participant_not_found`"
        )
    ),
]


def register(tools: Toolset) -> None:
    """Объявляет `update_participant` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=OVERWRITING_UPDATE, scope=TokenScope.MAIN)
    async def update_participant(
        name: ParticipantNameArg,
        description: ParticipantDescriptionArg,
    ) -> ParticipantNameView:
        """Changes a participant's description. Only a `main` token edits participants.
        Name and kind never change: the name signs entries already filed. The previous
        description is not kept.
        """
        async with runtime.call() as (session, actor):
            participant = await participants_service.get_participant(session, name)
            return participant_name(
                await participants_service.update_participant(
                    session, participant, actor=actor, description=description
                )
            )
