"""Фразы, которые человек копирует и говорит своему агенту (`TRK-360#40`, `TRK-387`).

Настоящая работа идёт двумя ходами в двух сессиях: `create_tasks` («завести задачи») —
агент на сильной модели заводит проект и режет работу человека на задачи;
`execute_tasks` («выполнить задачи») — в новой сессии, с чистым контекстом, агент берёт
эти задачи и раздаёт агентам на дешёвых моделях, по одной на агента. Между ходами
контекст теряется целиком: второй агент знает только то, что лежит в трекере.

Фразы читают несколько мест продукта — экран «Начало» и экран подключения агента,
установщики, `README.md`, отчёт агента-установщика, — и копии обязаны совпадать
дословно. Источник один — этот модуль; копии сводит сплошная проверка
`tests/test_agent_phrases_everywhere.py` (`TRK-367`). Правка текста здесь — правка всех
копий в той же ветке.
"""

from dataclasses import dataclass
from typing import Literal

#: Языки, на которых интерфейс показывает фразы; английский — ещё и установщики и README.
type PhraseLanguage = Literal["en", "ru"]
PHRASE_LANGUAGES: tuple[PhraseLanguage, ...] = ("en", "ru")


@dataclass(frozen=True, slots=True)
class AgentPhrases:
    """Две фразы двух ходов: завести задачи и выполнить их в новой сессии."""

    create_tasks: str
    execute_tasks: str


AGENT_PHRASES: dict[PhraseLanguage, AgentPhrases] = {
    "en": AgentPhrases(
        create_tasks=(
            "File tasks in Casefile for my work: a project for it if there is none yet, and "
            "tasks with all their sections and checks, each small enough for one agent to "
            "finish in one go, each naming its environment in `context` — where the work lives "
            "and how to run its checks. Don't start the work itself; if I haven't described it "
            "yet, ask me."
        ),
        execute_tasks=(
            "Carry out the tasks for this work from the Casefile tracker. Hand them to agents, "
            "one task per agent, to save your own context, and give them cheaper models "
            "where those cope."
        ),
    ),
    "ru": AgentPhrases(
        create_tasks=(
            "Заведи в Casefile задачи по моей работе: проект под неё, если его ещё нет, и "
            "задачи со всеми разделами и проверками — каждая такая, чтобы один агент выполнил "
            "её за один заход, и в разделе `context` каждой названо её окружение: где лежит "
            "работа и как запускать её проверки. Саму работу не начинай; если я её ещё не "
            "описал, спроси меня."
        ),
        execute_tasks=(
            "Выполни задачи по этой работе из трекера Casefile. Раздавай их агентам, по одной "
            "задаче на агента, чтобы беречь свой контекст, и бери для них модели подешевле, "
            "если они справляются."
        ),
    ),
}
