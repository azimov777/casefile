"""Инструмент `register_participant`: человек или постоянный агент в реестре, только набором
`main`.
"""

from typing import Annotated

from pydantic import Field

from app.domain.tokens import TokenScope
from app.mcp.arguments import IdempotencyKeyArg
from app.mcp.enums import ParticipantKindSchema
from app.mcp.idempotency import Once
from app.mcp.tools.registries.arguments import ParticipantDescriptionArg
from app.mcp.tools.registries.views import ParticipantNameView, participant_name
from app.mcp.toolset import FILING, Toolset
from app.services import participants as participants_service

NewParticipantNameArg = Annotated[
    str,
    Field(
        description=(
            "Name of the new participant: a Latin letter followed by 1–63 Latin letters, "
            "digits or `_` (`invalid_participant_name` otherwise). It is stored "
            "lower-case and never changes: it signs the participant's entries. A name "
            "already taken, in any case, is refused with `participant_name_taken`"
        )
    ),
]


ParticipantKindArg = Annotated[ParticipantKindSchema, Field(description="Human or permanent agent")]


def register(tools: Toolset) -> None:
    """Объявляет `register_participant` в наборе `main`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def register_participant(
        kind: ParticipantKindArg,
        name: NewParticipantNameArg,
        description: ParticipantDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> ParticipantNameView:
        """Registers a human or a permanent agent. Only a `main` token registers
        participants; the new participant's token is issued through the REST API. An
        existing participant's description is changed by `update_participant`.
        """
        async with runtime.call() as (session, actor):

            async def create() -> ParticipantNameView:
                return participant_name(
                    await participants_service.register_participant(
                        session, actor=actor, kind=kind, name=name, description=description
                    )
                )

            return await Once.of(register_participant, session, actor, idempotency_key).run(
                result=ParticipantNameView,
                request={"kind": kind, "name": name, "description": description},
                build=create,
            )
