"""Инструмент `remove_attribute`: снять атрибут проекта или области с причиной."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.db.models.entry import Entry
from app.mcp.arguments import CaseOwnerKeyArg, IdempotencyKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.arguments import AttributeNameArg
from app.mcp.toolset import FILING, Toolset
from app.services import areas as areas_service
from app.services import attributes as attributes_service
from app.services.case import owner_name

AttributeRemovalReasonArg = Annotated[
    str,
    Field(
        description=(
            "Why the attribute is removed; a blank one is refused with "
            "`attribute_reason_required`. Filed in the `attribute_removed` entry together "
            "with the last value"
        )
    ),
]


class AttributeRemovedView(BaseModel):
    """Removed attribute, by the entry that records the removal; the entry in full is
    returned by `read_project_entries`.
    """

    project_key: str = Field(description="Project key or area address")
    name: str = Field(description="Name as it was stored")
    no: int = Field(description="Number of the `attribute_removed` entry in its case")


def attribute_removed(entry: Entry, *, project_key: str) -> AttributeRemovedView:
    """Ответ `remove_attribute`: имя снятого атрибута и номер записи о снятии."""
    return AttributeRemovedView(project_key=project_key, name=entry.payload["name"], no=entry.no)


def register(tools: Toolset) -> None:
    """Объявляет `remove_attribute`."""
    runtime = tools.runtime

    @tools.tool(title="Remove attribute", annotations=FILING, creating=True)
    async def remove_attribute(
        key: CaseOwnerKeyArg,
        name: AttributeNameArg,
        reason: AttributeRemovalReasonArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AttributeRemovedView:
        """Removes an attribute and files an `attribute_removed` entry with its last value
        and the reason in the case of the attribute's owner. The attribute's history stays
        in the case; a later `set_attribute` with the same name creates it anew.

        A name that matches no attribute there is refused with `attribute_not_found`. A
        `task` token removes attributes.
        """
        async with runtime.call() as (session, actor):
            owner = await areas_service.get_owner(session, key)

            async def remove() -> AttributeRemovedView:
                entry = await attributes_service.remove_attribute(
                    session, owner, actor=actor, name=name, reason=reason
                )
                return attribute_removed(entry, project_key=owner_name(owner))

            return await Once.of(remove_attribute, session, actor, idempotency_key).run(
                result=AttributeRemovedView,
                request={"project": owner_name(owner), "name": name.lower(), "reason": reason},
                build=remove,
            )
