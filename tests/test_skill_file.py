"""`skills/casefile/SKILL.md` — единственный файл скила Casefile (TRK-402, TRK-398#7).

Один и тот же файл отдают плагин маркетплейса (`.claude-plugin/`, TRK-404) и сам сервер
по SEP-2640 (`skill://casefile/SKILL.md`, TRK-403). Формат — agentskills.io: фронтматтер
из двух ключей, `name` равен имени каталога скила, `description` не длиннее 1024
символов по стандарту, а у Casefile — не длиннее 500 (TRK-442): Claude Code режет
описание в листинге скилов до 1536 символов, Codex отводит всему списку 2% контекста.
`allowed-tools` и прочие ключи не допускаются: харнессы понимают их по-разному,
а скил не расширяет права агента.

YAML-библиотеки в зависимостях нет, поэтому фронтматтер разбирается здесь строго и узко:
каждая строка — `ключ: значение` одной строкой, значение — простой скаляр YAML без
`: ` и ` #` внутри и без кавычек и спецсимволов в начале. Всё, что шире, — отказ теста,
а не догадка: так любой разборщик YAML в харнессе прочтёт те же два значения.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.domain.tasks import TaskStatus
from conftest import Connect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / "skills" / "casefile"
SKILL_FILE = SKILL_DIR / "SKILL.md"

DESCRIPTION_LIMIT = 1024
#: Свой потолок Casefile под листинги Claude Code и Codex (TRK-435#10, TRK-436#11).
CASEFILE_DESCRIPTION_LIMIT = 500
LINE = re.compile(r"^(?P<key>[a-z][a-z0-9-]*): (?P<value>\S.*)$")
#: Символы, с которых простой скаляр YAML начинаться не может.
YAML_INDICATORS = set("-?:,[]{}#&*!|>'\"%@`")


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.split("\n")
    assert lines[0] == "---", "SKILL.md начинается строкой `---`"
    try:
        end = lines.index("---", 1)
    except ValueError:
        pytest.fail("фронтматтер SKILL.md не закрыт строкой `---`")
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = LINE.match(line)
        assert match, f"строка фронтматтера не вида `ключ: значение`: {line!r}"
        key, value = match["key"], match["value"]
        assert key not in fields, f"ключ {key!r} повторён"
        assert value[0] not in YAML_INDICATORS, f"{key}: первый символ значения {value[0]!r}"
        assert ": " not in value and " #" not in value, f"{key}: не простой скаляр YAML"
        assert value == value.rstrip(), f"{key}: пробел в конце значения"
        fields[key] = value
    assert "\n".join(lines[end + 1 :]).strip(), "тело скила после фронтматтера пусто"
    return fields


@pytest.fixture(scope="module")
def frontmatter() -> dict[str, str]:
    return parse_frontmatter(SKILL_FILE.read_text(encoding="utf-8"))


def test_frontmatter_has_exactly_name_and_description(frontmatter: dict[str, str]) -> None:
    assert set(frontmatter) == {"name", "description"}


def test_name_is_casefile_and_matches_directory(frontmatter: dict[str, str]) -> None:
    assert frontmatter["name"] == "casefile"
    assert frontmatter["name"] == SKILL_DIR.name


def test_description_fits_limit(frontmatter: dict[str, str]) -> None:
    assert 0 < len(frontmatter["description"]) <= DESCRIPTION_LIMIT


def test_description_fits_harness_listings(frontmatter: dict[str, str]) -> None:
    assert len(frontmatter["description"]) <= CASEFILE_DESCRIPTION_LIMIT


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("name: casefile\n---\nbody", "начинается"),
        ("---\nname: casefile\nbody", "не закрыт"),
        ("---\nname: a: b\n---\nbody", "простой скаляр"),
        ("---\nname: 'casefile'\n---\nbody", "первый символ"),
        ("---\nname: casefile\nname: other\n---\nbody", "повторён"),
        ("---\n  name: casefile\n---\nbody", "не вида"),
        ("---\nname: casefile\n---\n\n", "пусто"),
    ],
)
def test_parser_rejects_what_it_does_not_understand(text: str, reason: str) -> None:
    with pytest.raises((AssertionError, pytest.fail.Exception), match=reason):
        parse_frontmatter(text)


#: Скил не несёт команд «скачать и выполнить» (TRK-508): проверки каталогов OpenAI и
#: Anthropic помечают `curl … | sh`, `irm … | iex` и `npx` как код вне проверенного пакета.
#: Установка и обновление — в README и `docs/agent-install.md`, скил даёт на них ссылки.
DOWNLOAD_AND_RUN = re.compile(r"\| *(sh|bash|iex)\b|curl |irm |npx ")

#: Второй отказ портала OpenAI — «security risk» (TRK-459#30): ключ из `.secrets`, заголовок
#: `Bearer` в конфиге, внешний скрипт из `scripts/`. С TRK-509 скил учит работе с задачами
#: через MCP, а подключение, ключи и сторож журнала живут в `docs/agent-install.md`:
#: в скиле нет ни установки, ни секретов, ни кода вне пакета.
SECURITY_MARKERS = re.compile(r"docker|\.secrets|bearer|\btokens?\b|scripts/", re.IGNORECASE)

GUIDE_URL = "https://github.com/azimov777/casefile/blob/main/docs/agent-install.md"


def skill_body() -> str:
    text = SKILL_FILE.read_text(encoding="utf-8")
    return text[text.index("---", 3) + 3 :]


def test_skill_has_no_download_and_run_commands() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8")
    found = [line for line in text.splitlines() if DOWNLOAD_AND_RUN.search(line)]
    assert not found, f"в скиле команды скачать-и-выполнить: {found}"


def test_skill_has_no_install_secrets_or_outside_scripts() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8")
    found = [line for line in text.splitlines() if SECURITY_MARKERS.search(line)]
    assert not found, f"в скиле установка, секреты или внешние скрипты: {found}"


def test_skill_links_to_the_connection_guide_once_in_its_last_section() -> None:
    """Скил не про установку (TRK-509): гайд подключения — одной ссылкой в последнем разделе."""
    body = skill_body()
    last = body[body.rindex("\n## ") :]
    assert GUIDE_URL in last
    assert body.count("https://") == 1, "кроме ссылки на гайд, адресов в скиле нет"


def test_the_detectors_catch_what_they_are_for() -> None:
    for line in (
        "curl -fsSL https://x/install.sh | sh",
        "irm https://x/install.ps1 | iex",
        "npx skills add a/b",
    ):
        assert DOWNLOAD_AND_RUN.search(line), line
    for line in (
        "cd ~/casefile && docker compose run agent-token",
        "cat .secrets/agent-token",
        'Authorization: "Bearer <x>"',
        "put the token into the config",
        "run scripts/watch-journal.sh",
    ):
        assert SECURITY_MARKERS.search(line), line


#: Имя вида snake_case вне пути к файлу: `get_task`, `in_progress`, `after_no`.
SNAKE = re.compile(r"(?<![\w/.])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![\w.])")
#: Одно слово в обратных кавычках: `open`, `decision`, `parent`.
QUOTED_WORD = re.compile(r"`([a-z][a-z0-9_]*)`")
#: Вызов инструмента в примере: `get_task(` и т. п.
CALL = re.compile(r"(?<![\w.])([a-z][a-z0-9_]*)\(")
#: Целевой статус перехода в примере: `to="open"`.
TARGET = re.compile(r'\bto="([a-z_]+)"')


def words(node: Any) -> Iterator[str]:
    """Все слова вида snake_case в живом `tools/list`: имена, аргументы, перечисления, описания."""
    yield from re.findall(r"[a-z][a-z0-9_]*", json.dumps(node))


@pytest.fixture
async def served(mcp_session: Connect, main_secret: str) -> tuple[set[str], set[str]]:
    """Имена инструментов и словарь сервера — то, что агент видит при подключении."""
    async with mcp_session(main_secret) as session:
        init = await session.initialize()
        tools = (await session.list_tools()).tools
    names = {tool.name for tool in tools}
    vocabulary = set(words([tool.model_dump(mode="json") for tool in tools]))
    vocabulary |= set(re.findall(r"[a-z][a-z0-9_]*", init.instructions or ""))
    return names, vocabulary


async def test_every_called_tool_exists_on_the_server(served: tuple[set[str], set[str]]) -> None:
    names, _ = served
    called = set(CALL.findall(skill_body()))
    assert called, "в скиле нет примеров вызовов"
    assert called <= names, f"в скиле вызовы инструментов, которых нет: {called - names}"


async def test_every_identifier_in_the_skill_is_served(served: tuple[set[str], set[str]]) -> None:
    """Имена инструментов, аргументов, статусов и типов записей из скила есть в коде MCP."""
    _, vocabulary = served
    body = skill_body()
    named = set(SNAKE.findall(body)) | set(QUOTED_WORD.findall(body))
    assert named <= vocabulary, f"в скиле имена, которых сервер не знает: {named - vocabulary}"


def test_every_status_in_the_skill_is_a_task_status() -> None:
    body = skill_body()
    statuses = {status.value for status in TaskStatus}
    targets = set(TARGET.findall(body))
    assert targets, "в скиле нет примеров перехода"
    assert targets <= statuses, f"переходы в несуществующий статус: {targets - statuses}"
    mentioned = {word for word in QUOTED_WORD.findall(body) if word in statuses}
    assert {"in_progress", "open"} <= mentioned | targets
