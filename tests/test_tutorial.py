"""Тексты учебного проекта `START` и фразы для агента (`TRK-366`).

Засева здесь нет — он в своей задаче; проверяется, что тексты годятся для засева и равны
на двух языках. Годятся — значит, трекер примет их теми же правилами, что задачу агента:
описание проекта в пределе, задача уходит в `open` (четыре непустых раздела и проверки),
поля уже в каноническом виде. Равны — значит, установка на любом языке заводит тот же
набор задач с тем же числом проверок: тексты правятся парой, а не по одному.
"""

import re

import pytest

from app.domain.projects import validate_project_description, validate_project_key
from app.domain.tasks import TEXT_SECTIONS, TaskField, normalize_fields
from app.domain.tutorial import (
    AGENT_PHRASES,
    INTRODUCTION_TASK_KEY,
    MOVE_LINES,
    TUTORIAL_LANGUAGES,
    TUTORIAL_PROJECT_KEY,
    TUTORIAL_PROJECTS,
    TutorialTask,
)

_TASKS = [
    pytest.param(language, number, task, id=f"{language}-{number}")
    for language in TUTORIAL_LANGUAGES
    for number, task in enumerate(TUTORIAL_PROJECTS[language].tasks, start=1)
]


def _fields(task: TutorialTask) -> dict[TaskField, object]:
    return {
        TaskField.TITLE: task.title,
        TaskField.DESCRIPTION: task.description,
        TaskField.GOAL: task.goal,
        TaskField.CONTEXT: task.context,
        TaskField.CONSTRAINTS: task.constraints,
        TaskField.OUTPUT: task.output,
        TaskField.CHECKS: list(task.checks),
    }


def _sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?:\s|$)", text.strip()))


def test_every_language_has_project_and_phrases() -> None:
    assert set(TUTORIAL_PROJECTS) == set(TUTORIAL_LANGUAGES)
    assert set(AGENT_PHRASES) == set(TUTORIAL_LANGUAGES)
    assert validate_project_key(TUTORIAL_PROJECT_KEY) == TUTORIAL_PROJECT_KEY


@pytest.mark.parametrize("language", TUTORIAL_LANGUAGES)
def test_project_description_fits_the_limit(language: str) -> None:
    project = TUTORIAL_PROJECTS[language]
    assert project.title.strip()
    assert validate_project_description(project.description) == project.description


@pytest.mark.parametrize(("language", "number", "task"), _TASKS)
def test_task_is_accepted_as_is_and_can_open(
    language: str, number: int, task: TutorialTask
) -> None:
    fields = _fields(task)
    # Канонический вид равен исходному: трекер не поправит текст молча при засеве.
    assert normalize_fields(fields) == fields
    # Условие перехода в `open` (`check_sections_filled_before_open`).
    assert all(fields[section] for section in TEXT_SECTIONS), f"{language}-{number}"
    assert task.checks


def test_languages_have_the_same_tasks() -> None:
    """Одинаковый набор задач: столько же задач, столько же проверок у каждой."""
    shapes = {
        language: [len(task.checks) for task in TUTORIAL_PROJECTS[language].tasks]
        for language in TUTORIAL_LANGUAGES
    }
    assert len(set(map(tuple, shapes.values()))) == 1, shapes


def test_languages_name_the_same_keys_and_tools() -> None:
    """Ключи задач и имена инструментов в тексте — одни на обоих языках.

    Перевод может разойтись по смыслу незаметно для теста, но не по тому, что агент
    вызывает: пропавший в одном языке `resolve` или `waiting` — это другая задача.
    """

    def names(task: TutorialTask) -> set[str]:
        text = " ".join([task.goal, task.context, task.constraints, task.output, *task.checks])
        keys = re.findall(rf"{TUTORIAL_PROJECT_KEY}-\d+", text)
        # Заготовка вида `START-1#<её номер>` переводится вместе с текстом — не имя.
        names = {name for name in re.findall(r"`([^`]+)`", text) if "<" not in name}
        return names | set(keys)

    for position in range(len(TUTORIAL_PROJECTS[TUTORIAL_LANGUAGES[0]].tasks)):
        found = {
            language: names(TUTORIAL_PROJECTS[language].tasks[position])
            for language in TUTORIAL_LANGUAGES
        }
        assert len({frozenset(value) for value in found.values()}) == 1, found


@pytest.mark.parametrize("language", TUTORIAL_LANGUAGES)
def test_introduction_phrase_is_short_and_names_the_task(language: str) -> None:
    phrase = AGENT_PHRASES[language].introduction
    assert INTRODUCTION_TASK_KEY in phrase
    assert 1 <= _sentences(phrase) <= 2, phrase
    assert f"{TUTORIAL_PROJECT_KEY}-1" == INTRODUCTION_TASK_KEY
    assert TUTORIAL_PROJECTS[language].tasks, "фраза называет задачу, которой нет"


@pytest.mark.parametrize("language", TUTORIAL_LANGUAGES)
def test_two_move_phrases_do_not_assume_the_tutorial(language: str) -> None:
    """«Завести задачи» и «выполнить задачи» годятся установке без учебного проекта."""
    phrases = AGENT_PHRASES[language]
    for phrase in (phrases.create_tasks, phrases.execute_tasks):
        assert phrase and phrase.strip() == phrase
        assert TUTORIAL_PROJECT_KEY not in phrase


@pytest.mark.parametrize("language", TUTORIAL_LANGUAGES)
def test_memo_ends_with_both_move_lines_word_for_word(language: str) -> None:
    """Памятка учебной задачи отдаёт человеку те же фразы, что экран «Начало».

    Фразы едут в готовых строках ходов, и учебная задача велит закончить ими памятку.
    """
    first = TUTORIAL_PROJECTS[language].tasks[0]
    phrases = AGENT_PHRASES[language]
    create_line, execute_line = MOVE_LINES[language]
    assert f"«{phrases.create_tasks}»" in create_line
    assert f"«{phrases.execute_tasks}»" in execute_line
    assert create_line in first.output
    assert execute_line in first.output
