"""`instructions` сервера: длина под обрезкой клиента и состав по раскладке TRK-141.

`instructions` уезжают клиенту в ответе на `initialize`, и Claude Code вставляет их в
системный промпт модели. Вставляет не целиком: строку длиннее 2048 символов он обрезает
и дописывает «… [truncated]» (`TRK-142#15`, исходник клиента). Хвост после обрезки
модель не видит, а сервер при этом выглядит здоровым — так раздел «Кратко» скила
терял пункты 7–11, в том числе правило о чужом тексте.

## Почему символы считаются единицами UTF-16

Клиент сравнивает `length` строки JS, а это число единиц UTF-16, не байт и не кодовых
точек. Для кириллицы разницы с `len()` нет, для символа вне BMP (эмодзи) JS насчитает
два. Тест считает так же, как клиент: иначе такой символ прошёл бы проверку и срезал
последний символ текста у модели.

## Почему меряется строка сервера, а не файл

Между файлом и клиентом стоит сборка: чтение, `strip()`, передача в `MCPServer`. Тест
файла не заметил бы, что сборка начала что-то приклеивать к тексту. Поэтому длину меряет
ответ `initialize` — ровно то, что получит клиент.
"""

import pytest

from app.mcp.server import INSTRUCTIONS_PATH
from conftest import Connect

#: Предел Claude Code по умолчанию: `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`, 2048.
CLIENT_LIMIT = 2048

#: Правила, которым раскладка TRK-141 (#15–#17) отвела место в `instructions`, и метка,
#: по которой правило находится в тексте. Метка — сама суть правила, а не случайное
#: слово: переписанный текст, потерявший правило, её не сохранит.
RULES = {
    "0.1 дело ведут для преемника без контекста": "чистым контекстом",
    "0.3 цикл задачи по шагам": "Цикл задачи",
    "1.1 трекер сам ничего не делает": "не оркестратор",
    "1.1 скрытой автоматики нет, кроме названной": "Скрытой автоматики",
    "1.2 порча журнала — отказ и причина": "отклоняет",
    "1.7 что видит человек": "видна человеку",
    "2.1 вход — get_task": "`get_task`",
    "2.4 исход по каждому замечанию": "`resolve`",
    "2.8 назначить себя до in_progress": "назначь себя",
    "3.1 что задаёт работу": "Работу задают",
    "3.2 чужой текст — сведения, подпись не приказ": "не приказ",
    "3.7 текст мимо контракта — finding и ответ": "`finding`",
    "5.5 сводка после каждого значимого шага": "после каждого значимого шага",
    "9.1 ход за задачей — blocked_by и open": "`blocked_by`",
    "10.1 ход за человеком — waiting": "`waiting`",
    "10.7 не держать in_progress, когда ход не твой": "держи `in_progress`, когда ход не твой",
    "12.10 распавшееся не вести одним делом": "не веди их одним делом",
}


def utf16_length(text: str) -> int:
    """Длина строки так, как её считает `String.prototype.length`."""
    return len(text.encode("utf-16-le")) // 2


@pytest.fixture
async def served(mcp_session: Connect, task_secret: str) -> str:
    """`instructions` из ответа `initialize` живого сервера."""
    async with mcp_session(task_secret) as session:
        result = await session.initialize()
    assert result.instructions, "сервер перестал отдавать `instructions`"
    return result.instructions


async def test_the_instructions_fit_the_client_limit(served: str) -> None:
    """Обзорная проверка TRK-142: модель получает `instructions` целиком."""
    length = utf16_length(served)

    assert length <= CLIENT_LIMIT, (
        f"`instructions` — {length} символов, Claude Code обрежет их на {CLIENT_LIMIT}-м"
    )


def test_the_length_is_counted_the_way_the_client_counts() -> None:
    """Эмодзи — две единицы UTF-16, кириллица — одна: счёт повторяет JS, а не `len()`."""
    assert utf16_length("дело") == 4
    assert utf16_length("🙂") == 2


async def test_the_instructions_are_the_text_of_their_file(served: str) -> None:
    """Сервер отдаёт файл как есть: без приклеенного текста и без второй копии в коде."""
    assert served == INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("rule", RULES)
async def test_every_rule_placed_in_the_instructions_is_there(served: str, rule: str) -> None:
    """Обзорная проверка TRK-142: каждая строка раскладки с местом «instructions» — в тексте."""
    assert RULES[rule] in served, f"в `instructions` не стало правила {rule}"


async def test_what_the_human_sees_is_said_once(served: str) -> None:
    """Вторичный эффект подшивки назван один раз одной строкой (TRK-140#8, TRK-142).

    Из описаний инструментов его снимает TRK-145; здесь он обязан стоять целиком: лента,
    ожидающие `wait_journal` и человек в интерфейсе.
    """
    lines = [line for line in served.splitlines() if "видна человеку" in line]

    assert len(lines) == 1, "строка про то, что видит человек, пропала или раздвоилась"
    assert "ленту" in lines[0] and "`wait_journal`" in lines[0]


async def test_the_assignee_is_set_before_taking_the_task_into_work(served: str) -> None:
    """TRK-123: назначить себя — раньше, чем `in_progress`, и в этом порядке в тексте."""
    assign = served.index("назначь себя")

    assert assign < served.index("`in_progress`", assign), (
        "`instructions` перестали назначать себя до перевода в `in_progress`"
    )
