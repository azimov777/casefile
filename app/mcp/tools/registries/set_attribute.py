"""Инструмент `set_attribute`: завести атрибут проекта или изменить его значение."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.mcp.arguments import IdempotencyKeyArg, ProjectKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.arguments import AttributeNameArg
from app.mcp.toolset import IDEMPOTENT_TASK_UPDATE, Toolset
from app.services import attributes as attributes_service
from app.services import projects as projects_service
from app.services.attributes import AttributeSet

AttributeValueArg = Annotated[
    str,
    Field(
        description=(
            "Attribute value: plain text up to 1000 characters, stored as sent and not "
            "interpreted by the tracker; a longer one is refused with "
            "`attribute_value_too_long`"
        )
    ),
]

AttributeSetReasonArg = Annotated[
    str | None,
    Field(
        description=(
            "Why the value changes. Required when the attribute already exists with "
            "another value (`attribute_reason_required` otherwise); optional when the "
            "call creates it. Filed in the entry with the previous and the new value"
        )
    ),
]


# Ответ: имя в хранимом написании и номер подшитой записи. Значение агент прислал сам,
# но оно остаётся в ответе: без него «ничего не подшито» (`no: null`) не отличить от
# «подшито не то».
class AttributeSetView(BaseModel):
    """Project attribute after the call; the project with all attributes is returned by
    `get_project`.
    """

    project_key: str
    name: str = Field(description="Name as stored: the spelling the attribute was created with")
    value: str
    no: int | None = Field(
        description=(
            "Number of the filed entry in the project's case (`TRK#7`); `null` when the "
            "value equals the current one and nothing was filed"
        )
    )


def attribute_set(result: AttributeSet, *, project_key: str) -> AttributeSetView:
    """Ответ `set_attribute`: атрибут после вызова и номер записи, если она подшита."""
    return AttributeSetView(
        project_key=project_key,
        name=result.attribute.name,
        value=result.attribute.value,
        no=None if result.entry is None else result.entry.no,
    )


def register(tools: Toolset) -> None:
    """Объявляет `set_attribute` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=IDEMPOTENT_TASK_UPDATE, creating=True)
    async def set_attribute(
        key: ProjectKeyArg,
        name: AttributeNameArg,
        value: AttributeValueArg,
        reason: AttributeSetReasonArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AttributeSetView:
        """Sets the value of a project attribute: a reference fact of the project such as
        its repository or main branch. One call both creates and changes; which entry
        it files follows from the attribute's state.

        - No attribute with this name, ignoring case: the attribute is created and an
          `attribute_created` entry is filed; the reason is optional.
        - An attribute with another value: the value changes and an
          `attribute_changed` entry is filed with the previous value; the reason is
          required.
        - The same value: nothing changes and nothing is filed.

        The name keeps the spelling it was created with; another spelling addresses the
        same attribute and does not rename it. Attributes carry no types and no search:
        the tracker stores the text and acts on none of it. A `task` token sets
        attributes.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)

            async def put() -> AttributeSetView:
                result = await attributes_service.set_attribute(
                    session, project, actor=actor, name=name, value=value, reason=reason
                )
                return attribute_set(result, project_key=project.key)

            return await Once.of(set_attribute, session, actor, idempotency_key).run(
                result=AttributeSetView,
                request={
                    "project": project.key,
                    "name": name.lower(),
                    "value": value,
                    "reason": reason,
                },
                build=put,
            )
