"""Скил, который сервер раздаёт агенту: промпт, инструкции и совпадение имён.

Дисциплина живёт в одном файле — `skill/tracker-agent/SKILL.md` (`CONCEPT.md`, 5.3).
Проверяется здесь не столько код, сколько то, что второй копии этого текста нет и что
скил не разошёлся с сервером по именам инструментов.

## Почему совпадение имён проверяется тестом, а не вниманием

Скил зовёт инструменты по именам прямо в тексте. Переименованный инструмент делает скил
инструкцией к несуществующему действию: агент выполнит её буквально, получит отказ
«неизвестный инструмент» и начнёт искать обход — то есть сломается не сервер, а работа.
Обратная сторона так же важна: инструмент, ни разу не названный в скиле, агент, скорее
всего, не найдёт вовсе.
"""

import re

import pytest
from mcp.server.mcpserver import MCPServer
from mcp_types import TextContent

from app.mcp.skill import PROMPT_NAME, SKILL_PATH, SUMMARY_HEADING
from conftest import Connect

#: Идентификатор в обратных кавычках, за которым сразу идёт скобка, — это вызов
#: инструмента в тексте скила: `add_summary(key, ...)`.
TOOL_CALL_IN_SKILL = re.compile(r"`([a-z][a-z0-9_]*)\(")


@pytest.fixture
def skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


async def test_the_prompt_returns_the_whole_skill(
    mcp_session: Connect, task_secret: str, skill_text: str
) -> None:
    """Обзорная проверка 6: `prompts/get` отдаёт файл скила целиком."""
    async with mcp_session(task_secret) as session:
        listed = await session.list_prompts()
        prompt = await session.get_prompt(PROMPT_NAME)

    assert [item.name for item in listed.prompts] == [PROMPT_NAME]
    contents = [
        message.content.text
        for message in prompt.messages
        if isinstance(message.content, TextContent)
    ]
    assert contents == [skill_text]


async def test_the_instructions_are_the_summary_section(
    mcp_session: Connect, task_secret: str, skill_text: str
) -> None:
    """Обзорная проверка 6: `instructions` равны разделу «Кратко».

    Раздел здесь вырезается своим разбором, а не функцией приложения: тест, зовущий тот
    же код, проверял бы только то, что функция детерминирована.
    """
    _, _, rest = skill_text.partition(f"{SUMMARY_HEADING}\n")
    expected = rest.split("\n## ", 1)[0].strip()
    assert expected, "в скиле не стало раздела «Кратко»"

    async with mcp_session(task_secret) as session:
        result = await session.initialize()

    assert result.instructions == expected
    assert "add_summary" in expected, "выжимка перестала называть главное правило"


async def test_every_tool_named_in_the_skill_exists(mcp_server: MCPServer, skill_text: str) -> None:
    """Обзорная проверка 9: скил не зовёт того, чего у сервера нет."""
    registered = {tool.name for tool in await mcp_server.list_tools()}
    called = set(TOOL_CALL_IN_SKILL.findall(skill_text))

    assert called, "в скиле не осталось ни одного вызова инструмента — выражение устарело"
    assert called <= registered, f"скил зовёт несуществующее: {sorted(called - registered)}"


async def test_every_working_cycle_tool_is_mentioned_in_the_skill(
    mcp_session: Connect, task_secret: str, skill_text: str
) -> None:
    """Обзорная проверка 9: инструмент, не названный в скиле, агент не найдёт.

    Список берётся у сервера токеном `task`, а не переписывается в тест: иначе тест
    сверял бы скил со своей же копией перечня.
    """
    async with mcp_session(task_secret) as session:
        working_cycle = {tool.name for tool in (await session.list_tools()).tools}

    missing = sorted(name for name in working_cycle if f"`{name}" not in skill_text)

    assert not missing, f"скил не упоминает: {missing}"
