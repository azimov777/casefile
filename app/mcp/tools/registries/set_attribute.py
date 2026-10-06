"""Инструмент `set_attribute`: завести атрибут проекта или направления или изменить его
значение."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.mcp.arguments import CaseOwnerKeyArg, IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.arguments import AttributeNameArg
from app.mcp.toolset import IDEMPOTENT_TASK_UPDATE, Toolset
from app.services import attributes as attributes_service
from app.services import directions as directions_service
from app.services.attributes import AttributeSet
from app.services.case import owner_name

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
    """Attribute after the call; the project or direction with all attributes is returned
    by `get_project`.
    """

    project_key: str = Field(description="Project key or direction address")
    name: str = Field(description="Name as stored: the spelling the attribute was created with")
    value: str
    no: int | None = Field(
        description=(
            "Number of the filed entry in its case (`TRK#7`); `null` when the value equals "
            "the current one and nothing was filed"
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
    """Объявляет `set_attribute`."""
    runtime = tools.runtime

    @tools.tool(title="Set attribute", annotations=IDEMPOTENT_TASK_UPDATE, creating=True)
    async def set_attribute(
        key: CaseOwnerKeyArg,
        name: AttributeNameArg,
        value: AttributeValueArg,
        reason: AttributeSetReasonArg = None,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AttributeSetView:
        """Sets the value of an attribute: a reference fact such as the repository or the
        main branch, kept by a project or direction. One call both creates and changes;
        which entry it files in the owner's case follows from the attribute's state.

        - No attribute with this name, ignoring case: the attribute is created and an
          `attribute_created` entry is filed; the reason is optional.
        - An attribute with another value: the value changes and an
          `attribute_changed` entry is filed with the previous value; the reason is
          required.
        - The same value: nothing changes and nothing is filed.

        The name keeps the spelling it was created with; another spelling addresses the
        same attribute and does not rename it. Attributes carry no types and no search:
        the tracker stores the text and acts on none of it.
        """
        async with runtime.call() as (session, actor):
            owner = await directions_service.get_owner(session, key)

            async def put() -> AttributeSetView:
                result = await attributes_service.set_attribute(
                    session, owner, actor=actor, name=name, value=value, reason=reason
                )
                return attribute_set(result, project_key=owner_name(owner))

            return await Once.of(set_attribute, session, actor, idempotency_key).run(
                result=AttributeSetView,
                request={
                    "project": owner_name(owner),
                    "name": name.lower(),
                    "value": value,
                    "reason": reason,
                },
                build=put,
            )
