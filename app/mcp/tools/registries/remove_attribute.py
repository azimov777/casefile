"""Инструмент `remove_attribute`: снять атрибут проекта с причиной."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.db.models.entry import Entry
from app.mcp.arguments import IdempotencyKeyArg, ProjectKeyArg
from app.mcp.idempotency import Once
from app.mcp.tools.registries.arguments import AttributeNameArg
from app.mcp.toolset import FILING, Toolset
from app.services import attributes as attributes_service
from app.services import projects as projects_service

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
    """Removed project attribute, by the entry that records the removal; the entry in
    full is returned by `read_project_entries`.
    """

    project_key: str
    name: str = Field(description="Name as it was stored")
    no: int = Field(description="Number of the `attribute_removed` entry in the project's case")


def attribute_removed(entry: Entry, *, project_key: str) -> AttributeRemovedView:
    """Ответ `remove_attribute`: имя снятого атрибута и номер записи о снятии."""
    return AttributeRemovedView(project_key=project_key, name=entry.payload["name"], no=entry.no)


def register(tools: Toolset) -> None:
    """Объявляет `remove_attribute` в наборе `task`."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def remove_attribute(
        key: ProjectKeyArg,
        name: AttributeNameArg,
        reason: AttributeRemovalReasonArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> AttributeRemovedView:
        """Removes a project attribute and files an `attribute_removed` entry in the
        project's case with its last value and the reason. The attribute's history stays
        in the case; a later `set_attribute` with the same name creates it anew.

        A name that matches no attribute of the project is refused with
        `attribute_not_found`. A `task` token removes attributes.
        """
        async with runtime.call() as (session, actor):
            project = await projects_service.get_project(session, key)

            async def remove() -> AttributeRemovedView:
                entry = await attributes_service.remove_attribute(
                    session, project, actor=actor, name=name, reason=reason
                )
                return attribute_removed(entry, project_key=project.key)

            return await Once.of(remove_attribute, session, actor, idempotency_key).run(
                result=AttributeRemovedView,
                request={"project": project.key, "name": name.lower(), "reason": reason},
                build=remove,
            )
