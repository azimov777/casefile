"""Одноразовые ссылки на файлы: байты идут мимо модели, по HTTP, командой `curl`.

Решение владельца TRK~8#11 (вариант А): файл не передаётся текстом вовсе — ни аргументом, ни
результатом инструмента. Инструмент выдаёт **ссылку** на адрес MCP-сервера установки, а агент
гонит байты своей командной строкой: `curl -T <путь> '<ссылка>'` и
`curl -o <путь> '<ссылка>'`. В контексте модели остаются ссылка и короткий ответ «загружено».
Агент без командной строки (чат Claude Desktop, claude.ai) файлы не загружает — запасного пути
нет.

## Ссылка — сама пропуск

У `curl` агента токена нет, поэтому вход проверяет секрет в адресе: длинный случайный, на
одно использование, живёт `LINK_TTL`, привязан к тому, кто его взял (автор записи файла —
владелец токена, выдавшего ссылку), и к одному действию: загрузке в проект, замене файла или
выдаче файла. Ссылка сгорает на **первом же** запросе, удачном или нет: после отказа
(`file_too_large`, `project_archived`) агент берёт новую. Повтор, просрочка и неизвестный
секрет — отказ (`410` и `404`), тело — JSON с `code`, как у остальных ошибок трекера.

## Хранилище ссылок — память процесса

Таблицы нет: срок жизни — минуты, а перезапуск службы MCP обрывает передачу, но не портит
данные — агент берёт ссылку заново. Служба MCP — один процесс (`app/mcp/__main__.py`); при
нескольких процессах ссылка, взятая в одном, не открылась бы в другом, и тогда хранилище надо
переносить в базу. Не больше `MAX_OPEN_LINKS` живых ссылок: сверх этого выдача отказывает.

## Что ссылка не делает

Не подшивает записей в дело и не пишет в ленту: файл — строка установки (TRK#216 стоит на
сценариях `app/services/files.py`, которые зовёт и этот маршрут, и позже REST). Прикладывает
файл к записи агент отдельно, аргументом `files` инструмента записи.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.errors import (
    FileLinkExpiredError,
    FileLinkNotFoundError,
    FileLinkUsedError,
    FileLinkWrongKindError,
    FileTooLargeError,
    TooManyFileLinksError,
)
from app.mcp.runtime import Runtime
from app.services import files as files_service
from app.services.auth import Actor

__all__ = ["LINK_TTL", "FileLink", "FileLinks", "LinkKind", "register_file_routes"]

#: Сколько живёт ссылка: на загрузку файла в пределе установки хватает с запасом.
LINK_TTL = timedelta(minutes=10)

#: Потолок живых ссылок: выдача требует токена, но забытые ссылки не должны копиться вечно.
MAX_OPEN_LINKS = 1000

#: Сгоревшая и просроченная ссылка помнится ещё час, чтобы отличать «уже использована» и
#: «просрочена» от «такой не выдавали»; потом память чистится.
_REMEMBERED = timedelta(hours=1)

#: Длина секрета в байтах: `token_urlsafe(32)` — 43 знака, 256 бит.
_SECRET_BYTES = 32

UPLOAD_PATH = "/files/upload"
DOWNLOAD_PATH = "/files/download"


class LinkKind(StrEnum):
    """На что открывает ссылка."""

    UPLOAD = "upload"
    REPLACE = "replace"
    DOWNLOAD = "download"


@dataclass(slots=True)
class FileLink:
    """Выданная ссылка: что открывает, чьим именем действует и до какого часа."""

    secret: str
    kind: LinkKind
    actor: Actor
    expires_at: datetime
    project: str | None = None
    file_id: UUID | None = None
    name: str | None = None
    mime_type: str | None = None
    used: bool = False


class FileLinks:
    """Память выданных ссылок процесса: выдать, предъявить один раз."""

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._links: dict[str, FileLink] = {}
        self._now = now or (lambda: datetime.now(UTC))

    def issue(
        self,
        kind: LinkKind,
        actor: Actor,
        *,
        project: str | None = None,
        file_id: UUID | None = None,
        name: str | None = None,
        mime_type: str | None = None,
    ) -> FileLink:
        """Выдаёт новую ссылку. Сверх `MAX_OPEN_LINKS` живых — отказ `too_many_file_links`."""
        self._forget()
        now = self._now()
        if sum(1 for item in self._links.values() if not item.used and item.expires_at > now) >= (
            MAX_OPEN_LINKS
        ):
            raise TooManyFileLinksError
        link = FileLink(
            secret=secrets.token_urlsafe(_SECRET_BYTES),
            kind=kind,
            actor=actor,
            expires_at=now + LINK_TTL,
            project=project,
            file_id=file_id,
            name=name,
            mime_type=mime_type,
        )
        self._links[link.secret] = link
        return link

    def take(self, secret: str, *kinds: LinkKind) -> FileLink:
        """Предъявляет ссылку: сжигает её и отдаёт. Отказ — исключение со статусом HTTP.

        Сгорает и ссылка не того вида: предъявление чужого вида — тоже использование.
        """
        link = self._links.get(secret)
        if link is None:
            raise FileLinkNotFoundError
        if link.used:
            raise FileLinkUsedError
        link.used = True
        if link.expires_at <= self._now():
            raise FileLinkExpiredError
        if link.kind not in kinds:
            raise FileLinkWrongKindError
        return link

    def _forget(self) -> None:
        horizon = self._now() - _REMEMBERED
        for secret in [s for s, item in self._links.items() if item.expires_at <= horizon]:
            del self._links[secret]


def link_origin(settings: Settings) -> str:
    """Адрес службы MCP для клиента снаружи — без пути эндпоинта MCP.

    Тот же адрес, по которому агент подключён (`TRACKER_MCP_PUBLIC_URL` или локальный по
    умолчанию), поэтому ссылка открывается там же, где открывается MCP. Путь `mcp_path` в
    конце отбрасывается; префикс прокси перед ним остаётся.
    """
    parts = urlsplit(settings.effective_mcp_public_url)
    path = parts.path.rstrip("/")
    suffix = settings.mcp_path.rstrip("/")
    if suffix and path.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def link_url(settings: Settings, link: FileLink) -> str:
    """Готовый адрес ссылки."""
    base = DOWNLOAD_PATH if link.kind is LinkKind.DOWNLOAD else UPLOAD_PATH
    return f"{link_origin(settings)}{base}/{link.secret}"


# --- Маршруты -------------------------------------------------------------------------


def register_file_routes(
    server: MCPServer, *, runtime: Runtime, settings: Settings, links: FileLinks
) -> None:
    """Подключает к службе MCP загрузку (`PUT`) и скачивание (`GET`) по одноразовой ссылке.

    Маршруты стоят рядом с эндпоинтом MCP и без входа по токену, как `/health`: пропуск —
    секрет в адресе.
    """

    @server.custom_route(f"{UPLOAD_PATH}/{{secret}}", methods=["PUT"], include_in_schema=False)
    async def upload(request: Request) -> Response:
        try:
            link = links.take(request.path_params["secret"], LinkKind.UPLOAD, LinkKind.REPLACE)
            data = await _body(request, settings.file_max_bytes)
            async with runtime.sessions() as session:
                if link.kind is LinkKind.UPLOAD:
                    assert link.project is not None and link.name is not None
                    card = await files_service.upload_file(
                        session,
                        actor=link.actor,
                        project=link.project,
                        name=link.name,
                        data=data,
                        mime_type=link.mime_type,
                    )
                else:
                    assert link.file_id is not None
                    card = await files_service.replace_file(
                        session,
                        link.file_id,
                        actor=link.actor,
                        data=data,
                        name=link.name,
                        mime_type=link.mime_type,
                    )
        except AppError as error:
            return _refusal(error)
        return JSONResponse(
            {
                "id": str(card.id),
                "name": card.name,
                "mime_type": card.mime_type,
                "size_bytes": card.size_bytes,
                "sha256": card.sha256,
            }
        )

    @server.custom_route(f"{DOWNLOAD_PATH}/{{secret}}", methods=["GET"], include_in_schema=False)
    async def download(request: Request) -> Response:
        try:
            link = links.take(request.path_params["secret"], LinkKind.DOWNLOAD)
            assert link.file_id is not None
            async with runtime.sessions() as session:
                opened = await files_service.open_file(session, link.file_id, actor=link.actor)
        except AppError as error:
            return _refusal(error)
        return Response(
            opened.data,
            media_type=opened.card.mime_type,
            headers={
                "Content-Disposition": _attachment(opened.card.name),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )


async def _body(request: Request, limit: int) -> bytes:
    """Тело запроса как есть, не больше предела установки.

    Предел проверяется дважды: по `Content-Length`, чтобы отказать, не читая, и по ходу
    чтения, если заголовка нет или он соврал. Оба отказа — `file_too_large`, как у сценария.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large(int(declared), limit)
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > limit:
            raise _too_large(len(received), limit)
    return bytes(received)


def _too_large(size: int, limit: int) -> AppError:
    return FileTooLargeError(details={"size": size, "max_bytes": limit}, status_code=413)


def _refusal(error: AppError) -> JSONResponse:
    body: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.details:
        body["details"] = error.details
    return JSONResponse(body, status_code=error.status_code)


def _attachment(name: str) -> str:
    """`Content-Disposition` с именем файла: ASCII-запасное и полное в `filename*`."""
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
