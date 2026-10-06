"""`skills/casefile-setup/SKILL.md` — второй скил плагина: как подключить Casefile (TRK-566).

Скил срабатывает сам только когда инструментов Casefile нет или они отвечают 401: отключить
один скил плагина в Claude Code нельзя (TRK-564#18), поэтому условие держит его `description`.
Формат и запреты — те же, что у `skills/casefile/` (`tests/test_skill_file.py`): в тексте
нет команд «скачать и выполнить», ключей, `Bearer` и ссылок на `scripts/` (TRK-459#29, #30).
Что `description` и вправду заставит модель вызвать скил вовремя, тесты не меряют.
"""

import re
from pathlib import Path

import pytest

from test_skill_file import (
    CASEFILE_DESCRIPTION_LIMIT,
    DESCRIPTION_LIMIT,
    DOWNLOAD_AND_RUN,
    SECURITY_MARKERS,
    SKILL_FILE,
    parse_frontmatter,
)

SETUP_DIR = Path(__file__).resolve().parents[1] / "skills" / "casefile-setup"
SETUP_FILE = SETUP_DIR / "SKILL.md"

CONDITION = "Use only when the Casefile MCP tools are missing"
REPOSITORY = "https://github.com/azimov777/casefile"
MCPB_URL = f"{REPOSITORY}/releases/latest/download/casefile.mcpb"
GUIDE_URL = f"{REPOSITORY}/blob/main/docs/agent-install.md"


@pytest.fixture(scope="module")
def frontmatter() -> dict[str, str]:
    return parse_frontmatter(SETUP_FILE.read_text(encoding="utf-8"))


def test_setup_frontmatter_has_exactly_name_and_description(frontmatter: dict[str, str]) -> None:
    assert set(frontmatter) == {"name", "description"}


def test_setup_name_is_casefile_setup_and_matches_directory(frontmatter: dict[str, str]) -> None:
    assert frontmatter["name"] == "casefile-setup"
    assert frontmatter["name"] == SETUP_DIR.name


def test_setup_description_starts_with_the_missing_tools_condition(
    frontmatter: dict[str, str],
) -> None:
    assert frontmatter["description"].startswith(CONDITION)
    assert "401" in frontmatter["description"]


def test_setup_description_fits_the_limits(frontmatter: dict[str, str]) -> None:
    assert 0 < len(frontmatter["description"]) <= CASEFILE_DESCRIPTION_LIMIT <= DESCRIPTION_LIMIT


def test_setup_skill_has_no_download_and_run_commands() -> None:
    text = SETUP_FILE.read_text(encoding="utf-8")
    found = [line for line in text.splitlines() if DOWNLOAD_AND_RUN.search(line)]
    assert not found, f"в скиле команды скачать-и-выполнить: {found}"


def test_setup_skill_has_no_install_secrets_or_outside_scripts() -> None:
    text = SETUP_FILE.read_text(encoding="utf-8")
    found = [line for line in text.splitlines() if SECURITY_MARKERS.search(line)]
    assert not found, f"в скиле установка, секреты или внешние скрипты: {found}"


def test_setup_skill_links_only_to_the_public_repository_and_has_no_private_paths() -> None:
    text = SETUP_FILE.read_text(encoding="utf-8")
    links = re.findall(r"https?://[^\s)`]+", text)
    assert GUIDE_URL in text and MCPB_URL in text
    for link in links:
        assert link.startswith(REPOSITORY) or link == "http://127.0.0.1:8100/mcp", link
    assert "/Users/" not in text


def test_setup_skill_covers_every_place_the_person_may_work() -> None:
    body = SETUP_FILE.read_text(encoding="utf-8")
    for heading in (
        "### Claude Code",
        "### Codex",
        "### Cursor",
        "### The Claude desktop app chat",
        "### claude.ai in a browser, or the Claude app on a phone",
    ):
        assert heading in body, heading


def test_the_casefile_skill_sends_a_disconnected_agent_to_the_setup_skill() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8")
    last = text[text.rindex("\n## ") :]
    assert "`casefile-setup`" in last
    assert "casefile-setup" not in text[: text.rindex("\n## ")]
