"""Аргументы пары задач, общие для `link` и `unlink`: вид связи и задача на другой стороне."""

from typing import Annotated

from pydantic import Field

from app.mcp.enums import LinkKindSchema

LinkKindArg = Annotated[
    LinkKindSchema,
    Field(
        description=(
            "Role of the task `key` toward the task `other`: "
            "`link(key='TRK-1', kind='blocks', other='TRK-7')` means TRK-1 blocks TRK-7, "
            "and the card of TRK-7 shows the same link as `blocked_by`"
        )
    ),
]

OtherTaskKeyArg = Annotated[
    str,
    Field(description="Key of the task on the other side of the link", examples=["TRK-7"]),
]
