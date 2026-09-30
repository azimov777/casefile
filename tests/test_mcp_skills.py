"""Скил Casefile по SEP-2640: объявление, `skills/list`, `skills/get`, ресурсы.

Ходим настоящим HTTP-запросом через ASGI на обеих эпохах протокола: сито версий SDK
срезает `capabilities.extensions` в рукопожатии старой эпохи, и сломать объявление
можно сборкой сервера, ничего не трогая в самом расширении (`docs/notes/mcp.md`).
"""

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer

from app.mcp.skills import MAX_SKILL_FILES, SKILLS_DIR, SKILLS_EXTENSION, CasefileSkills

SKILL_URI = "skill://casefile/SKILL.md"
ACCEPT = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
CLIENT = {"name": "tests", "version": "0"}
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": CLIENT,
    "io.modelcontextprotocol/clientCapabilities": {},
}

type Call = Callable[[str, dict[str, Any]], Any]


def _body(response: Any) -> dict[str, Any]:
    text: str = response.text
    if "data:" in text:
        text = [line[5:] for line in text.splitlines() if line.startswith("data:")][-1]
    return json.loads(text)  # type: ignore[no-any-return]


@asynccontextmanager
async def _era(server: MCPServer, era: str, secret: str) -> AsyncIterator[Call]:
    """`call(method, params)` -> (HTTP-статус, тело JSON-RPC) на выбранной эпохе."""
    application = server.streamable_http_app()
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application), base_url="http://localhost:8100"
        ) as client,
    ):
        # Транспорт требует действующий токен (`app/mcp/oauth.py`); чей — скилу всё равно.
        headers = dict(ACCEPT) | {"authorization": f"Bearer {secret}"}
        counter = 0

        if era == "legacy":
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": CLIENT,
                    },
                },
            )
            handshake = _body(response)
            headers |= {
                "mcp-session-id": response.headers["mcp-session-id"],
                "mcp-protocol-version": "2025-11-25",
            }
            await client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

        async def call(method: str, params: dict[str, Any]) -> Any:
            nonlocal counter
            counter += 1
            if method == "initialize":
                return 200, handshake
            extra = {}
            payload = dict(params)
            if era == "modern":
                extra = {"mcp-protocol-version": "2026-07-28", "mcp-method": method}
                if "uri" in params and method == "resources/read":
                    extra["mcp-name"] = params["uri"]
                payload["_meta"] = MODERN_META
            reply = await client.post(
                "/mcp",
                headers=headers | extra,
                json={"jsonrpc": "2.0", "id": 100 + counter, "method": method, "params": payload},
            )
            return reply.status_code, _body(reply)

        yield call


def _capabilities(reply: dict[str, Any]) -> dict[str, Any]:
    return reply["result"]["capabilities"]  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("era", "method", "params"),
    [
        ("legacy", "initialize", {}),
        ("modern", "server/discover", {}),
    ],
)
async def test_both_eras_declare_the_extension_and_resources(
    mcp_server: MCPServer, main_secret: str, era: str, method: str, params: dict[str, Any]
) -> None:
    async with _era(mcp_server, era, main_secret) as call:
        status, reply = await call(method, params)

    assert status == 200, reply
    capabilities = _capabilities(reply)
    assert capabilities["extensions"][SKILLS_EXTENSION] == {}
    assert "resources" in capabilities


@pytest.mark.parametrize("era", ["legacy", "modern"])
async def test_skills_list_matches_the_file_on_disk(
    mcp_server: MCPServer, main_secret: str, era: str
) -> None:
    source = SKILLS_DIR / "casefile" / "SKILL.md"
    raw = source.read_bytes()
    front = yaml.safe_load(raw.decode().split("---", 2)[1])

    async with _era(mcp_server, era, main_secret) as call:
        status, listed = await call("skills/list", {})
        _, read = await call("resources/read", {"uri": SKILL_URI})

    assert status == 200, listed
    (skill,) = listed["result"]["skills"]
    assert skill["uri"] == SKILL_URI
    assert skill["frontmatter"] == front
    assert front["name"] == "casefile"
    by_uri = {item["uri"]: item for item in skill["resources"]}
    manifest = by_uri[SKILL_URI]
    assert manifest["size"] == len(raw)
    assert manifest["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    (content,) = read["result"]["contents"]
    assert content["text"].encode() == raw
    assert len(content["text"].encode()) == manifest["size"]


@pytest.mark.parametrize("era", ["legacy", "modern"])
async def test_skills_get_returns_the_skill_and_refuses_an_unknown_uri(
    mcp_server: MCPServer, main_secret: str, era: str
) -> None:
    async with _era(mcp_server, era, main_secret) as call:
        _, found = await call("skills/get", {"uri": SKILL_URI})
        status, missing = await call("skills/get", {"uri": "skill://nope/SKILL.md"})

    assert found["result"]["skill"]["uri"] == SKILL_URI
    assert missing["error"]["code"] == -32602
    assert status == (400 if era == "modern" else 200)


async def test_cache_fields_appear_only_on_the_modern_era(
    mcp_server: MCPServer, main_secret: str
) -> None:
    async with _era(mcp_server, "modern", main_secret) as call:
        _, modern = await call("skills/list", {})
    async with _era(mcp_server, "legacy", main_secret) as call:
        _, legacy = await call("skills/list", {})

    assert modern["result"]["cacheScope"] == "public"
    assert modern["result"]["resultType"] == "complete"
    assert modern["result"]["ttlMs"] > 0
    assert "ttlMs" not in legacy["result"]
    assert "cacheScope" not in legacy["result"]


async def test_the_skill_is_also_an_ordinary_resource(
    mcp_server: MCPServer, main_secret: str
) -> None:
    async with _era(mcp_server, "legacy", main_secret) as call:
        _, listed = await call("resources/list", {})

    assert SKILL_URI in {item["uri"] for item in listed["result"]["resources"]}


def test_there_is_one_skills_directory_for_the_plugin_and_the_server() -> None:
    """Плагин и сервер читают один каталог: копии скила разошлись бы молча."""
    repository = Path(__file__).resolve().parents[1]
    assert SKILLS_DIR.samefile(repository / "skills")
    found = SKILLS_DIR.glob("*/SKILL.md")
    manifests = sorted(path.relative_to(repository).as_posix() for path in found)
    assert manifests == ["skills/casefile/SKILL.md"]


def test_a_skill_over_the_sep_limits_is_refused_at_load(tmp_path: Path) -> None:
    """SEP-2640, «Limits»: больше 512 записей или 16 МиБ сервер не отдаёт."""
    skill = tmp_path / "big"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: big\ndescription: d\n---\n")
    for number in range(MAX_SKILL_FILES):
        (skill / f"{number}.md").write_text("x")

    with pytest.raises(ValueError, match="exceed the SEP-2640 limits"):
        CasefileSkills(tmp_path)
