"""Формат записей в `docs/notes/`: у находки есть все четыре поля, и в своём порядке.

Заметки — единственное место, где знание переживает сессию агента: файлы задач
удаляются, отчёты исчезают вместе с контекстом. Правило формата описано в
`docs/CONVENTIONS.md`, разделе «Заметки», но описанное прозой правило никто не
исполняет: к задаче 33 шестьдесят записей из трёхсот шестнадцати остались без «Как
правильно» — то есть называли грабли и не говорили, как их обойти.

Проверка стережёт именно состав полей, а не длину текста: «что» и «почему важно»
пишутся сами собой, а «как правильно» требует решить, что же делать, — и пропускается
первым.
"""

import re
from pathlib import Path

NOTES_DIR = Path(__file__).resolve().parents[1] / "docs" / "notes"

#: Карта папки — не заметка: её `##` перечисляют файлы, а не находки.
FOLDER_MAP = "AGENTS.md"

#: Обязательные поля записи в порядке из соглашений: факт, цена, действие, место.
REQUIRED_FIELDS = ("Что", "Почему важно", "Как правильно", "Где")

#: Заголовок записи: `##` внутри файла области.
ENTRY_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)

#: Имя поля записи — жирная подпись в начале строки. Поля сверх обязательных
#: («Чем ловится») законны, поэтому состав и порядок проверяются только по своим.
FIELD_LABEL = re.compile(r"^\*\*([^:*]+):\*\*", re.MULTILINE)


def _entries() -> list[tuple[str, str, list[str]]]:
    """Все записи всех заметок: файл, заголовок, имена полей по порядку."""
    found: list[tuple[str, str, list[str]]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        if path.name == FOLDER_MAP:
            continue
        chunks = re.split(r"^(?=## )", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for chunk in chunks:
            heading = ENTRY_HEADING.match(chunk)
            if heading is not None:
                found.append((path.name, heading.group(1), FIELD_LABEL.findall(chunk)))
    return found


def test_the_notes_are_parsed_at_all() -> None:
    """Разбор промахнулся — обе проверки ниже зеленеют на пустом множестве."""
    assert len(_entries()) > 100, "записи заметок не разобраны"


def test_every_note_names_all_four_fields() -> None:
    """Запись без «Как правильно» — рассказ о грабле, на которую наступят снова.

    Падение чинится дописыванием поля, а не правкой соседних: заметки только
    дополняются (`docs/CONVENTIONS.md`, раздел «Заметки»).
    """
    incomplete = [
        f"{file}, «{heading}»: нет полей {[f for f in REQUIRED_FIELDS if f not in labels]}"
        for file, heading, labels in _entries()
        if not set(REQUIRED_FIELDS) <= set(labels)
    ]

    assert not incomplete, incomplete


def test_every_note_keeps_the_field_order() -> None:
    """Порядок один на все заметки: инструкция раньше причины читается как каприз."""
    reordered = [
        f"{file}, «{heading}»: порядок полей {[f for f in labels if f in REQUIRED_FIELDS]}"
        for file, heading, labels in _entries()
        if [f for f in labels if f in REQUIRED_FIELDS] != list(REQUIRED_FIELDS)
    ]

    assert not reordered, reordered


# --- Указатели «Где:» ---------------------------------------------------------------

PROJECT_ROOT = NOTES_DIR.parents[1]

#: Поле «Где:» записи: от подписи до следующего поля или конца записи. Многострочное —
#: указатель на два-три места переносится по ширине строки, как и любой другой текст.
WHERE_FIELD = re.compile(r"^\*\*Где:\*\*(.*?)(?=^\*\*|\Z)", re.MULTILINE | re.DOTALL)

#: Токен в обратных кавычках: путь, имя символа или кусок команды.
QUOTED = re.compile(r"`([^`]+)`")

#: Похоже на путь в репозитории: расширение из тех, что в проекте есть, либо косая черта.
LOOKS_LIKE_PATH = re.compile(r"^[\w./-]+\.(py|md|yml|yaml|json|toml|ini|cfg|txt|sh|example)$")

#: Файлы-история: механика снесена, файл оставлен целиком как материал для возможного
#: возврата и помечен баннером в первых строках. Их «Где:» ведут в код, которого нет, и
#: это честно ровно потому, что баннер стоит на всём файле, а не потерян среди живых
#: записей. Список именно списком, а не поиском баннера в тексте: приписать себе
#: освобождение от проверки одной строкой в шапке не должно быть возможно — файл
#: попадает сюда правкой теста, которую видно на ревизии.
HISTORY_ONLY = {"webhooks.md"}


def _where_pointers() -> list[tuple[str, str, str]]:
    """Все указатели «Где:» живых заметок: файл, заголовок записи, текст поля."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        if path.name in (FOLDER_MAP, *HISTORY_ONLY):
            continue
        chunks = re.split(r"^(?=## )", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for chunk in chunks:
            heading = ENTRY_HEADING.match(chunk)
            field = WHERE_FIELD.search(chunk)
            if heading is not None and field is not None:
                found.append((path.name, heading.group(1), field.group(1)))
    return found


def test_every_history_only_note_carries_its_banner() -> None:
    """Освобождение от проверки ниже стоит на баннере — значит, баннер обязан быть.

    Без этой проверки файл из `HISTORY_ONLY` однажды окажется без пометки, и читатель
    примет историю за описание текущего кода — ровно то, от чего освобождение и
    отделяет его.
    """
    missing = [
        name
        for name in sorted(HISTORY_ONLY)
        if "снесена задачей" not in (NOTES_DIR / name).read_text(encoding="utf-8")[:600]
    ]

    assert not missing, missing


def test_every_where_pointer_leads_to_living_code() -> None:
    """Указатель «Где:» ведёт в существующий файл, а названный символ в нём находится.

    Заметку читают **до** кода и верят ей: указатель на удалённый модуль стоит
    следующему агенту получаса поисков поведения, которого нет, и заканчивается выводом
    «документация врёт» — после которого не верят уже и живым записям.

    Символы проверяются только там, где в том же указателе назван хотя бы один файл:
    «Где:» без файла (команда, папка целиком) проверять нечем, и придумывать ему правило
    хуже, чем не проверять.
    """
    problems: list[str] = []
    for name, heading, field in _where_pointers():
        files, symbols = [], []
        for token in QUOTED.findall(field):
            # `.gitignore` и подобные точечные файлы не подходят ни под расширение, ни
            # под косую черту — их выдаёт только само существование в репозитории.
            is_path = (
                LOOKS_LIKE_PATH.match(token) or "/" in token or (PROJECT_ROOT / token).exists()
            )
            (files if is_path else symbols).append(token)

        readable = []
        for token in files:
            target = PROJECT_ROOT / token
            if target.is_file():
                readable.append(target)
            elif not target.is_dir():
                problems.append(f"{name}, «{heading}»: нет файла {token}")

        if not readable:
            continue
        texts = [target.read_text(encoding="utf-8") for target in readable]
        problems += [
            f"{name}, «{heading}»: символа {symbol!r} нет в {[t.name for t in readable]}"
            for symbol in symbols
            if not any(symbol in text for text in texts)
        ]

    assert not problems, problems
