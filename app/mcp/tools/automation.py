"""Инструменты автоматики: посмотреть правила, настроить их, запустить макрос.

Правила пишутся кодом и заводить их через MCP нельзя — строка без объявления это
правило, которое нечем выполнить. Наружу отдана ровно настройка: включить, выключить,
привязать к очереди, задать параметры.

Своей проверки параметров здесь нет. Схема у каждого правила своя и объявлена в его
модуле; проверяет её `update_rule` той же моделью, которой правило пользуется при
выполнении. Вторая проверка «попроще» разошлась бы с настоящей, и правило запускалось бы
с параметрами, которых не приняло сохранение (выявлено в задаче 13).
"""

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.core.config import get_settings
from app.core.sentinels import UNSET, unset_field
from app.db.pagination import MAX_PAGE_SIZE
from app.mcp import refs, views
from app.mcp.runtime import Runtime
from app.services import automation as automation_service


class RuleChangesInput(BaseModel):
    """Настройка правила: применяются только переданные поля.

    `params` заменяются целиком, а не сливаются с текущими: слияние не давало бы
    способа снять значение. Проверяются они схемой самого правила (`params_schema` в
    ответе `list_automation_rules`), поэтому мусор отвергается при сохранении, а не
    всплывает падением в фоне.
    """

    model_config = ConfigDict(extra="forbid")

    is_enabled: bool = unset_field(description="Whether the rule is allowed to run")
    queue: str | None = unset_field(
        description="Queue key to limit the rule to, or null to let it work everywhere"
    )
    params: dict[str, JsonValue] = unset_field(
        description="Rule settings, validated against its own `params_schema`"
    )


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует инструменты автоматики."""

    @server.tool()
    async def list_automation_rules(
        queue: Annotated[
            str | None, Field(description="Queue key: rules limited to this queue only")
        ] = None,
        is_enabled: Annotated[
            bool | None, Field(description="Filter by whether the rule is on")
        ] = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE, description="Page size")] = None,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page")
        ] = None,
    ) -> dict[str, Any]:
        """List automation rules with their declaration and their settings.

        `kind` says how a rule runs: `trigger` reacts to events, `scheduled` works by
        the clock, `macro` is started by hand — those are the ones `run_macro` accepts.
        `params_schema` is the JSON Schema of `params`; build the settings by it.

        A rule whose code was removed stays in the list with `is_available: false`: it
        may still be marked enabled, and hiding it would leave «why does it not fire»
        unanswered.
        """
        settings = get_settings()
        async with runtime.call() as (session, actor):
            page = await automation_service.list_rules(
                session,
                initiator=actor,
                queue=await refs.queue(session, queue) if queue is not None else None,
                is_enabled=is_enabled,
                limit=limit or settings.mcp_page_size,
                cursor=cursor,
            )
            return views.page(
                (views.rule(item) for item in page.items), next_cursor=page.next_cursor
            )

    @server.tool()
    async def configure_automation_rule(
        rule: Annotated[str, Field(description="Rule key from `list_automation_rules`")],
        changes: RuleChangesInput,
    ) -> dict[str, Any]:
        """Switch an automation rule on or off and set it up. Mutating.

        Takes effect immediately, without restarting anything. Parameters are checked
        against the rule's own schema: a rejected value comes back naming the parameter,
        so fix it by the error instead of guessing.

        A rule without a declaration in the code cannot be configured at all — there is
        nothing to validate its parameters with.
        """
        given = changes.model_dump(exclude_unset=True)
        async with runtime.call() as (session, actor):
            entry = await automation_service.get_rule(session, rule)
            view = await automation_service.update_rule(
                session,
                entry,
                initiator=actor,
                is_enabled=given.get("is_enabled", UNSET),
                queue=(
                    await refs.optional_queue(session, given["queue"])
                    if "queue" in given
                    else UNSET
                ),
                params=given.get("params", UNSET),
            )
            return views.rule(view)

    @server.tool()
    async def run_macro(
        rule: Annotated[str, Field(description="Key of a rule whose `kind` is `macro`")],
        issue: Annotated[str, Field(description="Issue key to run the macro on")],
        params: Annotated[
            dict[str, JsonValue] | None,
            Field(description="One-off parameters on top of the saved ones"),
        ] = None,
    ) -> dict[str, Any]:
        """Run a macro rule on an issue. Mutating: the rule changes the tracker.

        Answers with the journal entry. A failure **inside** the rule arrives here as
        `status: failed` with the reason — it is a result, not a broken call: raising
        would roll the transaction back together with the journal entry, and the only
        trace of the failed macro would disappear.

        Refusals **before** the run are errors: the rule is off
        (`automation_rule_disabled`), it is not a macro
        (`automation_rule_kind_mismatch`), the issue belongs to another queue
        (`automation_rule_out_of_scope`).
        """
        async with runtime.call() as (session, actor):
            target = await refs.issue(session, issue)
            outcome = await automation_service.run_macro(
                session,
                rule,
                issue=target,
                initiator=actor,
                params=params,
            )
            return views.run(outcome.run)
