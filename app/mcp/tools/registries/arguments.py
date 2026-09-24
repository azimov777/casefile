"""Аргумент участника, общий для `register_participant` и `update_participant`: описание."""

from typing import Annotated

from pydantic import Field

ParticipantDescriptionArg = Annotated[
    str,
    Field(
        description=(
            "Who the participant is: all that a reader of a case learns about the author "
            "of an entry"
        )
    ),
]
