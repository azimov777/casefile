"""Метадата инструментов в `tools/list`: язык, правила текста, длина и договоры отказа.

Скила в проекте нет (TRK-140#8): правила работы с одним инструментом живут в его
метадате — описании инструмента, описаниях аргументов, вложенных моделей и полей ответа.
Правила самого текста (TRK-140#18) проверяются здесь по живому `tools/list`, а не по
исходникам: модель читает ровно то, что отдал сервер, включая докстроки моделей и
перечислений, которые pydantic кладёт в схему сам.

Список берётся токеном `main`: описание читает каждый, кому инструмент виден, и
расхождение прячется в наборе `main` не хуже, чем в рабочем цикле.

## Почему грамматика, а не сверка текстов

Граница между описанием и советом грамматическая: метадата **описывает** вызов и поле,
совет **предписывает** ход. Повелительное наклонение в начале предложения, обращение
к читателю («you», «should»), оценки («better», «last resort») и объяснения «because» —
след предписания, и другого способа отличить один текст от другого без чтения глазами
нет. Безличный совет без грамматического следа этот тест не ловит — он остаётся на
вычитке (`docs/notes/mcp.md`).
"""

import json
import re
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

import pytest
from mcp_types import Tool

from app.domain.query_language import QUERY_EXAMPLES
from app.domain.tasks import TaskStatus
from conftest import Connect

#: Предел клиента Claude Code на описание инструмента: 2048 единиц UTF-16 (TRK-142#15).
CLIENT_DESCRIPTION_LIMIT = 2048

#: Глаголы, которыми начинается повелительное предложение. Список закрытый: морфологии
#: английскому тексту не нужно, а описания начинают предложения существительными
#: («Key of …») или глаголами третьего лица («Returns …»), которых здесь нет.
IMPERATIVE_VERBS = (
    "add",
    "always",
    "ask",
    "avoid",
    "call",
    "check",
    "choose",
    "consider",
    "do",
    "don't",
    "ensure",
    "fill",
    "give",
    "include",
    "keep",
    "leave",
    "look",
    "make",
    "mark",
    "never",
    "note",
    "omit",
    "pass",
    "pick",
    "prefer",
    "provide",
    "put",
    "read",
    "remember",
    "see",
    "send",
    "set",
    "specify",
    "start",
    "stop",
    "supply",
    "take",
    "try",
    "use",
    "wait",
    "write",
)

#: Начало предложения: начало текста, конец предыдущего предложения, пункт списка, тире.
SENTENCE_START = r"(?:^|[.;:!?]\s+|\n\s*(?:-\s+)?|—\s+)"
IMPERATIVE = re.compile(
    SENTENCE_START + r"(" + "|".join(re.escape(verb) for verb in IMPERATIVE_VERBS) + r")\b",
    re.IGNORECASE,
)

#: Обращение к читателю, оценка, объяснение, пример ситуации — где бы ни стояли.
PRESCRIBING = re.compile(
    r"\b(you|your|should|must|please|better|best|worse|worst|good|bad|valuable|"
    r"because|last resort|last choice|for example|for instance|when to use)\b",
    re.IGNORECASE,
)

#: Длина отрезка слов, общего у двух описаний, который считается повторённой фразой.
#: Пять слов ловят уже общие связки вида «only a `main` token …» у разных инструментов,
#: шесть — начало настоящего повтора предложения.
REPEATED_PHRASE_WORDS = 6

#: Аргументы, общие у многих инструментов: их описание одно на весь сервер и повторяется
#: в каждом инструменте, который их принимает.
SHARED_ARGUMENTS = frozenset({"key", "idempotency_key", "limit", "cursor"})

#: Код отказа на конфликт у инструментов, которым есть с чем конфликтовать, кроме ключа
#: повтора: занятый ключ, повтор связи, связи нет, участника нет.
CONFLICT_CODES = {
    ("create_project", "key"): "project_key_taken",
    ("register_participant", "name"): "participant_name_taken",
    ("update_participant", "name"): "participant_not_found",
    ("link", None): "link_exists",
    ("unlink", None): "link_not_found",
}

#: Примеры формата: ключ задачи, ключ проекта, ссылка на запись, UUID, ключ сортировки.
FORMAT_EXAMPLE = re.compile(
    r"^(?:[A-Z][A-Z0-9]*-\d+(?:#\d+)?"
    r"|[A-Z][A-Z0-9]+"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|-?[a-z_]+)$"
)


@pytest.fixture
async def tools(mcp_session: Connect, main_secret: str) -> list[Tool]:
    async with mcp_session(main_secret) as session:
        listed = (await session.list_tools()).tools
    assert listed, "список инструментов пуст: проверять нечего"
    return listed


def descriptions(node: Any, path: str) -> Iterator[tuple[str, str]]:
    """Все описания схемы вглубь: свойства, `$defs`, элементы списков, варианты."""
    if isinstance(node, dict):
        text = node.get("description")
        if isinstance(text, str):
            yield path, text
        for name, value in node.items():
            # Строка под ключом `description` — описание узла; словарь под тем же ключом —
            # свойство с именем `description` (аргумент `create_task.description`).
            if not (name == "description" and isinstance(value, str)):
                yield from descriptions(value, f"{path}/{name}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from descriptions(value, f"{path}/{index}")


def model_reads(tool: Tool) -> Iterator[tuple[str, str]]:
    """Всё, что модель читает у инструмента: описание и описания обеих схем."""
    yield tool.name, tool.description or ""
    yield from descriptions(tool.input_schema, f"{tool.name}/input")
    yield from descriptions(tool.output_schema or {}, f"{tool.name}/output")


def unwrapped(text: str) -> str:
    """Текст без переносов вёрстки: докстрока свёрстана по ширине, а перенос строки
    внутри абзаца — не начало предложения. Абзацы и пункты списка остаются."""
    return re.sub(r"(?<!\n)\n(?!\n|- )", " ", text)


def examples(node: Any) -> Iterator[Any]:
    """Все значения `examples` схемы вглубь, списки развёрнуты до строк."""
    if isinstance(node, dict):
        for name, value in node.items():
            if name == "examples" and isinstance(value, list):
                for item in value:
                    yield from item if isinstance(item, list) else [item]
            else:
                yield from examples(value)
    elif isinstance(node, list):
        for value in node:
            yield from examples(value)


async def test_the_tool_list_has_no_cyrillic(tools: list[Tool]) -> None:
    """Обзорная проверка 3: вся метадата английская, включая схемы и перечисления."""
    dumped = json.dumps([tool.model_dump(mode="json") for tool in tools], ensure_ascii=False)
    found = re.findall(r".{0,40}[\u0400-\u04ff]+.{0,40}", dumped)

    assert not found, "кириллица в tools/list:\n" + "\n".join(found[:20])


async def test_no_metadata_prescribes_judges_or_explains(tools: list[Tool]) -> None:
    """Обзорная проверка 4: ни повелительного наклонения, ни оценок, ни «because».

    Правило, выраженное советом или запретом, переписывается определением или условием
    (TRK-140#18); здесь ловится грамматический след того, что переписать забыли.
    """
    offending: list[str] = []
    for tool in tools:
        for where, wrapped in model_reads(tool):
            text = unwrapped(wrapped)
            for found in (*IMPERATIVE.finditer(text), *PRESCRIBING.finditer(text)):
                said = " ".join(text[max(0, found.start() - 50) : found.end() + 50].split())
                offending.append(f"{where}: «{found.group(0).strip()}» — …{said}…")

    assert not offending, "метадата предписывает, оценивает или объясняет:\n" + "\n".join(offending)


async def test_no_phrase_repeats_across_tool_descriptions(tools: list[Tool]) -> None:
    """Обзорная проверка 4: одно правило — у одного инструмента.

    Сравниваются описания инструментов между собой отрезками по шесть слов. Описания
    общих аргументов (`key`, `idempotency_key`, `limit`, `cursor`) повторяются по
    построению и в сравнение не входят: это не описания инструментов.
    """
    owners: defaultdict[str, set[str]] = defaultdict(set)
    for tool in tools:
        words = re.findall(r"[\w`'#.-]+", (tool.description or "").lower())
        for start in range(len(words) - REPEATED_PHRASE_WORDS + 1):
            owners[" ".join(words[start : start + REPEATED_PHRASE_WORDS])].add(tool.name)

    repeated = sorted(
        f"{sorted(names)}: {phrase}" for phrase, names in owners.items() if len(names) > 1
    )

    assert not repeated, "фраза повторена в описаниях разных инструментов:\n" + "\n".join(repeated)


async def test_every_tool_description_fits_the_client_limit(tools: list[Tool]) -> None:
    """Обзорная проверка 5: описание не длиннее 2048 единиц UTF-16, как считает клиент."""
    lengths = {tool.name: len((tool.description or "").encode("utf-16-le")) // 2 for tool in tools}
    too_long = {
        name: length for name, length in lengths.items() if length > CLIENT_DESCRIPTION_LIMIT
    }

    assert not too_long, f"описания длиннее {CLIENT_DESCRIPTION_LIMIT}: {too_long}"


async def test_examples_show_formats_only(tools: list[Tool]) -> None:
    """Примеры в схеме — только формата: ключи, ссылка на запись, UUID, язык запросов."""
    content: list[str] = []
    for tool in tools:
        for schema in (tool.input_schema, tool.output_schema or {}):
            for value in examples(schema):
                is_format = isinstance(value, str) and (
                    FORMAT_EXAMPLE.match(value) is not None or value in QUERY_EXAMPLES
                )
                if not is_format:
                    content.append(f"{tool.name}: {value!r}")

    assert not content, "содержательные примеры в схеме:\n" + "\n".join(content)


async def test_every_creating_tool_names_its_conflict_code(tools: list[Tool]) -> None:
    """Обзорная проверка 6: код отказа на конфликт назван у инструмента или его поля.

    У каждого создающего инструмента есть ключ повтора, и его описание называет отказ
    на тот же ключ с другими аргументами; у остальных конфликтов код назван там, где
    конфликт возникает — у поля или в описании инструмента.
    """
    by_name = {tool.name: tool for tool in tools}
    missing: list[str] = []
    for tool in tools:
        properties = tool.input_schema.get("properties") or {}
        if "idempotency_key" in properties:
            described = properties["idempotency_key"].get("description") or ""
            if "idempotency_key_reused" not in described:
                missing.append(f"{tool.name}.idempotency_key: idempotency_key_reused")
    for (name, argument), code in CONFLICT_CODES.items():
        tool = by_name[name]
        if argument is None:
            text = tool.description or ""
        else:
            text = tool.input_schema["properties"][argument].get("description") or ""
        if code not in text:
            missing.append(f"{name}{'' if argument is None else '.' + argument}: {code}")

    assert not missing, "код конфликта не назван:\n" + "\n".join(missing)


async def test_every_page_says_what_an_empty_cursor_means(tools: list[Tool]) -> None:
    """Обзорная проверка 6: у выдачи страницей названо, что значит `next_cursor: null`."""
    paged = [
        tool
        for tool in tools
        if "next_cursor" in ((tool.output_schema or {}).get("properties") or {})
    ]
    assert paged, "ни одной выдачи страницей: проверять нечего"

    for tool in paged:
        described = tool.output_schema["properties"]["next_cursor"].get("description") or ""  # type: ignore[index]
        assert "`null`" in described and "last" in described, (
            f"{tool.name}: не сказано, что пустой `next_cursor` — последняя страница"
        )


async def test_no_tool_description_repeats_what_every_entry_does(tools: list[Tool]) -> None:
    """Свойство каждой записи — видна в ленте и человеку, будит ждущих — стоит один раз.

    Его место — `instructions` (TRK-141#17, спорное 1, решено TRK-140#21): повторённое в
    описаниях десяти инструментов, оно стоило контекста и расходилось бы при правке.
    """
    repeating = [
        tool.name
        for tool in tools
        if re.search(r"\bwakes\b|\binterface\b|visible to", tool.description or "", re.IGNORECASE)
    ]

    assert not repeating, f"описание повторяет свойство каждой записи: {repeating}"


async def test_no_description_names_another_status_for_waiting_for_an_answer(
    tools: list[Tool],
) -> None:
    """Абзац про ожидание ответа называет только `waiting` (TRK-31).

    Ожидание ответа — `waiting`, решение владельца (`CONCEPT.md`, 3.3). Прежде статус
    сверялся со скилом; скила нет, и эталон — сам статус домена.
    """
    about_answer = re.compile(r"\banswer", re.IGNORECASE)
    about_waiting = re.compile(r"wait", re.IGNORECASE)
    waiting = TaskStatus.WAITING.value

    diverged: list[str] = []
    for tool in tools:
        for where, text in model_reads(tool):
            for paragraph in (block for block in re.split(r"\n\s*\n", text) if block.strip()):
                if not (about_answer.search(paragraph) and about_waiting.search(paragraph)):
                    continue
                named = {
                    status.value
                    for status in TaskStatus
                    if re.search(rf"(?<![a-z_]){status.value}(?![a-z_])", paragraph)
                }
                if named - {waiting}:
                    diverged.append(f"{where}: {sorted(named - {waiting})}")

    assert not diverged, "ожидание ответа названо не `waiting`:\n" + "\n".join(diverged)


async def test_shared_arguments_are_described_once_for_the_whole_server(
    tools: list[Tool],
) -> None:
    """Общий аргумент описан одинаково у всех инструментов: одно поле — одно описание."""
    seen: defaultdict[str, set[str]] = defaultdict(set)
    for tool in tools:
        for name, schema in (tool.input_schema.get("properties") or {}).items():
            if name in SHARED_ARGUMENTS and name != "key":
                seen[name].add(schema.get("description") or "")

    assert all(len(texts) == 1 for texts in seen.values()), dict(seen)


def test_the_text_detectors_catch_what_they_are_for() -> None:
    """Сами детекторы: ловят предписание и не ловят описание, перенос вёрстки — не начало."""
    assert IMPERATIVE.search(unwrapped("Returns a page.\nUse `get_task` for one task."))
    assert IMPERATIVE.search("Entry types:\n- Pass the key of the task")
    assert IMPERATIVE.search("One call. Never edit an entry")
    assert not IMPERATIVE.search(unwrapped("a verdict on every review\ncheck within the pass"))
    assert not IMPERATIVE.search("Returns entries; Marks the call; Sets nothing")
    assert PRESCRIBING.search("a failed attempt is more valuable than a success")
    assert PRESCRIBING.search("note is the last choice")
    assert PRESCRIBING.search("it is refused because the key is taken")
    assert not PRESCRIBING.search("Returns the entries in number order")
