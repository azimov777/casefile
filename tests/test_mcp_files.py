"""Файлы через MCP (TRK-737): одноразовая ссылка на загрузку и скачивание, изображение
содержимым `image`, вложения к записям агента. Base64 нет ни в одном аргументе (TRK~8#11).

Ядро файлов проверяет `tests/test_files.py`; здесь — вход агента: инструменты, маршруты
`PUT`/`GET` по ссылке и их отказы. Ссылка идёт настоящим HTTP поверх ASGI, как клиент
`curl` в бою.
"""

import base64
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp_types import ImageContent

from app.core.config import Settings, get_settings
from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.authors import Author, AuthorKind
from app.domain.errors import FileLinkExpiredError, FileLinkNotFoundError, FileLinkUsedError
from app.domain.project_access import ProjectAccess
from app.mcp import file_links
from app.mcp.file_links import FileLinks, LinkKind, link_origin, register_file_routes
from app.mcp.runtime import Runtime
from app.services.auth import Actor
from conftest import MCP_BASE_URL, call, refuse, tool_text
from mcp import ClientSession

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4  # байты, не похожие на текст
PDF = b"%PDF-1.7\n" + bytes(range(255, 0, -1)) * 8

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def served(server: MCPServer, secret: str) -> AsyncIterator[tuple[ClientSession, Any]]:
    """Сессия клиента MCP и HTTP-клиент `curl` на одном приложении.

    Токена у второго клиента нет: ссылка — сама пропуск.
    """
    application = server.streamable_http_app()
    async with application.router.lifespan_context(application):
        transport = httpx2.ASGITransport(application)
        agent = httpx2.AsyncClient(
            transport=transport,
            base_url=MCP_BASE_URL,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=60,
        )
        curl = httpx2.AsyncClient(transport=transport, base_url=MCP_BASE_URL, timeout=60)
        async with (
            agent,
            curl,
            streamable_http_client(f"{MCP_BASE_URL}/mcp", http_client=agent) as streams,
        ):
            read, write = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session, curl


def path_of(url: str) -> str:
    """Путь ссылки: клиент `curl` в тесте ходит на тот же приложение, без сети."""
    return "/" + url.split("/", 3)[3]


async def put(curl: Any, link: dict[str, Any], data: bytes) -> Any:
    return await curl.put(path_of(link["url"]), content=data)


async def stored(
    session: ClientSession, curl: Any, name: str, data: bytes, mime_type: str | None = None
) -> dict[str, Any]:
    """Загружает файл в проект `TRK` по ссылке и отдаёт ответ загрузки."""
    arguments: dict[str, Any] = {"project": "TRK", "name": name}
    if mime_type is not None:
        arguments["mime_type"] = mime_type
    link = await call(session, "request_file_upload", **arguments)
    response = await put(curl, link, data)
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_upload_link_stores_the_file_and_is_spent_by_the_first_request(
    mcp_server: MCPServer, main_secret: str, project: Project
) -> None:
    """Загрузка по ссылке кладёт файл в проект; повтор той же ссылки — отказ, файл один."""
    async with served(mcp_server, main_secret) as (session, curl):
        link = await call(session, "request_file_upload", project="TRK", name="report.pdf")
        assert "curl" in link["command"] and "-T" in link["command"]
        assert link["max_bytes"] == get_settings().file_max_bytes

        first = await put(curl, link, PDF)
        assert first.status_code == 200
        body = first.json()
        assert body["name"] == "report.pdf"
        assert body["mime_type"] == "application/pdf"  # угадан по имени
        assert body["size_bytes"] == len(PDF)
        assert body["sha256"] == hashlib.sha256(PDF).hexdigest()

        again = await put(curl, link, PDF)
        assert again.status_code == 410
        assert again.json()["code"] == "file_link_used"

        listed = await call(session, "list_files", project="TRK")
        assert [item["id"] for item in listed["items"]] == [body["id"]]
        assert listed["items"][0]["added_by"] == "owner"


async def test_an_expired_or_unknown_link_is_refused(
    mcp_server: MCPServer,
    main_secret: str,
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Просроченная ссылка — `410 file_link_expired`; чужой секрет — `404`; файла нет."""
    async with served(mcp_server, main_secret) as (session, curl):
        monkeypatch.setattr(file_links, "LINK_TTL", timedelta(seconds=-1))
        expired = await call(session, "request_file_upload", project="TRK", name="late.bin")
        response = await put(curl, expired, b"x")
        assert response.status_code == 410
        assert response.json()["code"] == "file_link_expired"

        unknown = await curl.put("/files/upload/not-a-link", content=b"x")
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "file_link_not_found"

        listed = await call(session, "list_files")
        assert listed["items"] == []


async def test_a_link_opens_only_its_own_action(
    mcp_server: MCPServer, main_secret: str, project: Project
) -> None:
    """Секрет скачивания в адресе загрузки (и наоборот) — отказ, и ссылка сгорает."""
    async with served(mcp_server, main_secret) as (session, curl):
        card = await stored(session, curl, "report.pdf", PDF)
        result = await session.call_tool("read_file", {"file": card["id"]})
        download = json.loads(tool_text(result))
        secret = download["url"].rsplit("/", 1)[1]

        wrong = await curl.put(f"/files/upload/{secret}", content=b"x")
        assert wrong.status_code == 405
        assert wrong.json()["code"] == "file_link_wrong_kind"
        spent = await curl.get(path_of(download["url"]))
        assert spent.status_code == 410

        upload = await call(session, "request_file_upload", project="TRK", name="a.bin")
        secret = upload["url"].rsplit("/", 1)[1]
        refused = await curl.get(f"/files/download/{secret}")
        assert refused.status_code == 405
        assert refused.json()["code"] == "file_link_wrong_kind"


async def test_a_file_larger_than_the_limit_is_refused_and_nothing_is_stored(
    mcp_server: MCPServer,
    main_secret: str,
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сверх предела — `413 file_too_large` с размером и пределом, и по заголовку длины, и по
    ходу чтения; файл не сохраняется."""
    monkeypatch.setattr(get_settings(), "file_max_bytes", 100)
    async with served(mcp_server, main_secret) as (session, curl):
        link = await call(session, "request_file_upload", project="TRK", name="big.bin")
        assert link["max_bytes"] == 100
        response = await put(curl, link, bytes(101))
        assert response.status_code == 413
        assert response.json()["code"] == "file_too_large"
        assert response.json()["details"]["max_bytes"] == 100

        streamed = await call(session, "request_file_upload", project="TRK", name="big2.bin")

        async def chunks() -> AsyncIterator[bytes]:
            yield bytes(60)
            yield bytes(60)

        response = await curl.put(path_of(streamed["url"]), content=chunks())
        assert response.status_code == 413
        assert (await call(session, "list_files"))["items"] == []


async def test_an_image_comes_as_image_content_and_marks_the_file_opened(
    mcp_server: MCPServer, main_secret: str, project: Project
) -> None:
    """PNG отдаётся содержимым `image` после карточки; байты в нём — те же, что загружены."""
    async with served(mcp_server, main_secret) as (session, curl):
        card = await stored(session, curl, "scheme.png", PNG)
        result = await session.call_tool("read_file", {"file": card["id"]})
        assert not result.is_error
        kinds = [block.type for block in result.content]
        assert kinds == ["text", "image"]
        image = next(block for block in result.content if isinstance(block, ImageContent))
        assert image.mime_type == "image/png"
        assert base64.b64decode(image.data) == PNG
        text = json.loads(tool_text(result))
        assert text["id"] == card["id"]
        assert "url" not in text and "command" not in text
        assert (await call(session, "list_files"))["items"][0]["last_opened_at"]
        assert result.structured_content is not None
        assert result.structured_content["id"] == card["id"]


async def test_a_document_comes_as_a_card_and_a_download_link_without_bytes(
    mcp_server: MCPServer, main_secret: str, project: Project
) -> None:
    """PDF — карточка и ссылка `curl -o`, без байтов; скачивание по ссылке даёт те же байты и
    ставит отметку открытия, повтор ссылки — отказ."""
    async with served(mcp_server, main_secret) as (session, curl):
        card = await stored(session, curl, "report.pdf", PDF)
        result = await session.call_tool("read_file", {"file": card["id"]})
        assert [block.type for block in result.content] == ["text"]
        read = json.loads(tool_text(result))
        assert read["sha256"] == hashlib.sha256(PDF).hexdigest()
        assert "last_opened_at" not in (await call(session, "list_files"))["items"][0]
        assert "-o" in read["command"]
        assert base64.b64encode(PDF).decode() not in tool_text(result)

        downloaded = await curl.get(path_of(read["url"]))
        assert downloaded.status_code == 200
        assert downloaded.content == PDF
        assert downloaded.headers["content-type"] == "application/pdf"
        assert "attachment" in downloaded.headers["content-disposition"]

        again = await curl.get(path_of(read["url"]))
        assert again.status_code == 410
        assert again.json()["code"] == "file_link_used"

        listed = await call(session, "list_files")
        assert listed["items"][0]["last_opened_at"]


async def test_replacing_keeps_the_id_and_a_deleted_file_leaves_a_tombstone(
    mcp_server: MCPServer, main_secret: str, project: Project
) -> None:
    """Замена кладёт новые байты под тот же id; удаление оставляет надгробие, повтор и замена
    удалённого — отказ."""
    async with served(mcp_server, main_secret) as (session, curl):
        card = await stored(session, curl, "report.pdf", PDF)
        link = await call(session, "request_file_replace", file=card["id"], name="final.pdf")
        replaced = await put(curl, link, PDF + b"!")
        assert replaced.status_code == 200
        assert replaced.json()["id"] == card["id"]
        assert replaced.json()["name"] == "final.pdf"
        assert replaced.json()["size_bytes"] == len(PDF) + 1

        deleted = await call(session, "delete_file", file=card["id"])
        assert deleted["deleted_at"] and deleted["id"] == card["id"]
        assert "file_deleted" in await refuse(session, "delete_file", file=card["id"])
        assert "file_deleted" in await refuse(session, "request_file_replace", file=card["id"])
        assert (await call(session, "list_files"))["items"] == []
        everything = await call(session, "list_files", include_deleted=True)
        assert [item["id"] for item in everything["items"]] == [card["id"]]
        assert everything["items"][0]["deleted_by"] == "owner"

        read = await session.call_tool("read_file", {"file": card["id"]})
        assert not read.is_error
        assert json.loads(tool_text(read))["deleted_at"]


async def test_an_entry_of_the_agent_attaches_files_and_shows_them_then_the_tombstone(
    mcp_server: MCPServer, main_secret: str, project: Project, task: Task
) -> None:
    """`add_entry` с `files`: запись показывает карточки вложений в порядке; после удаления —
    надгробие. Запись без вложений поля `files` не несёт."""
    key = task.key
    async with served(mcp_server, main_secret) as (session, curl):
        first = await stored(session, curl, "scheme.png", PNG)
        second = await stored(session, curl, "report.pdf", PDF)

        await call(
            session,
            "add_entry",
            key=key,
            type="artifact",
            title="Схема и отчёт",
            files=[second["id"], first["id"]],
        )
        await call(session, "add_entry", key=key, type="note", title="Без вложений")

        entries = (await call(session, "read_entries", key=key, types=["artifact", "note"]))[
            "items"
        ]
        attached = entries[0]["files"]
        assert [item["id"] for item in attached] == [second["id"], first["id"]]
        assert attached[0]["name"] == "report.pdf" and attached[0]["size_bytes"] == len(PDF)
        assert "deleted_at" not in attached[0]
        assert "files" not in entries[1]

        await call(session, "delete_file", file=first["id"])
        entries = (await call(session, "read_entries", key=key, types=["artifact"]))["items"]
        tombstone = entries[0]["files"][1]
        assert tombstone["deleted_at"] and tombstone["name"] == "scheme.png"

        assert "file_deleted" in await refuse(
            session,
            "add_entry",
            key=key,
            type="note",
            title="Вложение удалённого",
            files=[first["id"]],
        )
        missing = "00000000-0000-4000-8000-000000000000"
        assert "file_not_found" in await refuse(
            session,
            "add_entry",
            key=key,
            type="note",
            title="Вложение несуществующего",
            files=[missing],
        )


async def test_project_entries_questions_and_answers_attach_files(
    mcp_server: MCPServer, main_secret: str, project: Project, task: Task
) -> None:
    """`add_project_entry`, `ask` и `answer` принимают `files`; читаются тем же полем."""
    key = task.key
    async with served(mcp_server, main_secret) as (session, curl):
        card = await stored(session, curl, "scheme.png", PNG)

        await call(
            session,
            "add_project_entry",
            key="TRK",
            type="note",
            title="Схема проекта",
            files=[card["id"]],
        )
        entries = (await call(session, "read_project_entries", key="TRK", types=["note"]))["items"]
        assert [item["id"] for item in entries[-1]["files"]] == [card["id"]]

        asked = await call(
            session,
            "ask",
            key=key,
            addressees=["owner"],
            title="Эта схема верна?",
            files=[card["id"]],
        )
        address = asked["discussion"]
        answered = await call(
            session, "answer", key=address, question_no=asked["no"], body="да", files=[card["id"]]
        )
        discussion = (await call(session, "read_project_entries", key=address))["items"]
        with_files = [item for item in discussion if item.get("files")]
        assert [item["no"] for item in with_files] == [asked["no"], answered["no"]]
        card_view = (await call(session, "list_files"))["items"][0]
        assert card_view["entries"] == 3


async def test_no_tool_takes_file_content_in_an_argument(
    mcp_server: MCPServer, main_secret: str
) -> None:
    """Ни у одного инструмента нет аргумента с содержимым файла (TRK~8#11), а в коде MCP нет
    приёма base64: изображение отдаёт SDK, своих кодировщиков здесь нет."""
    forbidden = {"base64", "bytes", "content", "data", "payload", "file_content", "contents"}
    async with served(mcp_server, main_secret) as (session, _):
        for tool in (await session.list_tools()).tools:
            names = set(tool.input_schema.get("properties", {}))
            assert not names & forbidden, f"{tool.name}: {sorted(names & forbidden)}"

    pattern = re.compile(r"base64|b64decode|b64encode", re.IGNORECASE)
    hits = [
        str(path.relative_to(PROJECT_ROOT))
        for path in (PROJECT_ROOT / "app" / "mcp").rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == [], hits


def test_a_link_is_spent_once_and_forgotten_after_an_hour() -> None:
    """`FileLinks` с подставленными часами: ожидание, сгорание, просрочка, потолок и забвение."""
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    clock = [now]
    links = FileLinks(now=lambda: clock[0])
    actor = Actor(author=Author(kind=AuthorKind.AGENT, signature="claude"))

    link = links.issue(LinkKind.UPLOAD, actor, project="TRK", name="a.bin")
    assert links.take(link.secret, LinkKind.UPLOAD) is link
    with pytest.raises(FileLinkUsedError):
        links.take(link.secret, LinkKind.UPLOAD)

    late = links.issue(LinkKind.DOWNLOAD, actor)
    clock[0] = now + file_links.LINK_TTL + timedelta(seconds=1)
    with pytest.raises(FileLinkExpiredError):
        links.take(late.secret, LinkKind.DOWNLOAD)

    clock[0] = now + file_links.LINK_TTL + timedelta(hours=2)
    links.issue(LinkKind.DOWNLOAD, actor)
    with pytest.raises(FileLinkNotFoundError):
        links.take(late.secret, LinkKind.DOWNLOAD)


def test_the_link_address_is_the_mcp_address_without_the_mcp_path() -> None:
    """Ссылка открывается там же, где агент подключён к MCP: свой адрес и префикс прокси."""
    assert link_origin(Settings(mcp_public_url=None, mcp_port=8100)) == "http://localhost:8100"
    proxied = Settings(mcp_public_url="https://tracker.example.com/casefile/mcp")
    assert link_origin(proxied) == "https://tracker.example.com/casefile"


async def test_a_link_acts_with_the_project_access_of_who_took_it(
    mcp_sessions: Any, project: Project
) -> None:
    """Доступ агента к проектам (TRK-751) действует и на маршрутах ссылок: ссылка, взятая
    агентом, у которого проект закрыт, ничего не загружает и не выдаёт, даже если доступ
    сузили уже после выдачи."""
    server = MCPServer(name="probe")
    links = FileLinks()
    register_file_routes(
        server, runtime=Runtime(sessions=mcp_sessions), settings=get_settings(), links=links
    )
    application = server.streamable_http_app()
    closed = Actor(
        author=Author(kind=AuthorKind.AGENT, signature="narrow"),
        project_access=ProjectAccess.of("only", []),
    )
    async with (
        application.router.lifespan_context(application),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(application), base_url=MCP_BASE_URL
        ) as curl,
    ):
        upload = links.issue(LinkKind.UPLOAD, closed, project="TRK", name="a.bin")
        refused = await curl.put(f"/files/upload/{upload.secret}", content=b"x")
        assert refused.status_code == 403
        assert refused.json()["code"] == "project_not_allowed"

        opened = Actor(author=Author(kind=AuthorKind.AGENT, signature="wide"))
        stored_link = links.issue(LinkKind.UPLOAD, opened, project="TRK", name="b.bin")
        stored = await curl.put(f"/files/upload/{stored_link.secret}", content=b"x")
        assert stored.status_code == 200
        download = links.issue(LinkKind.DOWNLOAD, closed, file_id=uuid.UUID(stored.json()["id"]))
        refused = await curl.get(f"/files/download/{download.secret}")
        assert refused.json()["code"] == "project_not_allowed"


async def test_the_file_tools_refuse_a_project_the_agent_cannot_see(
    mcp_server: MCPServer, main_secret: str, project: Project
) -> None:
    """Инструменты файлов идут через сценарии: закрытый проект не даёт ссылки (проверка на
    сессии вызова, TRK-751) — для людей и общего ключа ограничений нет, поэтому здесь
    проверяется, что вызов с открытым проектом проходит и неизвестный проект отказывает."""
    async with served(mcp_server, main_secret) as (session, _):
        assert "project_not_found" in await refuse(
            session, "request_file_upload", project="NOPE", name="a.bin"
        )
