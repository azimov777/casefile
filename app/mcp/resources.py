"""Ресурсы MCP: справочная информация, которую агент читает, а не вызывает.

Разница с инструментами не в данных, а в назначении. Инструмент — действие, у него есть
аргументы и последствия; ресурс — то, что клиент может подложить в контекст один раз и
не звать снова. Поэтому здесь список очередей, словарь статусов и карточка «кто я»: то,
что меняется редко и нужно почти в каждом рассуждении.

Инбокс — ресурс по другой причине. Он адресуется ключом актора (`tracker://inbox/alice`)
и служит **адресом подписки**: сервер публикует по нему `resources/updated`, когда в
инбоксе что-то появилось (`app/mcp/push.py`). Читать его можно только свой: лента — это
рабочая очередь конкретного актора, и вычитать её со стороны значило бы отметить
прочитанным то, чего адресат не видел.
"""

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.core.config import get_settings
from app.core.errors import PermissionDeniedError
from app.db.pagination import MAX_PAGE_SIZE
from app.domain.catalogs import CatalogKind
from app.mcp import views
from app.mcp.push import inbox_uri
from app.mcp.runtime import Runtime
from app.services import catalogs as catalogs_service
from app.services import notifications as notifications_service
from app.services import queues as queues_service

MIME_TYPE = "application/json"


def register(server: MCPServer, runtime: Runtime) -> None:
    """Регистрирует ресурсы трекера."""

    @server.resource(
        "tracker://queues",
        name="queues",
        description=(
            "Queues of this installation with their defaults. A queue owns its process: "
            "its own issue types, statuses and workflows"
        ),
        mime_type=MIME_TYPE,
    )
    async def queues() -> str:
        async with runtime.read() as (session, actor):
            page = await queues_service.list_queues(session, initiator=actor, limit=MAX_PAGE_SIZE)
            return _json({"queues": [views.queue(item) for item in page.items]})

    @server.resource(
        "tracker://statuses",
        name="statuses",
        description=(
            "Status dictionary: reference, display name and category (`new`, "
            "`in_progress`, `done`). Boards, project progress and automation rely on "
            "the category, not on the name"
        ),
        mime_type=MIME_TYPE,
    )
    async def statuses() -> str:
        async with runtime.read() as (session, actor):
            page = await catalogs_service.list_entries(
                session,
                CatalogKind.STATUS,
                initiator=actor,
                is_active=True,
                limit=MAX_PAGE_SIZE,
            )
            return _json({"statuses": [views.catalog_entry(item) for item in page.items]})

    @server.resource(
        "tracker://me",
        name="me",
        description="The actor behind the API token: who the agent acts as",
        mime_type=MIME_TYPE,
    )
    async def me() -> str:
        async with runtime.read() as (_, actor):
            return _json(
                {
                    "key": actor.key,
                    "display_name": actor.display_name,
                    "type": actor.type.value,
                    "inbox_resource": inbox_uri(actor.key),
                }
            )

    @server.resource(
        "tracker://inbox/{actor_key}",
        name="inbox",
        description=(
            "Unread notifications of one actor. Subscribe to this URI to be told when "
            "something lands in the inbox; the notification carries no content, so read "
            "the feed with `list_notifications` and mark it with "
            "`mark_notifications_read` — the read mark is shared between both channels"
        ),
        mime_type=MIME_TYPE,
    )
    async def inbox(actor_key: str) -> str:
        settings = get_settings()
        async with runtime.read() as (session, actor):
            if actor_key != actor.key:
                # Чужой инбокс не читается вовсе — ни владельцем, ни агентом. Ошибка, а
                # не пустая выдача: пустая лента чужого актора неотличима от своей.
                raise PermissionDeniedError(
                    message="An inbox can only be read by the actor it belongs to",
                    details={"requested": actor_key, "actor": actor.key},
                )
            page = await notifications_service.list_notifications(
                session,
                initiator=actor,
                is_read=False,
                limit=settings.mcp_page_size,
            )
            return _json(
                {
                    "actor": actor.key,
                    "unread": [views.notification(item) for item in page.items],
                    "has_more": page.next_cursor is not None,
                }
            )


def _json(payload: dict[str, Any]) -> str:
    """Тело ресурса. Компактный JSON: отступы здесь — это контекст агента, потраченный зря."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
