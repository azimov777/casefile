"""Сверка копий двух фраз для агента (`AGENT_PHRASES`) во всех местах, куда они
переписаны дословно (TRK-367, TRK-387).

Источник — `AGENT_PHRASES` в `app/domain/agent_phrases.py`. Английский текст повторяется
в выводе `install.sh` и `install.ps1`, в `README.md` и в `docs/agent-install.md`, а
также в словаре экрана «Начало» для английского языка
(`ui/src/shared/i18n/dictionaries/en/start.ts`); русский текст — в том же словаре для
русского (`ru/start.ts`). Копия, лежащая в нескольких местах, сводится сплошной проверкой
множеств, а не вычиткой (`docs/CONVENTIONS.md`, «Документация»; образец —
`app/api/contract.py` и `tests/test_api_contract.py`).

`install.ps1` кодирует апостроф внутри одинарных кавычек его удвоением (`Don''t`) —
это синтаксис PowerShell, а не другой текст: напечатанная агенту строка получается той
же, что и везде. `install.sh` таким же образом экранирует обратную кавычку вокруг
context внутри двойных кавычек обратным слэшем — иначе оболочка приняла бы её за
начало подстановки команды. Сверка снимает то и другое перед поиском фразы, и только
для своего файла: печатаемый агенту текст от экранирования не меняется.
"""

from pathlib import Path

import pytest

from app.domain.agent_phrases import AGENT_PHRASES, PHRASE_LANGUAGES

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    assert path.is_file(), f"нет файла {path}"
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    """Схлопывает пробелы и переносы строк.

    Markdown переносит длинный абзац на несколько строк ради читаемости на GitHub —
    перенос не должен ронять сверку с однострочной фразой из `AGENT_PHRASES`.
    """
    return " ".join(text.split())


def _normalize_sh(text: str) -> str:
    """То же плюс снятие экранирования обратной кавычки — синтаксис `sh` внутри двойных
    кавычек: без `\\` перед `` ` `` оболочка приняла бы её за подстановку команды."""
    return _normalize(text.replace("\\`", "`"))


PS1_EM_DASH = "' + [char]0x2014 + '"


def _normalize_ps1(text: str) -> str:
    """То же плюс снятие двух записей PowerShell: удвоение одинарной кавычки (апостроф) и
    `' + [char]0x2014 + '` (длинное тире кодом, чтобы вывод не зависел от кодировки файла)."""
    return _normalize(text.replace(PS1_EM_DASH, "\u2014").replace("''", "'"))


def _phrases(language: str) -> tuple[str, str]:
    phrases = AGENT_PHRASES[language]  # type: ignore[index]
    return (phrases.create_tasks, phrases.execute_tasks)


ENGLISH_PHRASES = _phrases("en")
RUSSIAN_PHRASES = _phrases("ru")

#: Место в репозитории -> путь файла, без `install.sh`/`install.ps1`: у обоих своё
#: экранирование, и каждый сверяется отдельной проверкой ниже со своим снятием.
ENGLISH_SOURCES = {
    "README.md": PROJECT_ROOT / "README.md",
    "docs/agent-install.md": PROJECT_ROOT / "docs" / "agent-install.md",
    "ui/src/shared/i18n/dictionaries/en/start.ts": (
        PROJECT_ROOT / "ui" / "src" / "shared" / "i18n" / "dictionaries" / "en" / "start.ts"
    ),
}

RU_START_DICTIONARY = (
    PROJECT_ROOT / "ui" / "src" / "shared" / "i18n" / "dictionaries" / "ru" / "start.ts"
)


def test_english_phrases_match_agent_phrases_word_for_word() -> None:
    """README, отчёт агента-установщика и словарь `en/start.ts` несут обе фразы дословно."""
    for name, path in ENGLISH_SOURCES.items():
        content = _normalize(_read(path))
        for phrase in ENGLISH_PHRASES:
            assert _normalize(phrase) in content, f"{name}: фраза не найдена дословно: {phrase!r}"


def test_install_sh_matches_agent_phrases_word_for_word() -> None:
    """Обратная кавычка внутри `\\`context\\`` — экранирование `sh`, не другая фраза."""
    content = _normalize_sh(_read(PROJECT_ROOT / "install.sh"))
    for phrase in ENGLISH_PHRASES:
        assert _normalize(phrase) in content, f"install.sh: фраза не найдена дословно: {phrase!r}"


def test_install_ps1_matches_agent_phrases_word_for_word() -> None:
    """Близнец `install.sh`: те же две фразы, апостроф — синтаксисом PowerShell."""
    content = _normalize_ps1(_read(PROJECT_ROOT / "install.ps1"))
    for phrase in ENGLISH_PHRASES:
        assert _normalize(phrase) in content, f"install.ps1: фраза не найдена дословно: {phrase!r}"


def test_russian_phrases_match_agent_phrases_in_ru_start_dictionary() -> None:
    """Русский текст фраз живёт только в словаре экрана «Начало» для русского языка."""
    content = _normalize(_read(RU_START_DICTIONARY))
    for phrase in RUSSIAN_PHRASES:
        assert _normalize(phrase) in content, f"ru/start.ts: фраза не найдена дословно: {phrase!r}"


def test_install_ps1_code_lines_are_ascii() -> None:
    """Вне комментариев в `install.ps1` только ASCII: Windows PowerShell 5.1 читает файл
    без BOM в cp1252, и литерал вроде `\u2014` в `Write-Host` вышел бы мусором (TRK-380)."""
    lines = _read(PROJECT_ROOT / "install.ps1").splitlines()
    bad = [
        f"{number}: {line}"
        for number, line in enumerate(lines, start=1)
        if not line.lstrip().startswith("#") and not line.isascii()
    ]
    assert not bad, "не-ASCII в строках кода install.ps1: " + "; ".join(bad)


def test_every_language_has_both_phrases() -> None:
    assert set(AGENT_PHRASES) == set(PHRASE_LANGUAGES)
    for language in PHRASE_LANGUAGES:
        for phrase in _phrases(language):
            assert phrase and phrase.strip() == phrase, language


@pytest.mark.parametrize("language", PHRASE_LANGUAGES)
def test_create_tasks_phrase_names_environment_requirement(language: str) -> None:
    """Слово владельца (`TRK-366#66`): каждая заведённая задача называет своё окружение."""
    phrase = AGENT_PHRASES[language].create_tasks.lower()
    keyword = {"ru": "окружен", "en": "environment"}[language]
    assert keyword in phrase


#: Следы учебного проекта, которых не должно быть ни в одной копии (TRK-387): фраза
#: «знакомство» называла учебную задачу `START-1`.
TUTORIAL_TRACES = ("START-1", "tutorial task", "учебную задачу")

#: Все места с копиями, включая оба установщика.
ALL_COPIES = {
    **ENGLISH_SOURCES,
    "install.sh": PROJECT_ROOT / "install.sh",
    "install.ps1": PROJECT_ROOT / "install.ps1",
    "ui/src/shared/i18n/dictionaries/ru/start.ts": RU_START_DICTIONARY,
}


@pytest.mark.parametrize("name", sorted(ALL_COPIES))
def test_no_copy_names_the_tutorial_task(name: str) -> None:
    content = _read(ALL_COPIES[name])
    found = [trace for trace in TUTORIAL_TRACES if trace in content]
    assert not found, f"{name}: след учебного проекта: {found}"
