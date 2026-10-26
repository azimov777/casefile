"""Аргументы, общие для `link` и `unlink`: сторона связи `key`, вид связи и задача, обсуждение
или область на другой стороне."""

from typing import Annotated

from pydantic import Field

from app.mcp.enums import LinkToolKindSchema

LinkKeyArg = Annotated[
    str,
    Field(description="Task key `PROJECT-N`, or area address `PROJECT/key` with `see_also`"),
]

LinkKindArg = Annotated[
    LinkToolKindSchema,
    Field(
        description=(
            "Role of the task `key` toward `other`: "
            "`link(key='TRK-1', kind='blocks', other='TRK-7')` means TRK-1 blocks TRK-7, "
            "and the card of TRK-7 shows the same link as `blocked_by`. `attached` makes "
            "the task depend on the outcome of the discussion `other`. `see_also` is "
            "the only kind of an area"
        )
    ),
]

OtherTaskKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the task on the other side of the link; with `attached`, the address "
            "of the discussion `PROJECT~N`; with `see_also`, the address of the area"
        ),
        examples=["TRK-7"],
    ),
]

ReasonArg = Annotated[
    str | None,
    Field(
        description=(
            "Why whoever works in the area `key` also reads the area `other`: one phrase, "
            "up to 200 characters. Required with `see_also`, refused for a task"
        )
    ),
]
