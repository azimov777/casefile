"""Аргументы, общие для инструментов группы: описание участника (`register_participant`,
`update_participant`) и имя атрибута проекта (`set_attribute`, `remove_attribute`).
"""

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

AttributeNameArg = Annotated[
    str,
    Field(
        description=(
            "Attribute name: Latin letters, digits, `_` and `-`, at most 64 characters "
            "(`invalid_attribute_name` otherwise). Matching ignores case"
        )
    ),
]
