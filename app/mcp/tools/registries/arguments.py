"""Аргументы, общие для инструментов группы: описание участника (`register_participant`,
`update_participant`), имя атрибута проекта (`set_attribute`, `remove_attribute`) и
причина архивирования (`archive_project`, `restore_project`).
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

ProjectReasonArg = Annotated[
    str,
    Field(
        description=(
            "Why the project is archived or restored; a blank one is refused with "
            "`project_reason_required`. Filed in the `archived` or `restored` entry of the "
            "project's case"
        )
    ),
]
