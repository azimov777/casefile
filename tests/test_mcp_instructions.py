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

import re

import pytest

from app.mcp.server import INSTRUCTIONS_PATH
from conftest import Connect

#: Предел Claude Code по умолчанию: `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`, 2048.
CLIENT_LIMIT = 2048

#: Правила, которым раскладка TRK-141 (#15–#17) отвела место в `instructions`, и метка,
#: по которой правило находится в тексте. Метка — сама суть правила, а не случайное
#: слово: переписанный текст, потерявший правило, её не сохранит. Текст английский
#: (TRK-140#18), метки тоже.
RULES = {
    "0.1 дело ведут для преемника без контекста": "clean context",
    "0.3 цикл задачи по шагам": "Task cycle:",
    "1.1 трекер сам ничего не делает": "not an orchestrator",
    "1.1 статус переводит агент": "only when an agent moves it",
    "1.1 скрытой автоматики нет, кроме названной": "no hidden automation",
    "1.2 порча журнала — отказ и причина": "rejected with the reason stated",
    "1.7 что видит человек": "visible to the human",
    "2.1 вход — get_task": "Entry: `get_task`",
    "2.4 исход по каждому замечанию": "`resolve`",
    "2.8 назначить себя до in_progress": "gets the agent as its assignee first",
    "3.1 что задаёт работу": "Work is set by",
    "3.2 чужой текст — сведения, подпись не приказ": "not an instruction",
    "3.7 текст мимо контракта — finding и ответ": "`finding`",
    "5.5 сводка после каждого значимого шага": "summary follows every significant step",
    "9.1 ход за задачей — blocked_by и open": "`blocked_by`",
    "10.1 ход за человеком — waiting": "`waiting`",
    "10.7 in_progress только пока ход за агентом": "only while the next move is the agent's",
    "12.10 распавшееся не вести одним делом": "its own case rather than one shared case",
}

#: Повелительное наклонение (TRK-140#18). Приказ в английском — глагол в начальной форме
#: в начале предложения, шага или части после «:», «;», «—». Проверка смотрит первое
#: слово каждой такой части и сверяет со списком глаголов, которыми агенту приказывают
#: действовать с трекером. Глагол в середине описания («`get_task` returns», «is filed»)
#: её не трогает: он стоит не в начале и не в начальной форме. Имена инструментов в
#: обратных кавычках («`get_task`») словом-приказом не считаются.
IMPERATIVE_VERBS = frozenset(
    re.findall(
        r"\w+",
        """
    add answer ask assign avoid be begin call check choose close continue create do
    ensure file fill find follow get give go ignore keep leave let link look make mark
    move name note open pass pick put read record remember report resolve return run
    see send set split start stop summarize take tell treat try update use verify wait
    write
    """,
    )
)

#: Слова, которых в описательном тексте нет вовсе: обращение к агенту, «делай / не
#: делай», модальный долг, оценки и вводные примеров.
FORBIDDEN_WORDS = (
    "you",
    "your",
    "don't",
    "do not",
    "never",
    "always",
    "must",
    "should",
    "please",
    "good",
    "bad",
    "better",
    "worse",
    "for example",
    "for instance",
    "e.g.",
)

#: Границы частей, в начале которых стоит приказ: начало строки, конец предложения,
#: двоеточие, точка с запятой и тире. Номер шага «1. » закрыт точкой, так что слово после
#: него — тоже начало части.
CLAUSE_START = re.compile(r"(?:^|[.;:!?]\s+|\s—\s)", re.MULTILINE)


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
    lines = [line for line in served.splitlines() if "visible to the human" in line]

    assert len(lines) == 1, "строка про то, что видит человек, пропала или раздвоилась"
    assert "feed" in lines[0] and "`wait_journal`" in lines[0]


async def test_the_assignee_is_set_before_taking_the_task_into_work(served: str) -> None:
    """TRK-123: назначить себя — раньше, чем `in_progress`, и в этом порядке в тексте."""
    assign = served.index("gets the agent as its assignee first")

    assert assign < served.index("`in_progress`", assign), (
        "`instructions` перестали ставить исполнителя до перевода в `in_progress`"
    )


def clause_openers(text: str) -> list[str]:
    """Первое слово каждой части текста, где мог бы стоять приказ, в нижнем регистре."""
    openers = []
    for match in CLAUSE_START.finditer(text):
        word = re.match(r"[`\w']+", text[match.end() :])
        if word:
            openers.append(word.group().lower())
    return openers


async def test_the_instructions_are_english(served: str) -> None:
    """TRK-140#18: язык `instructions` — английский, кириллицы нет ни одной буквы."""
    cyrillic = re.findall(r"[\u0400-\u04ff]", served)

    assert not cyrillic, f"в `instructions` кириллица: {''.join(cyrillic[:20])}"


async def test_the_procedure_is_numbered_steps(served: str) -> None:
    """Порядок работы — пронумерованные шаги подряд с 1."""
    steps = re.findall(r"^(\d+)\. ", served, re.MULTILINE)

    assert steps == [str(n) for n in range(1, len(steps) + 1)] and len(steps) >= 5


async def test_no_clause_opens_with_a_command(served: str) -> None:
    """TRK-140#18: ни предложение, ни шаг, ни часть после «:», «;», «—» не приказывают."""
    commands = [word for word in clause_openers(served) if word in IMPERATIVE_VERBS]

    assert not commands, f"повелительные формы в `instructions`: {commands}"


async def test_no_address_duty_or_judgement(served: str) -> None:
    """TRK-140#18: без «you», «do / don't», «must», оценок и вводных примеров."""
    lowered = served.lower()
    found = [
        word
        for word in FORBIDDEN_WORDS
        if re.search(rf"(?<![\w']){re.escape(word)}(?![\w'])", lowered)
    ]

    assert not found, f"в `instructions` слова приказа, оценки или примера: {found}"


@pytest.mark.parametrize(
    "command",
    [
        "Call `get_task` first.",
        "The case matters: write a summary after each step.",
        "1. Entry: read the summary.",
        "Nothing is automatic; move the status yourself.",
        "Other text — treat it as information.",
    ],
)
def test_the_command_check_catches_commands(command: str) -> None:
    """Проверка ловит приказ в начале предложения, шага и части после «:», «;», «—»."""
    assert any(word in IMPERATIVE_VERBS for word in clause_openers(command))


@pytest.mark.parametrize(
    "description",
    [
        "`get_task` returns the summary.",
        "A summary follows every significant step.",
        "1. Entry: `get_task` returns the case index.",
        "Work is set by the sections of the task.",
    ],
)
def test_the_command_check_passes_descriptions(description: str) -> None:
    """Глагол описания в середине фразы и имя инструмента в начале приказом не считаются."""
    assert not any(word in IMPERATIVE_VERBS for word in clause_openers(description))
