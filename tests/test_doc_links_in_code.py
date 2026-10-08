"""Ссылки на документы `…docs/….md` в комментариях кода ведут на существующие файлы (TRK-646).

Комментарий «см. `docs/notes/api.md`» читает следующий агент и идёт по нему в файл. Файл
переехал или исчез (документы уходят в трекер: TRK-610, 612–615), а ссылка осталась —
агент упирается в пустое место. Тест сверяет каждую такую ссылку с деревом и называет
`файл:строка` и то, на что она указывает. Ссылка с якорем (`docs/CONCEPT.md §4.4`,
`docs/notes/api.md#…`) считается ссылкой на файл.

Ссылка живая, если файл существует от каталога файла со ссылкой, от `ui/` или от корня
репозитория. Исполняется в контейнере: репозиторий в нём смонтирован целиком.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Где ищем: код бэкенда, его тесты и скрипты, исходники интерфейса, его тестовая обвязка и e2e.
SCANNED = ("app", "tests", "scripts", "ui/src", "ui/testing", "ui/e2e")

SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".ps1", ".css", ".yml", ".yaml"})
SKIPPED_DIRS = frozenset({"node_modules", "__pycache__", "dist", ".venv"})

#: Ссылка на документ: путь с отрезком `docs/` и расширением `.md`.
DOC_LINK = re.compile(r"[A-Za-z0-9_./-]*docs/[A-Za-z0-9_./-]+\.md")

#: Адрес с протоколом ведёт во внешний мир (GitHub), а не в дерево: из строки вырезается.
#: Хвост адреса, собранного из частей (`f"{REPOSITORY}/blob/main/docs/x.md"`), начинается с `/`:
#: ссылка с первой косой чертой — не путь в дереве, её пропускаем.
URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+")

#: Заведомо несуществующие примеры «неверной ссылки» (проверки полей `refs`), а не ссылки на документ.
EXAMPLE_LINKS = frozenset({"docs/x.md"})

THIS_FILE = Path(__file__).resolve()


def _scanned_files() -> list[Path]:
    found: list[Path] = []
    for top in SCANNED:
        for path in sorted((PROJECT_ROOT / top).rglob("*")):
            relative = path.relative_to(PROJECT_ROOT)
            if SKIPPED_DIRS & set(relative.parts):
                continue
            if path.is_file() and path.suffix in SUFFIXES and path != THIS_FILE:
                found.append(path)
    return found


def _links(path: Path) -> list[tuple[int, str]]:
    """Номер строки и ссылка на документ — для каждой в файле."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for link in DOC_LINK.findall(URL.sub(" ", line)):
            if link not in EXAMPLE_LINKS and not link.startswith("/"):
                found.append((number, link))
    return found


def _exists(path: Path, link: str) -> bool:
    return any((base / link).is_file() for base in (path.parent, PROJECT_ROOT / "ui", PROJECT_ROOT))


def test_the_scan_sees_the_code_and_its_links() -> None:
    """Сканер промахнулся каталогом или шаблоном — проверка ниже зеленеет на пустом множестве."""
    files = _scanned_files()
    assert len(files) > 200, "исходники для сверки ссылок не найдены"
    assert sum(len(_links(path)) for path in files) > 100, "ссылки на документы не найдены"


def test_the_links_resolver_catches_a_missing_and_an_existing_file() -> None:
    sample = PROJECT_ROOT / "ui" / "src" / "shared" / "api" / "x.ts"
    assert _exists(sample, "docs/CONVENTIONS.md")
    assert _exists(sample, "ui/docs/FRONTEND.md")
    assert not _exists(sample, "../docs/FRONTEND.md")
    assert not _exists(sample, "docs/no-such-document.md")


def test_every_document_link_in_code_points_to_an_existing_file() -> None:
    """Битая ссылка в комментарии: названы файл, строка и то, на что она указывает."""
    broken = [
        f"{path.relative_to(PROJECT_ROOT)}:{number}: ссылка на `{link}`, такого файла нет "
        "(ни рядом, ни от ui/, ни от корня)"
        for path in _scanned_files()
        for number, link in _links(path)
        if not _exists(path, link)
    ]
    assert not broken, (
        "Комментарии кода ссылаются на несуществующие документы. Поправь ссылку на нынешний "
        "путь или, если документа больше нет, убери её (документы переезжают в трекер — "
        "тогда ссылку ведут туда, куда указал итог переноса):\n" + "\n".join(broken)
    )
