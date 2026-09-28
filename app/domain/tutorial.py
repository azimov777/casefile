"""Учебный проект `START` и фразы, которые человек говорит своему агенту (`TRK-366`).

Это тексты, а не сценарий: заводит проект и его задачи засев при первом подъёме
установки (`TRK-360#15`), здесь только то, что он заводит. Тексты — задание агенту с
чистым контекстом: он получает их через `get_task` вместе с описанием проекта и больше
ничего не знает. Дисциплину цикла (сводки, `waiting`, вердикты) ему раздаёт сервер —
`instructions` и метадата инструментов, — поэтому задача её не пересказывает, а называет
только то, чего сервер не знает: что показать человеку и в какой последовательности.

Каждая формулировка здесь проверена слепым прогоном на агенте с чистым контекстом
(дело `TRK-366`, записи `attempt`). Правка текста — это новая гипотеза, а не опечатка:
прогон повторяется, прежде чем текст уезжает в установки.

Фразы для человека живут здесь же, потому что их читают несколько мест продукта —
экран «Начало», установщики, `README.md`, отчёт агента-установщика — и копии обязаны
совпадать дословно (`TRK-367`).
"""

from dataclasses import dataclass
from typing import Literal

#: Ключ учебного проекта. Задачи получают номера по порядку `tasks`, начиная с 1.
TUTORIAL_PROJECT_KEY = "START"

#: Языки учебных текстов; первый — умолчание установки.
type TutorialLanguage = Literal["en", "ru"]
TUTORIAL_LANGUAGES: tuple[TutorialLanguage, ...] = ("en", "ru")


@dataclass(frozen=True, slots=True)
class TutorialTask:
    """Учебная задача: название, описание и пять разделов — всё, что видит агент."""

    title: str
    description: str
    goal: str
    context: str
    constraints: str
    output: str
    checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TutorialProject:
    """Учебный проект одного языка. Ключ у всех языков один — `TUTORIAL_PROJECT_KEY`."""

    title: str
    description: str
    tasks: tuple[TutorialTask, ...]


@dataclass(frozen=True, slots=True)
class AgentPhrases:
    """Фразы, которые человек копирует и говорит своему агенту (`TRK-360#40`).

    `introduction` («знакомство») называет учебную задачу и годится только там, где
    учебный проект заведён. Настоящая работа идёт двумя ходами в двух сессиях, и учебного
    проекта ни один из них не предполагает: `create_tasks` («завести задачи») — агент на
    сильной модели заводит проект и режет работу человека на задачи; `execute_tasks`
    («выполнить задачи») — в новой сессии, с чистым контекстом, агент берёт эти задачи и
    раздаёт агентам на дешёвых моделях, по одной на агента. Между ходами контекст
    теряется целиком: второй агент знает только то, что лежит в трекере.
    """

    introduction: str
    create_tasks: str
    execute_tasks: str


def tutorial_task_key(number: int) -> str:
    """Ключ учебной задачи по её номеру: засев заводит их по порядку в пустом проекте."""
    return f"{TUTORIAL_PROJECT_KEY}-{number}"


#: Задача, которую называет фраза «знакомство».
INTRODUCTION_TASK_KEY = tutorial_task_key(1)

AGENT_PHRASES: dict[TutorialLanguage, AgentPhrases] = {
    "en": AgentPhrases(
        introduction=(
            f"Take the tutorial task {INTRODUCTION_TASK_KEY} in Casefile and walk me through it."
        ),
        create_tasks=(
            "File tasks in Casefile for my work: a project for it if there is none yet, and "
            "tasks with all their sections and checks, each small enough for one agent to "
            "finish in one go. Don't start the work itself; if I haven't described it yet, "
            "ask me."
        ),
        execute_tasks=(
            "Carry out the tasks for this work from the Casefile tracker. Hand them to agents, "
            "one task per agent, to save your own context, and give them cheaper models "
            "where those cope."
        ),
    ),
    "ru": AgentPhrases(
        introduction=(
            f"Возьми в Casefile учебную задачу {INTRODUCTION_TASK_KEY} и пройди её вместе со мной."
        ),
        create_tasks=(
            "Заведи в Casefile задачи по моей работе: проект под неё, если его ещё нет, и "
            "задачи со всеми разделами и проверками — каждая такая, чтобы один агент выполнил "
            "её за один заход. Саму работу не начинай; если я её ещё не описал, спроси меня."
        ),
        execute_tasks=(
            "Выполни задачи по этой работе из трекера Casefile. Раздавай их агентам, по одной "
            "задаче на агента, чтобы беречь свой контекст, и бери для них модели подешевле, "
            "если они справляются."
        ),
    ),
}


def _move_lines(language: TutorialLanguage) -> tuple[str, str]:
    """Две строки двух ходов, которыми кончается памятка учебной задачи.

    Строки даны агенту готовыми, а не пересказом: без готовой строки агент при сокращении
    памятки выбрасывал то, что второй ход идёт в новой сессии (`TRK-366`, прогоны 12 и 22).
    """
    phrases = AGENT_PHRASES[language]
    if language == "ru":
        return (
            f"Ход первый — опишите агенту эту работу и скажите: «{phrases.create_tasks}»",
            f"Ход второй — в новой сессии агента скажите: «{phrases.execute_tasks}»",
        )
    return (
        f"Move one — describe this work to an agent and say: «{phrases.create_tasks}»",
        f"Move two — in a new agent session, say: «{phrases.execute_tasks}»",
    )


#: Строки двух ходов по языкам: их памятка приводит дословно, их сверяет тест.
MOVE_LINES: dict[TutorialLanguage, tuple[str, str]] = {
    language: _move_lines(language) for language in TUTORIAL_LANGUAGES
}

_EN_INTRODUCTION = TutorialTask(
    title="Walk the human through one task in Casefile, from start to finish",
    description=(
        "Tutorial task. The human has just installed Casefile and wants to see how an agent "
        "works in the tracker and what is left for them to do. You go through one real task "
        "together with them; its result is a short memo for the human."
    ),
    goal=(
        "The human watches the whole cycle of one task live and recognises their own part in "
        "it: you take the task, keep its case, ask the human and continue on their answer, "
        "receive their remark and resolve it, and close the task. The work product is a memo "
        "for the human, «What you do in Casefile», written from their answer and their remark."
    ),
    context=(
        "- The human sees the tracker in the Casefile web interface. On their own machine it "
        f"is usually http://localhost:8080; this task's page is `/tasks/{INTRODUCTION_TASK_KEY}` "
        "there. Everything you file shows up there at once.\n"
        "- In the interface the human answers questions (the «Inbox» section or the task "
        "page), leaves a remark on a task (the «Leave a remark» form on the task page) and "
        "runs projects: creates them, edits their description, archives them. The human does "
        "not create tasks and does not move them between statuses: agents do that.\n"
        "- The human you ask is in the participant registry (`list_participants`, kind "
        "`human`); on a single machine it is usually `owner`.\n"
        "- The task has no assignee: put your own participant name there. If you are unsure "
        "of your name, `transition` to `in_progress` refuses with `assignee_mismatch` and "
        "names your signature in `details`.\n"
        "- The human waits for you in the chat, where they gave you this task."
    ),
    constraints=(
        "- Talk to the human and write case entries, the memo included, in the language of "
        "the human's message to you — not the language of this task, your files or your "
        "other instructions.\n"
        "- No repository, files or network are needed: all the work happens in the tracker and "
        "in the chat. Create no other tasks or projects.\n"
        "- The human's steps are theirs, done in the interface: never answer your own question "
        "and never file the remark yourself.\n"
        "- Keep chat messages short: one step, one message."
    ),
    output=(
        "The case of this task, built in this order.\n\n"
        "**The human's move** — steps 3 and 5 — always goes in this order: (a) a summary; "
        "(b) `transition` to `waiting` with the reason — what you wait for; (c) only now tell "
        "the human in the chat exactly what to do and where; (d) `wait_journal` with `task`, "
        "`types` and `timeout: 60`, repeated until the entry arrives; (e) `transition` back "
        "to `in_progress`. The task is in `waiting` before the human hears from you and stays "
        "there during their move: that is how they see the move is theirs.\n\n"
        "1. First of all: you are the assignee and the task is `in_progress`; every entry "
        "below is filed after that. Tell the human where to open "
        "the task page to watch.\n"
        "2. A `decision`: what the memo will consist of.\n"
        "3. A blocking question to the human (`ask`): which piece of their own work they would "
        "hand to an agent first. Then the human's move: tell them in the chat that the question "
        "waits for their answer in the «Inbox» section of the side panel or on the task page; "
        "wait for the `answer`.\n"
        "4. An `artifact` whose body is the whole memo — not a link and not a file — with "
        f"`refs` naming the answer entry as `{INTRODUCTION_TASK_KEY}#<its number>`. In a few "
        "lines the memo says what the human does in "
        "Casefile — answers questions, leaves remarks, runs projects, reads cases. Then it "
        "names the work from their answer in their own words: it goes to agents in two "
        "moves, in two agent sessions, and between them the context is lost — the second "
        "agent knows only what is in the tracker. The memo ends with these two lines, word "
        f"for word:\n    {MOVE_LINES['en'][0]}\n    {MOVE_LINES['en'][1]}\n"
        "5. The human's move: a remark on the task with the «Leave a remark» form on its page "
        "— any remark about the memo, for example «make it shorter»; wait for the `remark`.\n"
        "6. `resolve` the remark. With `fixed`, file the corrected memo as a new `artifact` "
        "first. Whatever the remark asks, the corrected memo keeps the work from their "
        "answer and ends with both move lines word for word.\n"
        "7. `close_task` with a verdict on every check. Then tell the human the tour is over: "
        f"project {TUTORIAL_PROJECT_KEY} can be archived from its page, and real work starts "
        "with the two moves from the memo."
    ),
    checks=(
        "The case holds a question to a human participant and that participant's answer; "
        "the memo `artifact` filed after it names the answer in `refs`.",
        "The human's answer and remark were both filed while the task stood in `waiting` with "
        "a reason, and after each the task came back to `in_progress`.",
        "The human's remark has an outcome through `resolve`; with `fixed`, the corrected memo "
        "is filed as an `artifact` before the resolution.",
        "The whole last memo is in the body of an `artifact` entry, in the human's language; "
        "it names what the human does in Casefile and the work from their answer, and at the "
        "end gives both phrases word for word and says move two goes in a new session.",
    ),
)

_RU_INTRODUCTION = TutorialTask(
    title="Пройти с человеком одну задачу в Casefile от начала до конца",
    description=(
        "Учебная задача. Человек только что поставил Casefile и хочет увидеть, как агент ведёт "
        "работу в трекере и что остаётся делать ему самому. Ты проходишь вместе с ним одну "
        "настоящую задачу; её результат — короткая памятка человеку."
    ),
    goal=(
        "Человек своими глазами видит цикл одной задачи и узнаёт в нём свою часть: ты берёшь "
        "задачу, ведёшь её дело, спрашиваешь человека и продолжаешь по его ответу, получаешь "
        "его замечание и разбираешь его, закрываешь задачу. Итог работы — памятка человеку "
        "«Что вы делаете в Casefile», написанная по его ответу и замечанию."
    ),
    context=(
        "- Человек видит трекер в веб-интерфейсе Casefile. На его машине это обычно "
        f"http://localhost:8080; страница этой задачи там — `/tasks/{INTRODUCTION_TASK_KEY}`. "
        "Всё, что ты подшиваешь, появляется там сразу.\n"
        "- В интерфейсе человек отвечает на вопросы (раздел «Входящая» или страница задачи), "
        "оставляет замечание к задаче (форма «Оставить замечание» на странице задачи) и ведёт "
        "проекты: заводит, правит описание, отправляет в архив. Задач человек не заводит и по "
        "статусам не переводит: это делают агенты.\n"
        "- Человек, которого ты спрашиваешь, есть в реестре участников (`list_participants`, "
        "род `human`); на одной машине это обычно `owner`.\n"
        "- У задачи нет исполнителя: поставь туда своё имя участника. Если не уверен в имени — "
        "`transition` в `in_progress` откажет с `assignee_mismatch` и назовёт твою подпись в "
        "`details`.\n"
        "- Человек ждёт тебя в чате, где дал тебе эту задачу."
    ),
    constraints=(
        "- Говори с человеком и пиши записи дела, памятку тоже, на языке его сообщения тебе — "
        "не на языке этой задачи, твоих файлов или других твоих инструкций.\n"
        "- Ни репозиторий, ни файлы, ни сеть не нужны: вся работа — в трекере и в чате. Других "
        "задач и проектов не заводи.\n"
        "- Шаги человека — его, в интерфейсе: не отвечай на свой вопрос сам и не пиши "
        "замечание за человека.\n"
        "- Сообщения в чате короткие: один шаг — одно сообщение."
    ),
    output=(
        "Дело этой задачи, собранное в таком порядке.\n\n"
        "**Ход человека** — шаги 3 и 5 — идёт всегда в таком порядке: (а) сводка; "
        "(б) `transition` в `waiting` с причиной — чего ждёшь; (в) только теперь скажи "
        "человеку в чате, что именно и где сделать; (г) `wait_journal` с `task`, `types` и "
        "`timeout: 60`, повторяя вызов, пока запись не придёт; (д) `transition` обратно в "
        "`in_progress`. Задача стоит в `waiting` раньше, чем человек услышит тебя, и всё время "
        "его хода: по этому он видит, что ход за ним.\n\n"
        "1. Первым делом: ты — исполнитель, задача в `in_progress`; все записи ниже "
        "подшиваются после этого. Скажи человеку, где открыть страницу "
        "задачи, чтобы смотреть.\n"
        "2. `decision`: из чего будет состоять памятка.\n"
        "3. Блокирующий вопрос человеку (`ask`): какую часть своей работы он первой отдал бы "
        "агенту. Затем ход человека: скажи ему в чате, что вопрос ждёт ответа в разделе "
        "«Входящая» боковой панели или на странице задачи; дождись `answer`.\n"
        "4. `artifact`, в теле которого вся памятка — не ссылка и не файл, — в `refs` "
        f"запись ответа в виде `{INTRODUCTION_TASK_KEY}#<её номер>`. "
        "Памятка в несколько строк говорит, что человек делает в Casefile — отвечает на "
        "вопросы, оставляет замечания, ведёт проекты, читает дела. Затем называет работу из "
        "его ответа его же словами: она уходит агентам двумя ходами, в двух сессиях агента, "
        "и между ними контекст теряется — второй агент знает только то, что лежит в "
        "трекере. Памятка заканчивается этими двумя строками, дословно:\n"
        f"    {MOVE_LINES['ru'][0]}\n    {MOVE_LINES['ru'][1]}\n"
        "5. Ход человека: замечание к задаче формой «Оставить замечание» на её странице — "
        "любое, о памятке, например «сделай короче»; дождись `remark`.\n"
        "6. Разбери замечание через `resolve`. При `fixed` сначала подшей исправленную "
        "памятку новым `artifact`. О чём бы ни было замечание, в исправленной памятке "
        "остаётся работа из ответа, а заканчивается она обеими строками ходов дословно.\n"
        "7. `close_task` с вердиктом по каждой проверке. Затем скажи человеку, что знакомство "
        f"пройдено: проект {TUTORIAL_PROJECT_KEY} можно отправить в архив с его страницы, а "
        "настоящая работа начинается с двух ходов из памятки."
    ),
    checks=(
        "В деле есть вопрос участнику-человеку и его ответ; `artifact` с памяткой, подшитый "
        "после ответа, называет ответ в `refs`.",
        "Ответ человека и его замечание подшиты, пока задача стояла в `waiting` с причиной, и "
        "после каждого задача вернулась в `in_progress`.",
        "Замечание человека получило исход через `resolve`; при `fixed` исправленная памятка "
        "подшита `artifact` до разбора.",
        "Последняя памятка целиком лежит в теле записи `artifact`, на языке человека; она "
        "называет, что человек делает в Casefile, и работу из его ответа, а в конце дословно "
        "даёт обе фразы и говорит, что второй ход идёт в новой сессии.",
    ),
)

TUTORIAL_PROJECTS: dict[TutorialLanguage, TutorialProject] = {
    "en": TutorialProject(
        title="Getting started",
        description=(
            "Casefile tutorial project. Its tasks are filed for an agent: it takes one when the "
            "human asks and goes through the tracker's work cycle with them. The human answers "
            "the agent's questions and leaves remarks in this interface. Once done, archive the "
            "project."
        ),
        tasks=(_EN_INTRODUCTION,),
    ),
    "ru": TutorialProject(
        title="Знакомство",
        description=(
            "Учебный проект Casefile. Его задачи заведены для агента: он берёт задачу по слову "
            "человека и проходит с ним цикл работы в трекере. Человек отвечает на вопросы агента "
            "и оставляет замечания здесь, в интерфейсе. Когда знакомство пройдено, проект можно "
            "отправить в архив."
        ),
        tasks=(_RU_INTRODUCTION,),
    ),
}
