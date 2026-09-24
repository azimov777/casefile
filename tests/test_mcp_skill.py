"""Скил, который сервер раздаёт агенту: промпт и совпадение имён.

`instructions` сервера из скила больше не берутся — их стережёт
`tests/test_mcp_instructions.py` (TRK-142).

Дисциплина живёт в одном файле — `skill/tracker-agent/SKILL.md` (`CONCEPT.md`, 5.3).
Проверяется здесь не столько код, сколько то, что второй копии этого текста нет и что
скил не разошёлся с сервером по именам инструментов.

## Почему совпадение имён проверяется тестом, а не вниманием

Скил зовёт инструменты по именам прямо в тексте. Переименованный инструмент делает скил
инструкцией к несуществующему действию: агент выполнит её буквально, получит отказ
«неизвестный инструмент» и начнёт искать обход — то есть сломается не сервер, а работа.
Обратная сторона так же важна: инструмент, ни разу не названный в скиле, агент, скорее
всего, не найдёт вовсе.

## Почему по именам проверка не заканчивается

Имена — не единственное, чем описание инструмента расходится со скилом. Один и тот же
факт дисциплины записан в двух каналах: в скиле и в описании, которое приезжает агенту в
`tools/list`. Правка домена доходит до скила и не доходит до описания — и агент, до
которого скил не доехал (промпт клиент показывает по своему усмотрению, а в харнессе
скила может не быть), читает единственную инструкцию, и неверную. Так `wait_journal` звал
в `open` ожидать ответа четыре дня после того, как ожидание стало `waiting` (`TRK-31`).
"""

import re

import pytest
from mcp.server.mcpserver import MCPServer
from mcp_types import TextContent, Tool

from app.domain.tasks import TaskStatus
from app.mcp.skill import PROMPT_NAME, SKILL_PATH
from conftest import Connect

#: Идентификатор в обратных кавычках, за которым сразу идёт скобка, — это вызов
#: инструмента в тексте скила: `add_summary(key, ...)`.
TOOL_CALL_IN_SKILL = re.compile(r"`([a-z][a-z0-9_]*)\(")


@pytest.fixture
def skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """Раздел скила по заголовку второго уровня, до следующего такого заголовка.

    Разбор тот же, что у `instructions` в приложении, и такой же простой: формат файла
    задаём мы сами. Отсутствие раздела — провал теста, а не пустая строка: правило,
    которое некуда положить, из скила исчезло вместе с разделом.
    """
    _, separator, rest = text.partition(f"## {heading}\n")
    assert separator, f"в скиле не стало раздела «{heading}»"
    return rest.split("\n## ", 1)[0]


async def test_the_prompt_returns_the_whole_skill(
    mcp_session: Connect, task_secret: str, skill_text: str
) -> None:
    """Обзорная проверка 6: `prompts/get` отдаёт файл скила целиком."""
    async with mcp_session(task_secret) as session:
        listed = await session.list_prompts()
        prompt = await session.get_prompt(PROMPT_NAME)

    assert [item.name for item in listed.prompts] == [PROMPT_NAME]
    contents = [
        message.content.text
        for message in prompt.messages
        if isinstance(message.content, TextContent)
    ]
    assert contents == [skill_text]


async def test_every_tool_named_in_the_skill_exists(mcp_server: MCPServer, skill_text: str) -> None:
    """Обзорная проверка 9: скил не зовёт того, чего у сервера нет."""
    registered = {tool.name for tool in await mcp_server.list_tools()}
    called = set(TOOL_CALL_IN_SKILL.findall(skill_text))

    assert called, "в скиле не осталось ни одного вызова инструмента — выражение устарело"
    assert called <= registered, f"скил зовёт несуществующее: {sorted(called - registered)}"


async def test_every_working_cycle_tool_is_mentioned_in_the_skill(
    mcp_session: Connect, task_secret: str, skill_text: str
) -> None:
    """Обзорная проверка 9: инструмент, не названный в скиле, агент не найдёт.

    Список берётся у сервера токеном `task`, а не переписывается в тест: иначе тест
    сверял бы скил со своей же копией перечня.
    """
    async with mcp_session(task_secret) as session:
        working_cycle = {tool.name for tool in (await session.list_tools()).tools}

    missing = sorted(name for name in working_cycle if f"`{name}" not in skill_text)

    assert not missing, f"скил не упоминает: {missing}"


def test_entering_a_task_reads_what_was_filed_after_the_summary(skill_text: str) -> None:
    """Дисциплина TRK-3: сводка отстаёт от дела, и вход это учитывает.

    Пакет преемника отдаёт последнюю сводку и опись, но не говорит, что между ними
    разрыв: записи с номером больше номера сводки она не видела. Правило живёт только в
    тексте скила — валидации на это нет, — поэтому его и держит тест.
    """
    entering = section(skill_text, "Вход в задачу")

    assert "after_no" in entering, "вход перестал звать `read_entries(key, after_no=...)`"
    assert "сводк" in entering.lower()


def test_entering_a_task_reads_the_open_remarks(skill_text: str) -> None:
    """Дисциплина TRK-9: замечание не пропускают на входе.

    Трекер отдаёт неразобранные замечания в пакете, но прочитать их — обязанность агента,
    и потребовать этого он не может: чтение он не проверяет. Правило живёт только в
    тексте скила, поэтому его держит тест.
    """
    entering = section(skill_text, "Вход в задачу")

    assert "замечани" in entering.lower(), "вход перестал называть замечания среди читаемого"


def test_closing_names_the_outcome_of_every_remark(skill_text: str) -> None:
    """Дисциплина TRK-9: уйти в `done`, не ответив на «вышло не то», нельзя.

    Валидации на это нет и не будет: замечание не обзорная проверка, и «разобрано»
    означает «агент ответил», а не «трекер убедился». Единственное место, где обязанность
    закреплена, — раздел «Завершение».
    """
    closing = section(skill_text, "Завершение")

    assert "resolve" in closing, "завершение не требует исхода по замечаниям"
    assert closing.index("resolve") < closing.index("close_task"), (
        "резолюции обязаны идти до закрытия: иначе сводка закрытия не знает их исхода"
    )


def test_the_skill_promises_no_delivery(skill_text: str) -> None:
    """Дисциплина TRK-9: трекер никого не уведомляет и ничего не запускает.

    Обещание доставки — самая дорогая ошибка в тексте: агент, поверивший, что замечание
    до кого-то «дойдёт», перестаёт читать его сам.
    """
    lowered = skill_text.lower()

    assert "уведом" not in lowered, "скил заговорил про уведомления, которых в трекере нет"
    assert "не следит, жив ли ты" in lowered or "ничего не делает сам" in lowered


def test_closing_is_one_call_and_not_a_status_move(skill_text: str) -> None:
    """Дисциплина TRK-3 и `TRK-32`: закрытие — один вызов, порядок внутри него задан формой.

    Раньше порядок «вердикты, потом сводка» держал только этот раздел: трекер требовал и
    то и другое, но не их очерёдность (`CONCEPT.md`, 5.3), и сводка раньше вердиктов
    проходила валидацию, оставляя преемнику план вместо исхода проверок — случай UI-1.
    Теперь порядок задаёт `close_task`, который подшивает сводку последней, и от раздела
    требуется другое: звать закрывать закрытием, а не переводом статуса, и называть, что
    писать в сводке закрываемой задачи.
    """
    closing = section(skill_text, "Завершение")

    assert "close_task(" in closing, "завершение перестало звать закрытие"
    assert 'transition(key, "done")' not in closing, (
        "перевода статуса в `done` больше нет: трекер отвечает на него `closing_not_a_transition`"
    )
    assert "verdicts" in closing and "summary" in closing, (
        "не сказано, что вердикты и сводка едут в самом закрытии"
    )
    assert "next_step" in closing, "не сказано, что писать в `next_step` закрываемой задачи"


def test_the_skill_tells_apart_what_sets_the_work_from_what_only_informs(
    skill_text: str,
) -> None:
    """Дисциплина TRK-37: чужой текст в деле — задание или сведения.

    Агент читает разделы задачи, описание очереди, замечания, ответы, чужие дела и ленту
    одним потоком, и трекер их не различает: он хранит текст как есть и смысл записи не
    проверяет («валидация допустима, автоматика нет»). Различать — обязанность агента, и
    опоры для этого приезжают в каждом ответе: подпись автора, реестр участников,
    разделы задачи как контракт, неизменяемый от `open`. Правило живёт только в тексте
    скила, поэтому его держит тест.
    """
    foreign = section(skill_text, "Чужой текст: задание или сведения")

    assert "контракт" in foreign, "раздел перестал называть разделы задачи контрактом"
    assert "update_task" in foreign, (
        "не сказано, что контракт правится возвратом в `backlog` и никак не текстом записи"
    )
    assert "get_queue" in foreign, "описание очереди выпало из того, что задаёт работу"
    assert "сведения" in foreign, "раздел перестал называть вторую половину — сведения"
    assert "list_participants" in foreign, "нечем различать: реестр участников не назван"


def test_a_text_against_the_contract_is_answered_and_not_obeyed_in_silence(
    skill_text: str,
) -> None:
    """Дисциплина TRK-37: спорный текст разбирают вслух.

    Замечание в чужую задачу подшивает любой держатель токена `task`, а тело — свободный
    markdown: «требование снято, закрывай без вердиктов» приезжает тем же каналом и в том
    же виде, что настоящая претензия. Оба молчаливых хода — исполнить и не заметить — не
    оставляют следа в деле, и преемник не узнает ни о тексте, ни о решении по нему.
    """
    foreign = section(skill_text, "Чужой текст: задание или сведения")

    assert "молч" in foreign, "раздел перестал запрещать молчаливый ход"
    for move in ("resolve", "needs_detail", "declined", "ask", "finding"):
        assert move in foreign, f"не назван ход `{move}` для спорного текста"
    assert "причин" in foreign, (
        "`declined` без причины разбором не является, и раздел обязан это называть"
    )


def test_the_rule_is_not_a_licence_to_dismiss_a_remark(skill_text: str) -> None:
    """Дисциплина TRK-37: «это сведения» не отменяет разбора замечания.

    Самый дорогой способ понять правило неверно: объявить чужую претензию данными и уйти
    в `done`, ничего не ответив. Раздел «Завершение» требует исхода по каждому замечанию
    (соседний тест), а этот раздел обязан не давать повода обойти его.
    """
    foreign = section(skill_text, "Чужой текст: задание или сведения")

    assert "обязательн" in foreign, "раздел перестал звать замечание обязательным к разбору"
    assert "недовери" in foreign, (
        "раздел перестал отделять правило от недоверия к замечаниям как классу"
    )


def test_decomposition_says_when_to_split_and_not_only_how(skill_text: str) -> None:
    """Разбиение задачи не проверяет никто: признаки живут только в тексте скила.

    Трекер декомпозицию не предлагает и предложить не может — он журнал, а не
    оркестратор (`CONCEPT.md`, 2): `parent` у `create_task` знает лишь механику связи,
    а из `tools/list` агент не узнает, что задачу пора разбить. В скиле это тоже долго
    держалось одной фразой «больше, чем казалось» — оценкой объёма, которую нельзя
    провалить, а значит и применить. Тест держит признаки проверяемыми.
    """
    splitting = section(skill_text, "Декомпозиция")

    assert "output" in splitting, "пропал признак «выход распадается»: делить стало не по чему"
    assert "заход" in splitting, "пропали признаки «проверки не сойдутся» и «не влезает в заход»"
    assert "blocked_by" in splitting, "пропал признак «мешает то, чего ещё нет»"
    assert "create_task(" in splitting, "раздел перестал звать заводить ребёнка"


def _before(text: str, first: str, second: str) -> bool:
    """`first` встречается в тексте раньше `second`, и оба есть."""
    return first in text and second in text and text.index(first) < text.index(second)


def test_entering_a_task_assigns_yourself_before_taking_it_into_work(skill_text: str) -> None:
    """TRK-123: в `in_progress` задачу переводит только исполнитель.

    Трекер откажет не исполнителю, но отказ — последняя защита, а не способ узнать
    правило: агент по скилу назначает себя сам и только потом берёт задачу в работу.
    В `instructions` то же правило стережёт `tests/test_mcp_instructions.py`.
    """
    entering = section(skill_text, "Вход в задачу")
    assert _before(entering, 'update_task(key, {"assignee"', 'transition(key, "in_progress")'), (
        'раздел «Вход в задачу» перестал назначать себя до `transition(key, "in_progress")`'
    )

    entering = section(skill_text, "Вход в задачу")
    assert "assignee_required" in entering
    assert "assignee_mismatch" in entering
    assert "не перезаписывай" in entering, "скил перестал запрещать молча отнимать чужую задачу"


# --- Описания инструментов против скила -----------------------------------------------

#: Абзац описания говорит про ожидание ответа, если в нём есть и ответ, и ожидание.
#: Двух признаков сразу, а не одного: «ответ» без ожидания — это форма результата вызова,
#: а ожидание без ответа — другая задача или событие вне трекера, и ход там свой
#: (`CONCEPT.md`, 4.6).
ABOUT_AN_ANSWER = re.compile("ответ", re.IGNORECASE)
ABOUT_WAITING = re.compile("жд|ожид", re.IGNORECASE)

#: Ход дисциплины, как он записан в скиле: `transition(key, "waiting", reason=...)`.
#: Перенос строки между аргументами законен — файл свёрстан по ширине.
TRANSITION_IN_SKILL = re.compile(r'transition\(\s*key,\s*"([a-z_]+)"')


def statuses_named(text: str) -> set[str]:
    """Статусы, названные в тексте.

    Границы обязательны: без них `open` находился бы внутри `open_remarks`, и абзац про
    признаки карточки читался бы как совет уйти в очередь.
    """
    return {
        status.value
        for status in TaskStatus
        if re.search(rf"(?<![a-z_]){status.value}(?![a-z_])", text, re.IGNORECASE)
    }


def paragraphs(text: str) -> list[str]:
    """Абзацы текста: ими свёрстано описание инструмента, описание аргумента — один абзац.

    Абзац, а не предложение: ход дисциплины редко умещается в одно. «Годится, когда ответ
    ожидается скоро» и «если нет — уходи туда-то» стоят рядом, и разрезанные по точке они
    перестают быть разговором про ожидание ответа — то есть проверка молча перестала бы
    смотреть ровно туда, ради чего написана.
    """
    return [block for block in re.split(r"\n\s*\n", text) if block.strip()]


def model_reads(tool: Tool) -> list[tuple[str, str]]:
    """Всё, что модель читает у инструмента: его описание и описания его аргументов.

    Аргументы наравне с описанием: они приезжают тем же `tools/list`, и `BlockingArg`
    показывает, что расходится с доменом там ничуть не реже.
    """
    texts = [(tool.name, tool.description or "")]
    for name, schema in (tool.input_schema.get("properties") or {}).items():
        texts.append((f"{tool.name}.{name}", schema.get("description") or ""))
    return texts


@pytest.fixture
def waiting_status(skill_text: str) -> str:
    """Статус ожидания ответа — тот, который называет раздел «Вопросы» скила.

    Берётся из скила, а не пишется здесь константой: тест сверяет два текста, и своя
    копия ответа превратила бы его в сверку теста с самим собой.
    """
    named = set(TRANSITION_IN_SKILL.findall(section(skill_text, "Вопросы")))

    assert len(named) == 1, f"раздел «Вопросы» называет ходов не один: {sorted(named)}"
    status = named.pop()
    assert status in set(TaskStatus), f"раздел «Вопросы» зовёт в `{status}` — такого статуса нет"
    return status


async def test_no_tool_description_names_another_status_for_waiting_for_an_answer(
    mcp_session: Connect, main_secret: str, waiting_status: str
) -> None:
    """Дисциплина TRK-31: описание не зовёт ожидать ответа не там, где скил.

    Скил здесь главный, а описание производное: `waiting` — решение владельца
    (`CONCEPT.md`, 3.3), и расходится с ним всегда описание. Поэтому статус берётся из
    скила, а описания сверяются с ним, а не наоборот.

    Проверка отрицательная намеренно. Она не требует, чтобы ход дисциплины в описаниях
    вообще был: где живёт текст дисциплины, решает не этот тест (`TRK-33`). Она требует
    ровно одного — чтобы названный в описании статус ожидания совпадал со скилом.

    Список берётся токеном `main`: описание читает каждый, кому инструмент виден, и
    расхождение прячется в наборе `main` не хуже, чем в рабочем цикле.
    """
    async with mcp_session(main_secret) as session:
        listed = (await session.list_tools()).tools

    assert listed, "список инструментов пуст: проверять нечего"

    diverged: list[str] = []
    for tool in listed:
        for where, text in model_reads(tool):
            for paragraph in paragraphs(text):
                if not (ABOUT_AN_ANSWER.search(paragraph) and ABOUT_WAITING.search(paragraph)):
                    continue
                wrong = statuses_named(paragraph) - {waiting_status}
                if wrong:
                    said = " ".join(paragraph.split())
                    diverged.append(f"{where}: {sorted(wrong)} вместо `{waiting_status}` — {said}")

    assert not diverged, "описание зовёт ожидать ответа не там, где скил:\n" + "\n".join(diverged)


# --- Дисциплина в скиле, контракт в описании -------------------------------------------

#: Слова, которыми текст называет агенту **ход**: повелительное наклонение — обращение к
#: нему, наречия порядка — последовательность из нескольких вызовов. И то и другое по
#: решению владельца (`TRK-33`, `CONCEPT.md`, 5.2) живёт в скиле, а описание инструмента
#: остаётся контрактом одного вызова: что делает, что меняется снаружи, что вернёт, когда
#: откажет.
#:
#: Список закрытый, и это осознанно. Разбор морфологии здесь дал бы шум: существительных,
#: кончающихся как повелительное наклонение, в описаниях полно (`записи`, `связи`,
#: `ключи`). Дубли, снятые по `TRK-33`, ловятся все до одного: восемь описаний содержали
#: либо повелительное наклонение, либо «сначала … потом …».
#:
#: Чего список не ловит: безличный совет («так ждут ответа, не отпуская задачу»). Он тоже
#: дисциплина, но грамматического следа не оставляет, и это остаётся на вычитке — как и
#: обещание чужого поведения (`docs/notes/mcp.md`).
NEXT_MOVE_WORDS = (
    "адресуй",
    "бери",
    "возьми",
    "выбери",
    "выполни",
    "дождись",
    "жди",
    "заведи",
    "заполни",
    "затем",
    "начни",
    "напиши",
    "отвечай",
    "ответь",
    "передавай",
    "переведи",
    "пиши",
    "подшей",
    "положи",
    "после чего",
    "потом",
    "прежде чем",
    "приходи",
    "прочитай",
    "проси",
    "правь",
    "продолжай",
    "сначала",
    "смотри",
    "собери",
    "создай",
    "спроси",
    "ссылайся",
    "ставь",
    "укажи",
    "уходи",
    "читай",
)

#: Границы слова обязательны: без них `бери` находилось бы внутри «выбери», `правь` —
#: внутри «поправь». `\b` в Python по умолчанию юникодный, и кириллица ему слово.
NEXT_MOVE = re.compile(r"\b(" + "|".join(NEXT_MOVE_WORDS) + r")\b", re.IGNORECASE)

#: Инструменты, чьё действие **и есть** подшитая запись. Для них вторичный эффект —
#: половина контракта: запись уходит в общий журнал (`CONCEPT.md`, 4.1), будит ждущих
#: `wait_journal` через `LISTEN/NOTIFY` (`app/db/wakeup.py`) и немедленно видна человеку
#: в интерфейсе. Остальные подшивают запись попутно и называют, какую именно.
#:
#: `close_task` здесь же, хотя он ещё и переводит статус: записей он подшивает больше
#: всех сразу, и агент, не знающий, что они в ту же секунду стоят у человека на экране,
#: пишет закрытие в стол.
FILING_TOOLS = (
    "add_entry",
    "add_summary",
    "ask",
    "answer",
    "resolve",
    "add_verdict",
    "close_task",
)


async def test_no_tool_description_tells_the_agent_what_to_do_next(
    mcp_session: Connect, main_secret: str
) -> None:
    """`TRK-33`: описание — контракт вызова, а ходы агента живут в скиле.

    Один и тот же факт дисциплины стоял и в скиле, и в описании: восемь описаний
    пересказывали разделы скила, местами дословно. Расходятся такие пары молча и в одну
    сторону — скил правят, описание нет, — а прочитает разошедшееся описание ровно тот
    агент, у которого скила нет (`TRK-31`).

    Проверка грамматическая, потому что граница грамматическая: описание **описывает**
    вызов, а дисциплина **предписывает** ход. Повелительное наклонение и «сначала …
    потом …» — след предписания, и другого способа отличить один текст от другого без
    чтения глазами нет.

    Список берётся токеном `main`: описание читает каждый, кому инструмент виден.
    """
    async with mcp_session(main_secret) as session:
        listed = (await session.list_tools()).tools

    assert listed, "список инструментов пуст: проверять нечего"

    prescribing: list[str] = []
    for tool in listed:
        for where, text in model_reads(tool):
            for found in NEXT_MOVE.finditer(text):
                said = " ".join(text[max(0, found.start() - 60) : found.end() + 60].split())
                prescribing.append(f"{where}: «{found.group(0)}» — …{said}…")

    assert not prescribing, (
        "описание называет агенту ход; ход живёт в скиле (`CONCEPT.md`, 5.2):\n"
        + "\n".join(prescribing)
    )


async def test_every_filing_tool_names_that_the_entry_is_seen_at_once(
    mcp_session: Connect, task_secret: str
) -> None:
    """`TRK-33`: вторичный эффект вызова — часть контракта, и он назван в описании.

    Подшитая запись не остаётся внутри задачи: она попадает в общий журнал, будит
    ждущих ленту и в ту же секунду стоит у человека на экране. Агент, который этого не
    знает, пишет в дело так, будто пишет в стол, — и удивляется, что замечание пришло
    через минуту после его записи.

    Скил тут ни при чём: это не ход агента, а то, что вызов делает во внешнем мире.
    Поэтому и держится не текстом скила, а описанием — и проверяется у живого сервера.
    """
    async with mcp_session(task_secret) as session:
        described = {
            tool.name: tool.description or "" for tool in (await session.list_tools()).tools
        }

    missing: list[str] = []
    for name in FILING_TOOLS:
        assert name in described, f"инструмент `{name}` пропал из рабочего цикла"
        text = described[name]
        for mark in ("лент", "wait_journal", "человек"):
            if mark not in text:
                missing.append(f"{name}: не сказано про «{mark}»")

    assert not missing, "описание не называет вторичный эффект подшивки:\n" + "\n".join(missing)
