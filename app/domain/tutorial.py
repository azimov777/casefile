"""Учебный проект `START` и фразы, которые человек говорит своему агенту (`TRK-366`).

Это тексты, а не сценарий: заводит проект и его задачи засев при первом подъёме
установки (`TRK-360#15`), здесь только то, что он заводит. Тексты — задание агенту с
чистым контекстом: он получает их через `get_task` вместе с описанием проекта и больше
ничего не знает. Дисциплину цикла (сводки, `waiting`, вердикты) ему раздаёт сервер —
`instructions` и метадата инструментов, — поэтому задача её не пересказывает, а называет
только то, чего сервер не знает: что показать человеку, каким вызовом и в какой
последовательности.

Владелец потребовал от текста трёх вещей (`TRK-366#66`): максимально просто для модели,
явные действия, сведения об окружении в самой задаче. Отсюда устройство модуля:

- Раздел `context` учебной задачи несёт точные значения окружения — адрес доски и имя
  человека — как подстановки `{board_url}` и `{human_name}`; их заполняет
  `render_tutorial_project`, а не сам текст «обычным» приближением.
- Раздел `output` — нумерованный список, один шаг — одно действие; действие в трекере
  названо вызовом инструмента с именами его аргументов, действие в чате — готовой
  строкой. Общей процедуры «ход человека», которую агент прикладывал бы сам к разным
  шагам, здесь нет: её точки повторены на обоих местах, где ход человека нужен.
- Памятку агент не сочиняет: её текст дан целиком, с одним местом для подстановки —
  работой человека его же словами из ответа; это место помечено `<...>`, а не `{...}`,
  чтобы его не спутать с подстановками окружения.

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
        introduction=(
            f"Возьми в Casefile учебную задачу {INTRODUCTION_TASK_KEY} и пройди её вместе со мной."
        ),
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


def _memo_template(language: TutorialLanguage) -> str:
    """Шаблон памятки человеку: одно место для его работы, дальше — обе строки ходов дословно.

    Место для подстановки помечено `<...>`, а не `{...}`: угловые скобки не спутать с
    подстановками окружения `{board_url}`/`{human_name}`, которые заполняет засев, а не
    агент (проверка 6 задачи `TRK-366`).
    """
    create_line, execute_line = MOVE_LINES[language]
    if language == "ru":
        intro = (
            "Что вы делаете в Casefile: отвечаете на вопросы агента, оставляете замечания к "
            "задачам, заводите и ведёте проекты, читаете их дело."
        )
        work = (
            "Вашу работу — <работа из ответа, его же словами> — агенты берут через трекер: "
            "двумя ходами, в двух разных сессиях; между ходами контекст теряется целиком, и "
            "второй агент знает только то, что лежит в трекере."
        )
    else:
        intro = (
            "What you do in Casefile: you answer the agent's questions, leave remarks on "
            "tasks, create and run projects, read their case."
        )
        work = (
            "Your work — <the work from your answer, in your own words> — goes to agents "
            "through the tracker: in two moves, in two separate sessions; between moves the "
            "context is lost completely, and the second agent knows only what is in the "
            "tracker."
        )
    return f"{intro}\n\n{work}\n\n{create_line}\n{execute_line}"


#: Шаблон памятки по языкам: `output` учебной задачи цитирует его целиком.
_MEMO_TEMPLATES: dict[TutorialLanguage, str] = {
    language: _memo_template(language) for language in TUTORIAL_LANGUAGES
}

_EN_INTRODUCTION = TutorialTask(
    title="Walk the human through one task in Casefile, from start to finish",
    description=(
        "Tutorial task. The human has just installed Casefile and wants to see how an agent "
        "works in the tracker and what is left for them to do. You go through one real task "
        "together with them, step by step, and hand them a memo at the end."
    ),
    goal=(
        "The human watches the whole cycle of one task live and recognises their own part in "
        "it: you ask them a question and continue from their answer, take their remark and "
        "resolve it, and close the task. The result is a memo for the human that ends with the "
        "two moves that start their real work."
    ),
    context=(
        "Environment.\n"
        "- Casefile board: `{board_url}`. This task's page: `{board_url}/tasks/START-1`.\n"
        "- The human is participant `{human_name}`; address the question to them.\n"
        '- The human answers a question in the "Inbox" section of the side panel or on the '
        'task page; they leave a remark with the "Leave a remark" form on the task page.\n'
        "- You talk to the human in the chat — the one where you got this phrase.\n"
        "- Everything you file shows up for the human on the board at once."
    ),
    constraints=(
        "- Write case entries and the memo in the language of the human's message to you.\n"
        "- No repository, files or network are needed: all the work happens in the tracker and "
        "the chat. Create no other tasks or projects.\n"
        "- The question and the remark are the human's own steps: never answer your own "
        "question and never file the remark yourself.\n"
        "- Keep chat messages short: one step, one message."
    ),
    output=(
        "Build the case in this order — one numbered step, one action. Below, `key` (`task` "
        "for `wait_journal`) is always `START-1`.\n\n"
        "1. `update_task` — `changes.assignee` your own name, for example `agent`.\n"
        "2. `transition` — `to: in_progress`. Refused with `assignee_mismatch`? Take the name "
        "from the refusal's `details`, redo step 1 with it, then repeat this step.\n"
        '3. In chat, say word for word: "Open `{board_url}/tasks/START-1` — every step will '
        'show up there."\n'
        "4. `ask` — `addressees: [{human_name}]`, `blocking: true`, a `title` and `body` "
        "asking which piece of their own work the human would hand to an agent first.\n"
        "5. `add_summary` — `done`, `remaining`, `blockers`, `next_step`: say you asked the "
        "question and are waiting for the answer.\n"
        "6. `transition` — `to: waiting`, a `reason` naming the question you wait for.\n"
        "7. In chat, say word for word: \"Answer the question in the 'Inbox' section or on "
        "the task page. If after that I have stopped here and gone quiet, write me "
        "'Answered'.\" Do not end your turn after this line: go straight to step 8.\n"
        "8. `wait_journal` — `types: [answer]`, `after: 0`, `timeout: 60`; repeat the call "
        "until an entry comes back. If your client can watch in the background, a watcher "
        "on the answer may replace the call. The human wrote 'Answered'? Do this step "
        "again: the entry is already there.\n"
        "9. `transition` — `to: in_progress`.\n"
        "10. `add_entry` — `type: artifact`, a `title`, `refs: [START-1#<the answer's "
        "number>]`, and a `body` — the memo below, with the work from the answer, in the "
        "human's own words, in place of the one placeholder:\n\n"
        f"{_MEMO_TEMPLATES['en']}\n\n"
        "11. `add_summary` — `done`, `remaining`, `blockers`, `next_step`: say the memo is "
        "filed and you are waiting for a remark.\n"
        "12. `transition` — `to: waiting`, a `reason` naming that you wait for a remark.\n"
        "13. In chat, say word for word: \"Leave any remark on the task with the 'Leave a "
        "remark' form on its page. If after that I have stopped here and gone quiet, write "
        "me 'Remark left'.\" Do not end your turn after this line: go straight to step 14.\n"
        "14. `wait_journal` — `types: [remark]`, `after: 0`, `timeout: 60`; repeat the call "
        "until an entry comes back. If your client can watch in the background, a watcher "
        "on the remark may replace the call. The human wrote 'Remark left'? Do this step "
        "again: the entry is already there.\n"
        "15. `transition` — `to: in_progress`.\n"
        "16. `add_entry` — `type: artifact`, a `title`, `refs: [START-1#<the memo's "
        "number>]`, and a `body` — the same memo with only what the remark asked for "
        "changed; both move lines stay word for word.\n"
        "17. `resolve` — the `remark_no` of the remark, `outcome: fixed`, naming what changed "
        "in `body`.\n"
        "18. `close_task` — a `verdicts` entry for every check and a closing `summary`.\n"
        '19. In chat, say word for word: "The tour is over: project START can be archived '
        'from its page, and real work starts with the two moves from the memo."'
    ),
    checks=(
        "The case holds a question to the human participant and their `answer`.",
        "The `answer` and the `remark` were both filed while the task stood in `waiting` with "
        "a reason, and after each the task came back to `in_progress`.",
        "The `remark` has an outcome through `resolve`; the corrected memo is filed as an "
        "`artifact` before it.",
        "An `artifact` with the memo is filed after the answer, and its `refs` name the "
        "answer's entry.",
    ),
)

_RU_INTRODUCTION = TutorialTask(
    title="Пройти с человеком одну задачу в Casefile от начала до конца",
    description=(
        "Учебная задача. Человек только что поставил Casefile и хочет увидеть, как агент ведёт "
        "работу в трекере и что остаётся делать ему самому. Ты проходишь с ним одну настоящую "
        "задачу шаг за шагом и в конце отдаёшь ему памятку."
    ),
    goal=(
        "Человек своими глазами видит цикл одной задачи и узнаёт в нём свою часть: ты задаёшь "
        "ему вопрос и продолжаешь по ответу, принимаешь его замечание и разбираешь его, "
        "закрываешь задачу. Итог — памятка человеку, которая заканчивается двумя ходами, с "
        "которых начинается его настоящая работа."
    ),
    context=(
        "Окружение.\n"
        "- Доска Casefile: `{board_url}`. Страница этой задачи: `{board_url}/tasks/START-1`.\n"
        "- Человек — участник `{human_name}`; вопрос адресуй ему.\n"
        "- Человек отвечает на вопрос в разделе «Входящая» боковой панели или на странице "
        "задачи; замечание оставляет формой «Оставить замечание» на странице задачи.\n"
        "- Ты говоришь с человеком в чате — там же, где получил эту фразу.\n"
        "- Всё, что ты подшиваешь в дело, в тот же момент видно человеку на доске."
    ),
    constraints=(
        "- Пиши записи дела и памятку на языке сообщения человека тебе.\n"
        "- Репозиторий, файлы и сеть не нужны: вся работа идёт в трекере и в чате. Других "
        "задач и проектов не заводи.\n"
        "- Вопрос и замечание — шаги человека: не отвечай на свой вопрос сам и не пиши "
        "замечание за него.\n"
        "- Сообщения в чате короткие: один шаг — одно сообщение."
    ),
    output=(
        "Собери дело в этом порядке — один пронумерованный шаг, одно действие. Ниже `key` (у "
        "`wait_journal` — `task`) везде равен `START-1`.\n\n"
        "1. `update_task` — `changes.assignee` своё имя, например `agent`.\n"
        "2. `transition` — `to: in_progress`. Отказ `assignee_mismatch`? Возьми имя из "
        "`details` отказа, повтори шаг 1 с ним, затем повтори этот шаг.\n"
        "3. В чате скажи дословно: «Открой `{board_url}/tasks/START-1` — там будет видно "
        "каждый мой шаг.»\n"
        "4. `ask` — `addressees: [{human_name}]`, `blocking: true`, `title` и `body` — какую "
        "часть своей работы человек первой отдал бы агенту.\n"
        "5. `add_summary` — `done`, `remaining`, `blockers`, `next_step`: что задал вопрос и "
        "ждёшь ответ.\n"
        "6. `transition` — `to: waiting`, `reason` называет вопрос, которого ждёшь.\n"
        '7. В чате скажи дословно: «Ответь на вопрос в разделе "Входящая" или на странице '
        'задачи. Если после этого я здесь остановился и молчу, напиши мне "Ответил".» Не '
        "заканчивай ход после этой строки: сразу шаг 8.\n"
        "8. `wait_journal` — `types: [answer]`, `after: 0`, `timeout: 60`; повторяй вызов, "
        "пока запись не придёт. Если твой клиент умеет следить в фоне, вызов можно заменить "
        'сторожем на ответ. Человек написал "Ответил"? Сделай этот шаг снова: запись уже '
        "там.\n"
        "9. `transition` — `to: in_progress`.\n"
        "10. `add_entry` — `type: artifact`, `title`, `refs: [START-1#<номер ответа>]`, "
        "`body` — памятка ниже, с работой из ответа, его же словами, на месте единственной "
        "подстановки:\n\n"
        f"{_MEMO_TEMPLATES['ru']}\n\n"
        "11. `add_summary` — `done`, `remaining`, `blockers`, `next_step`: что памятка "
        "подшита и ждёшь замечание.\n"
        "12. `transition` — `to: waiting`, `reason` называет, что ждёшь замечание.\n"
        '13. В чате скажи дословно: «Оставь любое замечание к задаче формой "Оставить '
        'замечание" на её странице. Если после этого я здесь остановился и молчу, напиши мне '
        '"Оставил замечание".» Не заканчивай ход после этой строки: сразу шаг 14.\n'
        "14. `wait_journal` — `types: [remark]`, `after: 0`, `timeout: 60`; повторяй вызов, "
        "пока запись не придёт. Если твой клиент умеет следить в фоне, вызов можно заменить "
        'сторожем на замечание. Человек написал "Оставил замечание"? Сделай этот шаг снова: '
        "запись уже там.\n"
        "15. `transition` — `to: in_progress`.\n"
        "16. `add_entry` — `type: artifact`, `title`, `refs: [START-1#<номер памятки>]`, "
        "`body` — та же памятка, изменено только то, о чём просило замечание; обе строки "
        "ходов — дословно.\n"
        "17. `resolve` — `remark_no` замечания, `outcome: fixed`, что изменилось — в `body`.\n"
        "18. `close_task` — `verdicts` по каждой проверке и закрывающий `summary`.\n"
        "19. В чате скажи дословно: «Знакомство пройдено: проект START можно отправить в "
        "архив с его страницы, а настоящая работа начинается с двух ходов из памятки.»"
    ),
    checks=(
        "В деле есть вопрос участнику-человеку и его `answer`.",
        "И `answer`, и `remark` поданы, пока задача стояла в `waiting` с причиной, и после "
        "каждого — возврат в `in_progress`.",
        "У `remark` есть исход через `resolve`; до него подшит исправленный `artifact` с памяткой.",
        "После ответа подшит `artifact` с памяткой, и его `refs` называют запись ответа.",
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


def render_tutorial_project(
    language: TutorialLanguage, *, board_url: str, human_name: str
) -> TutorialProject:
    """Собирает тексты проекта `START` для одного языка, подставив окружение.

    `context` и `output` задач несут `{board_url}` и `{human_name}` буквально; эта функция
    подставляет в них значения текущей установки строковой заменой — просто и без риска
    столкнуться с другими фигурными скобками в тексте (именами аргументов инструментов вроде
    `changes={{"assignee": ...}}`). Сам засев (`TRK-370`) вызывает её со своими значениями;
    здесь других полей не заполняют — заголовок, описание, `goal`, `constraints` и `checks`
    подстановок не несут.
    """

    def fill(text: str) -> str:
        return text.replace("{board_url}", board_url).replace("{human_name}", human_name)

    project = TUTORIAL_PROJECTS[language]
    return TutorialProject(
        title=project.title,
        description=project.description,
        tasks=tuple(
            TutorialTask(
                title=task.title,
                description=task.description,
                goal=task.goal,
                context=fill(task.context),
                constraints=task.constraints,
                output=fill(task.output),
                checks=task.checks,
            )
            for task in project.tasks
        ),
    )
