"""Манифесты плагина `.claude-plugin/`: версия равна версии выпуска (TRK-404, TRK-398#7, #8).

Claude Code без новой `version` отвечает «already at latest» и держит старый `SKILL.md`,
поэтому равенство с `pyproject.toml` держит тест. Плагин несёт только скил: `.mcp.json`
и ключа `mcpServers` нет (TRK-398#9). Каталог `.codex-plugin/` (TRK-461) — манифест для
универсального каталога OpenAI: Codex предпочитает его `.claude-plugin/plugin.json`, поэтому
версия, имя и скил в нём обязаны совпадать с плагином Claude Code.
"""

import json
import tomllib
from pathlib import Path

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


def test_plugin_carries_only_the_skill() -> None:
    """Токен и адрес у каждой установки свои: MCP плагином не подключается."""
    assert "mcpServers" not in _load("plugin.json")
    assert "mcpServers" not in _marketplace_plugin()
    assert not (ROOT / ".mcp.json").exists()
    codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "mcpServers" not in codex and "apps" not in codex


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
