"""`skills/casefile/SKILL.md` — единственный файл скила Casefile (TRK-402, TRK-398#7).

Один и тот же файл отдают плагин маркетплейса (`.claude-plugin/`, TRK-404) и сам сервер
по SEP-2640 (`skill://casefile/SKILL.md`, TRK-403). Формат — agentskills.io: фронтматтер
из двух ключей, `name` равен имени каталога скила, `description` не длиннее 1024
символов. `allowed-tools` и прочие ключи не допускаются: харнессы понимают их по-разному,
а скил не расширяет права агента.

YAML-библиотеки в зависимостях нет, поэтому фронтматтер разбирается здесь строго и узко:
каждая строка — `ключ: значение` одной строкой, значение — простой скаляр YAML без
`: ` и ` #` внутри и без кавычек и спецсимволов в начале. Всё, что шире, — отказ теста,
а не догадка: так любой разборщик YAML в харнессе прочтёт те же два значения.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_ROOT / "skills" / "casefile"
SKILL_FILE = SKILL_DIR / "SKILL.md"

DESCRIPTION_LIMIT = 1024
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
