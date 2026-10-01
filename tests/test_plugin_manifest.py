"""Манифесты плагина `.claude-plugin/`: версия равна версии выпуска (TRK-404, TRK-398#7, #8).

Claude Code без новой `version` отвечает «already at latest» и держит старый `SKILL.md`,
поэтому равенство с `pyproject.toml` держит тест. Плагин несёт скил и коннектор Casefile
(TRK-451): адрес без токена и заголовков, вход агента — OAuth. Файл коннектора лежит в
`.claude-plugin/`, а не в корне: корневой `.mcp.json` подхватил бы Claude Code каждого, кто
открывает этот репозиторий, а установка `--sparse .claude-plugin --sparse skills` его бы не
забрала. Каталог `.codex-plugin/` (TRK-461) — манифест для
универсального каталога OpenAI: Codex предпочитает его `.claude-plugin/plugin.json`, поэтому
версия, имя и скил в нём обязаны совпадать с плагином Claude Code.
"""

import json
import shutil
import struct
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / ".claude-plugin"


def _release_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]["version"]


def _load(name: str) -> dict:
    return json.loads((PLUGIN_DIR / name).read_text(encoding="utf-8"))


def _marketplace_plugin() -> dict:
    plugins = _load("marketplace.json")["plugins"]
    assert [p["name"] for p in plugins] == ["casefile"]
    return plugins[0]


def test_marketplace_names_casefile_and_its_owner() -> None:
    marketplace = _load("marketplace.json")

    assert marketplace["name"] == "casefile"
    assert marketplace["owner"]["name"] == "azimov777"
    assert _marketplace_plugin()["source"] == "./"


def test_plugin_and_marketplace_versions_equal_release_version() -> None:
    expected = _release_version()

    assert _load("plugin.json")["version"] == expected
    assert _marketplace_plugin()["version"] == expected
    assert _load("marketplace.json")["metadata"]["version"] == expected


def test_plugin_skills_point_to_the_directory_with_the_skill() -> None:
    plugin = _load("plugin.json")

    assert plugin["name"] == "casefile"
    assert plugin["license"] == "MIT"
    skills_dir = (ROOT / plugin["skills"]).resolve()
    assert skills_dir.is_dir()
    assert (skills_dir / "casefile" / "SKILL.md").is_file()


def test_plugin_manifest_carries_the_listing_fields_of_the_anthropic_directory() -> None:
    """Поля, которые каталог Anthropic показывает в листинге и требует от плагина (TRK-457)."""
    plugin = _load("plugin.json")

    for field in ("name", "displayName", "description", "homepage", "repository", "version"):
        assert plugin[field], field
    assert plugin["author"]["name"]
    assert plugin["homepage"].startswith("https://")
    assert plugin["repository"].startswith("https://github.com/")


def test_plugin_carries_privacy_policy_and_square_png_icon_for_the_portal() -> None:
    """Портал Anthropic требует `privacyPolicyUrl` и PNG 512–2048 px меньше 2 МБ (TRK-505)."""
    plugin = _load("plugin.json")
    assert plugin["privacyPolicyUrl"] == "https://azimov777.github.io/casefile/privacy/"

    icon = PLUGIN_DIR / "icon.png"
    data = icon.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height and 512 <= width <= 2048
    assert len(data) < 2 * 1024 * 1024


DEFAULT_ADDRESS = "http://127.0.0.1:8100/mcp"
#: Ключи, которыми в конфигурации MCP-клиента задают авторизацию. В плагине их нет: вход — OAuth.
AUTH_KEYS = {
    "headers",
    "headersHelper",
    "headers_helper",
    "env",
    "env_vars",
    "bearer_token_env_var",
    "http_headers",
    "env_http_headers",
    "oauth",
    "authorization",
    "token",
}


def _codex() -> dict:
    return json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))


def _walk_keys(node: object) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _walk_keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _walk_keys(v)}
    return set()


def _connector(manifest: dict, base: Path) -> dict:
    """Единственный сервер `casefile` из файла, на который указывает `mcpServers` манифеста."""
    path = (base / manifest["mcpServers"]).resolve()
    assert path.is_file() and ROOT in path.parents
    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == ["casefile"]
    return servers["casefile"]


def test_plugin_carries_the_connector_with_the_address_from_user_config() -> None:
    """Claude Code: адрес спрашивается `userConfig`, по умолчанию — эта машина (TRK-451)."""
    plugin = _load("plugin.json")
    connector = _connector(plugin, ROOT)
    option = plugin["userConfig"]["casefile_url"]

    assert connector == {"type": "http", "url": "${user_config.casefile_url}"}
    assert option["type"] == "string" and option["default"] == DEFAULT_ADDRESS
    assert option["title"] and option["description"]
    assert not option.get("sensitive")


def test_codex_connector_is_a_fixed_address_equal_to_the_default() -> None:
    """У Codex подстановок нет: в манифесте адрес по умолчанию, другой — `codex mcp add`."""
    connector = _connector(_codex(), ROOT)

    assert connector == {"url": DEFAULT_ADDRESS}
    assert "${" not in json.dumps(connector)
    assert connector["url"] == _load("plugin.json")["userConfig"]["casefile_url"]["default"]


def test_plugin_has_no_token_headers_or_auth_settings() -> None:
    """Токен у каждой установки свой и в плагин не попадает: клиент входит по OAuth."""
    plugin = _load("plugin.json")
    codex = _codex()
    files = {
        "claude connector": json.loads((ROOT / plugin["mcpServers"]).read_text(encoding="utf-8")),
        "codex connector": json.loads((ROOT / codex["mcpServers"]).read_text(encoding="utf-8")),
        "claude userConfig": plugin["userConfig"],
        "marketplace": _marketplace_plugin(),
    }
    for name, node in files.items():
        assert not (_walk_keys(node) & AUTH_KEYS), name
    for name in ("claude connector", "codex connector"):
        text = json.dumps(files[name]).lower()
        assert "bearer" not in text and "token" not in text, name
    assert "mcpServers" not in _marketplace_plugin()
    assert "apps" not in codex


def test_no_connector_file_in_the_repository_root() -> None:
    """Корневой `.mcp.json` читают и Claude Code в этом репозитории, и Codex у плагина."""
    assert not (ROOT / ".mcp.json").exists()


def test_codex_manifest_matches_the_claude_plugin_and_has_listing_fields() -> None:
    """Манифест Codex (решение TRK-461): версия выпуска, то же имя, скил, поля листинга."""
    codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude = _load("plugin.json")

    assert codex["version"] == _release_version() == claude["version"]
    assert codex["name"] == claude["name"]
    assert codex["author"]["name"]
    assert (ROOT / codex["skills"]).resolve() == (ROOT / claude["skills"]).resolve()
    interface = codex["interface"]
    required = ("displayName", "shortDescription", "longDescription", "developerName", "category")
    for field in required:
        assert interface[field], field
    assert len(interface["displayName"]) <= 30
    assert len(interface["shortDescription"]) <= 30
    assert len(interface["longDescription"]) <= 4000
    for field in ("logo", "composerIcon"):
        icon = ROOT / interface[field]
        assert icon.is_file() and icon.stat().st_size <= 5 * 1024 * 1024


def test_codex_manifest_carries_listing_pages_on_https() -> None:
    interface = _codex()["interface"]
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        assert interface[field].startswith("https://azimov777.github.io/casefile/"), field


@pytest.mark.skipif(shutil.which("zip") is None, reason="нужен zip")
def test_openai_zip_is_skills_only_without_the_connector(tmp_path: Path) -> None:
    """ZIP для каталога OpenAI (TRK-503): без `mcpServers` и `mcp.json`, репозиторий с ними."""
    result = subprocess.run(
        [str(ROOT / "scripts" / "build-openai-plugin.sh"), str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    with zipfile.ZipFile(result.stdout.strip()) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read(".codex-plugin/plugin.json"))
    assert not [n for n in names if n.endswith("mcp.json")]
    assert "skills/casefile/SKILL.md" in names
    assert "mcpServers" not in manifest
    assert "mcp" not in manifest["keywords"]
    assert "connector" not in manifest["description"].lower()
    assert "connector" not in manifest["interface"]["longDescription"].lower()
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        assert manifest["interface"][field] == _codex()["interface"][field]
    assert "mcpServers" in _codex()
