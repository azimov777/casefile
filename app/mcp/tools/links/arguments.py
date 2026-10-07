"""Аргументы, общие для `link` и `unlink`: вид связи и задача или обсуждение на другой
стороне."""

from typing import Annotated

from pydantic import Field

from app.mcp.enums import LinkToolKindSchema

LinkKindArg = Annotated[
    LinkToolKindSchema,
    Field(
        description=(
            "Role of the task `key` toward `other`: "
            "`link(key='TRK-1', kind='blocks', other='TRK-7')` means TRK-1 blocks TRK-7, "
            "and the card of TRK-7 shows the same link as `blocked_by`. `attached` makes "
            "the task depend on the outcome of the discussion `other`"
        )
    ),
]

OtherTaskKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the task on the other side of the link; with `attached`, the address "
            "of the discussion `PROJECT~N`"
        ),
        examples=["TRK-7"],
    ),
]
