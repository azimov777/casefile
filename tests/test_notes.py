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
