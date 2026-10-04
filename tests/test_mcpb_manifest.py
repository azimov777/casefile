"""Расширение Claude Desktop `mcpb/` (TRK-514): манифест MCPB, мост и сборка.

`casefile.mcpb` собирает `scripts/build-mcpb.sh`, в выпуск его кладёт `.github/workflows/mcpb.yml`.
Сама сборка идёт в контейнере `node` и здесь не запускается: в образе тестов нет ни Docker, ни
Node. Здесь — то, что сломается молча: версия манифеста против версии выпуска (Claude Desktop
сравнивает версии при повторной установке), имя против `serverInfo.name` сервера (решение
TRK-514#20), аргументы моста и адрес по умолчанию, отсутствие токена и закреплённая версия
`mcp-remote`.
"""

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from app.mcp.server import SERVER_NAME

ROOT = Path(__file__).resolve().parents[1]
MCPB = ROOT / "mcpb"
BUILD = ROOT / "scripts" / "build-mcpb.sh"
BRIDGE = "node_modules/mcp-remote/dist/proxy.js"
DEFAULT_ADDRESS = "http://127.0.0.1:8100/mcp"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return _json(MCPB / "manifest.json")


def _release_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def test_manifest_version_equals_release_version() -> None:
    assert _manifest()["version"] == _release_version()


def test_manifest_name_equals_the_server_name_and_the_screens_say_casefile() -> None:
    """Desktop связывает инструменты расширения с чатом по равенству имён (TRK-514#20)."""
    manifest = _manifest()

    assert manifest["name"] == SERVER_NAME
    assert manifest["display_name"] == "Casefile"


def test_server_is_the_bundled_bridge_on_the_node_of_claude_desktop() -> None:
    manifest = _manifest()
    server = manifest["server"]

    assert manifest["manifest_version"] == "0.3"
    assert server["type"] == "node"
    assert server["entry_point"] == BRIDGE
    assert server["mcp_config"]["command"] == "node"
    args = server["mcp_config"]["args"]
    assert args[:2] == [f"${{__dirname}}/{BRIDGE}", "${user_config.casefile_url}"]
    flag = args.index("--static-oauth-client-metadata")
    assert json.loads(args[flag + 1]) == {"client_name": "Claude Desktop"}
    assert sorted(manifest["compatibility"]["platforms"]) == ["darwin", "win32"]


def test_the_address_is_asked_by_the_form_with_the_default_of_this_machine() -> None:
    option = _manifest()["user_config"]["casefile_url"]
    plugin = _json(ROOT / ".claude-plugin" / "plugin.json")["userConfig"]["casefile_url"]

    assert option["type"] == "string" and option["required"] is True
    assert option["default"] == DEFAULT_ADDRESS == plugin["default"]
    assert option["title"] and option["description"]
    assert not option.get("sensitive")


def test_the_extension_carries_no_token_header_or_environment() -> None:
    """Вход — OAuth моста: ни ключа, ни заголовка, ни переменной окружения с секретом."""
    config = _manifest()["server"]["mcp_config"]
    text = json.dumps(config).lower()

    assert "env" not in config
    for word in ("bearer", "authorization", "--header", "token", "trk_"):
        assert word not in text, word
    assert set(_manifest()["user_config"]) == {"casefile_url"}


def test_mcp_remote_is_pinned_to_one_version_in_the_package_and_the_lock() -> None:
    pinned = _json(MCPB / "package.json")["dependencies"]["mcp-remote"]
    lock = _json(MCPB / "package-lock.json")

    assert pinned[0].isdigit(), f"mcp-remote не закреплён точной версией: {pinned}"
    assert lock["packages"]["node_modules/mcp-remote"]["version"] == pinned
    assert lock["packages"][""]["dependencies"] == {"mcp-remote": pinned}


@pytest.mark.skipif(shutil.which("bash") is None, reason="нужен bash")
def test_the_build_refuses_a_manifest_version_other_than_the_release(tmp_path: Path) -> None:
    """Сверка версии идёт до Docker: в копии дерева с другой версией выпуска сборка падает."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(BUILD, tmp_path / "scripts" / BUILD.name)
    shutil.copytree(MCPB, tmp_path / "mcpb")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "99.0.0"\n', encoding="utf-8")

    done = subprocess.run(
        ["bash", str(tmp_path / "scripts" / BUILD.name), str(tmp_path / "out")],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
    )

    assert done.returncode != 0
    assert f"версия манифеста {_release_version()} не равна версии выпуска 99.0.0" in done.stderr
    assert not (tmp_path / "out").exists()


def test_the_release_workflow_builds_with_the_script_and_attaches_the_archive() -> None:
    text = (ROOT / ".github" / "workflows" / "mcpb.yml").read_text(encoding="utf-8")

    assert "types: [published]" in text and "workflow_dispatch" in text
    assert "scripts/build-mcpb.sh" in text
    assert 'gh release upload "$TAG"' in text and "casefile.mcpb" in text
    assert os.access(BUILD, os.X_OK)
