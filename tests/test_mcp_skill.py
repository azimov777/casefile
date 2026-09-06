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


def section(text: str, heading: str) -> str:
    """Раздел скила по заголовку второго уровня, до следующего такого заголовка.

    Разбор тот же, что у `instructions` в приложении, и такой же простой: формат файла
    задаём мы сами. Отсутствие раздела — провал теста, а не пустая строка: правило,
    которое некуда положить, из скила исчезло вместе с разделом.
    """
    _, separator, rest = text.partition(f"## {heading}\n")
    assert separator, f"в скиле не стало раздела «{heading}»"
    return rest.split("\n## ", 1)[0]


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
    assert "after_no" in expected, "выжимка перестала звать читать записи после сводки"


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


def test_entering_a_task_reads_what_was_filed_after_the_summary(skill_text: str) -> None:
    """Дисциплина TRK-3: сводка отстаёт от дела, и вход это учитывает.

    Пакет преемника отдаёт последнюю сводку и опись, но не говорит, что между ними
    разрыв: записи с номером больше номера сводки она не видела. Правило живёт только в
    тексте скила — валидации на это нет, — поэтому его и держит тест.
    """
    entering = section(skill_text, "Вход в задачу")

    assert "after_no" in entering, "вход перестал звать `read_entries(key, after_no=...)`"
    assert "сводк" in entering.lower()


def test_entering_a_task_reads_the_open_remarks(skill_text: str) -> None:
    """Дисциплина TRK-9: замечание не пропускают на входе.

    Трекер отдаёт неразобранные замечания в пакете, но прочитать их — обязанность агента,
    и потребовать этого он не может: чтение он не проверяет. Правило живёт только в
    тексте скила, поэтому его держит тест.
    """
    entering = section(skill_text, "Вход в задачу")

    assert "замечани" in entering.lower(), "вход перестал называть замечания среди читаемого"


def test_closing_names_the_outcome_of_every_remark(skill_text: str) -> None:
    """Дисциплина TRK-9: уйти в `done`, не ответив на «вышло не то», нельзя.

    Валидации на это нет и не будет: замечание не обзорная проверка, и «разобрано»
    означает «агент ответил», а не «трекер убедился». Единственное место, где обязанность
    закреплена, — раздел «Завершение».
    """
    closing = section(skill_text, "Завершение")

    assert "resolve" in closing, "завершение не требует исхода по замечаниям"
    assert closing.index("resolve") < closing.index("add_summary"), (
        "резолюции обязаны идти до финальной сводки: иначе сводка не знает их исхода"
    )


def test_the_skill_promises_no_delivery(skill_text: str) -> None:
    """Дисциплина TRK-9: трекер никого не уведомляет и ничего не запускает.

    Обещание доставки — самая дорогая ошибка в тексте: агент, поверивший, что замечание
    до кого-то «дойдёт», перестаёт читать его сам.
    """
    lowered = skill_text.lower()

    assert "уведом" not in lowered, "скил заговорил про уведомления, которых в трекере нет"
    assert "не следит, жив ли ты" in lowered or "ничего не делает сам" in lowered


def test_closing_puts_the_final_summary_after_the_verdicts(skill_text: str) -> None:
    """Дисциплина TRK-3: финальная сводка — последнее действие перед `done`.

    Трекер требует на `in_progress → done` сводку этого захода и положительный последний
    вердикт по каждой проверке, но не их очерёдность (`CONCEPT.md`, 5.3). Порядок
    «сводка, потом вердикты» валидацию проходит и оставляет преемнику план вместо исхода
    проверок — ровно случай UI-1. Единственное место, где порядок закреплён, — этот
    раздел, и переставленные пункты иначе никто не заметит.
    """
    closing = section(skill_text, "Завершение")
    verdicts = closing.rindex("add_verdict")
    summary = closing.index("add_summary")
    done = closing.index('transition(key, "done")')

    assert verdicts < summary < done, "порядок закрытия в разделе «Завершение» разъехался"
    assert "next_step" in closing, "не сказано, что писать в `next_step` закрываемой задачи"
