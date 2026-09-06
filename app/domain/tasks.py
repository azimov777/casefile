"""Задача: статусы, таблица переходов, проверки перехода, поля и их правила.

Чистый Python: ни ORM, ни HTTP. Всё, что здесь описано, одинаково верно для REST, MCP и
командной строки, поэтому проверки живут тут, а не в схемах запросов: MCP идёт мимо
FastAPI, и правило, записанное только в схеме, для него не существует.

## Статусы и переходы зашиты

Справочника статусов в базе нет и не будет (`CONCEPT.md`, 2 и 3.3): процесс не
настраивается, дисциплину задаёт скил. Поэтому статусы, порядок цепочки и таблица
переходов — перечисление и константы, а не строки таблицы. Расширение — правка кода и
концепции, а не задачи.

## Проверки перехода — список, а не таблица

Переход проверяется в два шага: сначала таблица (`TRANSITIONS`), потом список
независимых проверок (`TRANSITION_CHECKS`). Каждая проверка — функция от фактов о
переходе (`TransitionFacts`) и ничего не знает о соседях. Следующие задачи добавляют
свои проверки сюда, **не трогая таблицу**. Как именно — см. комментарий у
`TRANSITION_CHECKS`.

## Правки полей зависят от статуса

Название, описание и пять разделов меняются только в `backlog`; исполнитель, теги и
приоритет — в любом незакрытом статусе; в `done` и `cancelled` не меняется ничего.
Правило выражено одной функцией (`editable_fields`), чтобы частичное обновление и
инструмент MCP спрашивали её, а не держали по своей копии таблицы.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.errors import (
    ChecksNotPassedError,
    InvalidQueueKeyError,
    InvalidTaskKeyError,
    SummaryRequiredError,
    TaskBlockedError,
    TaskFieldsInvalidError,
    TaskHasUnclosedChildrenError,
    TaskSectionsIncompleteError,
    TransitionNotAllowedError,
    TransitionReasonRequiredError,
)
from app.domain.fields import FieldProblem, FieldProblems
from app.domain.queues import MAX_QUEUE_KEY_LENGTH, validate_queue_key

# --- Ключ задачи ----------------------------------------------------------------

#: Разделитель ключа задачи. В ключе очереди его быть не может — см. шаблон очередей.
TASK_KEY_SEPARATOR = "-"

#: Номер первой задачи в очереди. Счётчик хранит номер последней выданной, поэтому
#: пустая очередь держит 0, а первая задача получает 1.
FIRST_TASK_NUMBER = 1

#: Предел длины ключа задачи: ключ очереди, разделитель и номер. Номер — целое до 19
#: цифр, и в такой ключ не упрётся ни одна реальная очередь. Нужен только затем, чтобы
#: у колонки была явная граница, а не `TEXT` без предела.
MAX_TASK_KEY_LENGTH = MAX_QUEUE_KEY_LENGTH + len(TASK_KEY_SEPARATOR) + 19


def format_task_key(queue_key: str, number: int) -> str:
    """Собирает ключ задачи: `TRK` + `42` → `TRK-42`."""
    return f"{queue_key}{TASK_KEY_SEPARATOR}{number}"


def parse_task_key(key: str) -> tuple[str, int]:
    """Разбирает ключ задачи: `trk-42` → `("TRK", 42)`.

    Обратная к `format_task_key` и живёт рядом с ней намеренно: разделитель один, и
    второй разбор по своей константе однажды разъехался бы с форматированием.

    Адресация мягкая по регистру (`trk-42` находит `TRK-42`), но строгая по форме:
    `TRK-0`, `TRK-1-2` и `TRK-007` — не ключи задач, и молча истолковать их нельзя —
    ключ приезжает в ссылках записей дела и в строке поиска.
    """
    queue_part, separator, number_part = key.strip().partition(TASK_KEY_SEPARATOR)
    if not separator or not is_plain_number(number_part):
        raise InvalidTaskKeyError(
            details={
                "key": key,
                "reason": "pattern_mismatch",
                "expected": f"<QUEUE>{TASK_KEY_SEPARATOR}<number>",
            },
        )
    number = int(number_part)
    if number < FIRST_TASK_NUMBER:
        raise InvalidTaskKeyError(
            details={"key": key, "reason": "number_out_of_range", "min": FIRST_TASK_NUMBER},
        )
    try:
        queue_key = validate_queue_key(queue_part)
    except InvalidQueueKeyError as exc:
        # Клиент адресовал задачу, а не очередь: ответ должен говорить про ключ задачи,
        # а шаблон очереди приезжает в подробностях, чтобы было понятно, что не так.
        raise InvalidTaskKeyError(
            details={"key": key, "reason": "queue_key_mismatch", **exc.details},
        ) from exc
    return queue_key, number


def normalize_task_key(key: str) -> str:
    """Канонический вид ключа: очередь в верхнем регистре, номер без ведущих нулей."""
    return format_task_key(*parse_task_key(key))


def is_plain_number(part: str) -> bool:
    """Номер — десятичные цифры ASCII без ведущих нулей.

    `isdigit()` в одиночку не годится: он пропускает индийско-арабские цифры и
    надстрочные знаки. Ведущие нули отсекаются отдельно — иначе `TRK-007` и `TRK-7`
    указывали бы на одну задачу двумя способами.

    Публичная, потому что тем же правилом разбирается номер записи в ссылке
    `TRK-42#12` (`app/domain/case.py`): два разбора номера разъехались бы на первом же
    `TRK-42#007`.
    """
    return part.isascii() and part.isdigit() and part.lstrip("0") == part


# --- Статусы ------------------------------------------------------------------------


class TaskStatus(StrEnum):
    """Зашитый список статусов (`CONCEPT.md`, 3.3)."""

    BACKLOG = "backlog"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


#: Новая задача рождается только здесь; статус при создании не принимается.
INITIAL_STATUS = TaskStatus.BACKLOG

#: Порядок цепочки: `backlog` < `open` < `in_progress` < `done`. Переход к меньшему
#: статусу — шаг назад. `cancelled` в цепочке не стоит: это выход из неё.
STATUS_CHAIN: tuple[TaskStatus, ...] = (
    TaskStatus.BACKLOG,
    TaskStatus.OPEN,
    TaskStatus.IN_PROGRESS,
    TaskStatus.DONE,
)
_CHAIN_RANK = {status: rank for rank, status in enumerate(STATUS_CHAIN)}

#: Конечные статусы: из них нет переходов, а поля и связи задачи не меняются. Записи в
#: дело подшивать можно — это правило дела, а не задачи.
CLOSED_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})

#: Таблица переходов. Порядок целей в каждой строке — порядок в ответе «доступные
#: переходы»: сначала вперёд по цепочке, потом назад, потом отмена.
TRANSITIONS: Mapping[TaskStatus, tuple[TaskStatus, ...]] = {
    TaskStatus.BACKLOG: (TaskStatus.OPEN, TaskStatus.CANCELLED),
    TaskStatus.OPEN: (TaskStatus.IN_PROGRESS, TaskStatus.BACKLOG, TaskStatus.CANCELLED),
    TaskStatus.IN_PROGRESS: (
        TaskStatus.DONE,
        TaskStatus.OPEN,
        TaskStatus.BACKLOG,
        TaskStatus.CANCELLED,
    ),
    TaskStatus.DONE: (),
    TaskStatus.CANCELLED: (),
}


def allowed_transitions(status: TaskStatus) -> tuple[TaskStatus, ...]:
    """Куда можно перейти по таблице. Валидации переходов здесь не учитываются.

    Учитывать их значило бы считать сводки, вердикты и блокеры при каждом чтении
    карточки — а ответ всё равно устарел бы к моменту перехода. Таблица же не меняется
    никогда, и агент по ней понимает, какой ход вообще существует.
    """
    return TRANSITIONS[status]


def is_step_back(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """Шаг назад — переход к меньшему статусу цепочки. `cancelled` шагом назад не считается."""
    if from_status not in _CHAIN_RANK or to_status not in _CHAIN_RANK:
        return False
    return _CHAIN_RANK[to_status] < _CHAIN_RANK[from_status]


def is_closed(status: TaskStatus) -> bool:
    return status in CLOSED_STATUSES


# --- Приоритет ----------------------------------------------------------------------


class TaskPriority(StrEnum):
    """Приоритет. Порядок членов — от низшего к высшему, на него опирается сортировка поиска."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


DEFAULT_PRIORITY = TaskPriority.NORMAL


# --- Поля и кто их меняет -----------------------------------------------------------


class TaskField(StrEnum):
    """Поле задачи в записи об изменении и в правилах редактирования.

    Значения совпадают с именами полей в API: по ним строится `details.fields` ошибки и
    `payload.field` записи `section_changed`, и читающий видит то же имя, что в схеме.
    """

    TITLE = "title"
    DESCRIPTION = "description"
    GOAL = "goal"
    CONTEXT = "context"
    CONSTRAINTS = "constraints"
    OUTPUT = "output"
    CHECKS = "checks"
    STATUS = "status"
    ASSIGNEE = "assignee"
    TAGS = "tags"
    PRIORITY = "priority"


#: Четыре текстовых раздела; пятый — `checks` — устроен иначе (список), поэтому отдельно.
TEXT_SECTIONS: tuple[TaskField, ...] = (
    TaskField.GOAL,
    TaskField.CONTEXT,
    TaskField.CONSTRAINTS,
    TaskField.OUTPUT,
)

#: Пять разделов вместе с названием и описанием: то, что определяет задачу и
#: **редактируется только в `backlog`**. От `open` и дальше неизменяемы — чтобы
#: поправить, задача возвращается в `backlog` с причиной.
BACKLOG_ONLY_FIELDS: frozenset[TaskField] = frozenset(
    {TaskField.TITLE, TaskField.DESCRIPTION, *TEXT_SECTIONS, TaskField.CHECKS}
)

#: Меняются в любом незакрытом статусе: это не содержание задачи, а её обвязка.
OPEN_FIELDS: frozenset[TaskField] = frozenset(
    {TaskField.ASSIGNEE, TaskField.TAGS, TaskField.PRIORITY}
)


def editable_fields(status: TaskStatus) -> frozenset[TaskField]:
    """Какие поля можно править в этом статусе. Статус меняется только переходом."""
    if is_closed(status):
        return frozenset()
    if status is TaskStatus.BACKLOG:
        return BACKLOG_ONLY_FIELDS | OPEN_FIELDS
    return OPEN_FIELDS


# --- Форма значений полей -----------------------------------------------------------

#: Название — одна строка: оно показывается в списках и в описи, где перевод строки
#: испортит вёрстку.
MAX_TITLE_LENGTH = 255

#: Потолок описания и каждого текстового раздела. Ограничение неочевидное, поэтому
#: названо прямо: разделы уезжают в каждый пакет преемника, и мегабайтный текст съел бы
#: контекст агента целиком.
MAX_TEXT_LENGTH = 65_536

#: Проверок в задаче немного по смыслу: длинный список означает, что задачу надо делить.
MAX_CHECKS = 100
MAX_CHECK_LENGTH = 2_000

#: Исполнитель — имя участника или метка, и то и другое не длиннее 64 символов.
MAX_ASSIGNEE_LENGTH = 64

#: Теги — плоские метки, а не иерархия: длинный тег означает, что нужно поле.
MAX_TAG_LENGTH = 64
MAX_TAGS = 50


def normalize_fields(values: Mapping[TaskField, Any]) -> dict[TaskField, Any]:
    """Проверяет переданные поля и возвращает их канонический вид.

    Замечания собираются **все сразу**, а не до первого: фронт подсвечивает всю форму
    за один ответ, а агент исправляет запрос за одну попытку, а не за пять кругов
    «исправил одно — вылезло другое». Причины — стабильные строки `snake_case`:
    `required`, `multiline_not_allowed`, `too_long`, `too_many`, `empty_item`,
    `not_allowed`, `not_a_string`.

    Проверяются только переданные поля: и создание, и частичное обновление зовут эту
    функцию со своим набором, и второй валидатор «только для PATCH» разошёлся бы с
    первым на первом же правиле.
    """
    normalized: dict[TaskField, Any] = {}
    problems = FieldProblems()
    for field, value in values.items():
        with problems.field(field.value):
            normalized[field] = _NORMALIZERS[field](value)
    problems.raise_as(TaskFieldsInvalidError)
    return normalized


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise FieldProblem("not_a_string")
    return value


def _normalize_title(value: Any) -> str:
    title = _text(value).strip()
    if not title:
        raise FieldProblem("required")
    if "\n" in title or "\r" in title:
        raise FieldProblem("multiline_not_allowed")
    if len(title) > MAX_TITLE_LENGTH:
        raise FieldProblem("too_long", max=MAX_TITLE_LENGTH, got=len(title))
    return title


def _normalize_description(value: Any) -> str:
    """Описание обязательно: задача без него нечитаема, а придумать его за автора нечем."""
    description = _normalize_section(value)
    if not description:
        raise FieldProblem("required")
    return description


def _normalize_section(value: Any) -> str:
    """Раздел может быть пустым: в `backlog` задачу дописывают по частям."""
    section = _text(value)
    if len(section) > MAX_TEXT_LENGTH:
        raise FieldProblem("too_long", max=MAX_TEXT_LENGTH, got=len(section))
    return section.strip()


def _normalize_checks(value: Any) -> list[str]:
    """Проверки — упорядоченный список; нумерация с 1 по позиции.

    Пустая проверка отвергается, а не выбрасывается молча, как пустой тег: номера
    проверок — это адреса, на них ссылаются вердикты, и молчаливое схлопывание списка
    сдвинуло бы их так, что вердикт указал бы не на ту проверку.
    """
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise FieldProblem("not_a_list")
    checks: list[str] = []
    for position, item in enumerate(value, start=FIRST_CHECK_NUMBER):
        if not isinstance(item, str):
            raise FieldProblem("not_a_string", check_no=position)
        check = item.strip()
        if not check:
            raise FieldProblem("empty_item", check_no=position)
        if len(check) > MAX_CHECK_LENGTH:
            raise FieldProblem("too_long", check_no=position, max=MAX_CHECK_LENGTH, got=len(check))
        checks.append(check)
    if len(checks) > MAX_CHECKS:
        raise FieldProblem("too_many", max=MAX_CHECKS, got=len(checks))
    return checks


#: Нумерация проверок в задаче начинается с 1: `check_no` вердикта ссылается на неё.
FIRST_CHECK_NUMBER = 1


def _normalize_assignee(value: Any) -> str | None:
    """Свободная строка: имя участника или метка. Трекер её не проверяет по реестру.

    `None` — «исполнителя нет». Пустая строка отвергается: у поля есть явный способ
    очистки, и второй способ разъехался бы с первым у клиентов.
    """
    if value is None:
        return None
    assignee = _text(value).strip()
    if not assignee:
        raise FieldProblem("required", allowed_null=True)
    if "\n" in assignee or "\r" in assignee:
        raise FieldProblem("multiline_not_allowed")
    if len(assignee) > MAX_ASSIGNEE_LENGTH:
        raise FieldProblem("too_long", max=MAX_ASSIGNEE_LENGTH, got=len(assignee))
    return assignee


def _normalize_tags(value: Any) -> list[str]:
    """Приводит набор тегов к каноническому виду, сохраняя порядок.

    Повторы отбрасываются без учёта регистра, а сам регистр сохраняется: тег —
    пользовательские данные, и «Релиз» не должен превращаться в «релиз». Первое
    написание побеждает. Пустой тег выбрасывается молча (это опечатка вида `["a", ""]`),
    а слишком длинный или многострочный отвергается: молча обрезать значение, которое
    потом станет фильтром, нельзя.
    """
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise FieldProblem("not_a_list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise FieldProblem("not_a_string", tag=item)
        tag = item.strip()
        if not tag:
            continue
        if "\n" in tag or "\r" in tag:
            raise FieldProblem("multiline_not_allowed", tag=tag)
        if len(tag) > MAX_TAG_LENGTH:
            raise FieldProblem("too_long", tag=tag, max=MAX_TAG_LENGTH, got=len(tag))
        folded = tag.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(tag)
    if len(normalized) > MAX_TAGS:
        raise FieldProblem("too_many", max=MAX_TAGS, got=len(normalized))
    return normalized


def _normalize_priority(value: Any) -> TaskPriority:
    """Строка из MCP и член перечисления из REST приводятся к одному значению."""
    try:
        return TaskPriority(value)
    except ValueError:
        raise FieldProblem(
            "not_allowed", allowed=[priority.value for priority in TaskPriority]
        ) from None


_NORMALIZERS: dict[TaskField, Callable[[Any], Any]] = {
    TaskField.TITLE: _normalize_title,
    TaskField.DESCRIPTION: _normalize_description,
    TaskField.GOAL: _normalize_section,
    TaskField.CONTEXT: _normalize_section,
    TaskField.CONSTRAINTS: _normalize_section,
    TaskField.OUTPUT: _normalize_section,
    TaskField.CHECKS: _normalize_checks,
    TaskField.ASSIGNEE: _normalize_assignee,
    TaskField.TAGS: _normalize_tags,
    TaskField.PRIORITY: _normalize_priority,
}


# --- Переход ------------------------------------------------------------------------


class CheckGapReason(StrEnum):
    """Почему проверка не засчитана перед `done`.

    Стабильные строки: они уезжают в `details.checks` отказа `checks_not_passed`, и по
    ним читающий отличает «вердикта в этом заходе нет» от «последний вердикт провальный»
    — состояния разные, и делают по ним разное.
    """

    NO_VERDICT = "no_verdict"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CheckGap:
    """Незасчитанная проверка: её номер и причина.

    Пара, а не голый номер: отказ обязан объяснять, почему переход не прошёл, и по
    одному номеру этого не видно (`CONVENTIONS.md`, «Ошибки — только на английском»).
    """

    check_no: int
    reason: CheckGapReason

    def as_details(self) -> dict[str, Any]:
        """Вид, в котором пара уезжает в `details` ошибки."""
        return {"check_no": self.check_no, "reason": self.reason.value}


def checks_without_verdict(checks: Sequence[str]) -> list[CheckGap]:
    """Все проверки задачи как незасчитанные с причиной `no_verdict`.

    Общая для домена и сценария: так «вердиктов в этом заходе нет вообще» выглядит
    одинаково и когда факт не посчитан (проверка перехода), и когда в деле нет входа в
    `in_progress` (`app/services/case.py`, `verdict_gaps`). Две сборки одного и того же
    списка разъехались бы на первой же правке причины.
    """
    return [
        CheckGap(check_no=check_no, reason=CheckGapReason.NO_VERDICT)
        for check_no in range(FIRST_CHECK_NUMBER, FIRST_CHECK_NUMBER + len(checks))
    ]


@dataclass(frozen=True, slots=True)
class TransitionFacts:
    """Всё, что нужно проверкам перехода, собранное сценарием до вызова домена.

    Домен не ходит в базу, поэтому факты приносит `services`
    (`app/services/tasks.py`, `_transition_facts`). Проверка, которой нужен новый
    факт, добавляет сюда поле со значением по умолчанию и объясняет в комментарии, кто
    его заполняет; значение по умолчанию выбирается так, чтобы **непереданный факт не
    пропускал переход молча** — иначе забытое заполнение выглядело бы как успех.

    Факт, которому нужна база (сводка, вердикты, блокеры, дети), считается сценарием и
    только для тех пар статусов, где его смотрит хоть одна проверка.
    """

    key: str
    from_status: TaskStatus
    to_status: TaskStatus
    #: Уже нормализованная: без пробелов по краям, пустая строка превращена в `None`.
    reason: str | None
    sections: Mapping[TaskField, str]
    checks: Sequence[str]
    #: Есть ли в деле сводка, подшитая после последнего входа в `in_progress`. `False`
    #: по умолчанию — незаполненный факт запрещает выход из работы, а не разрешает его.
    has_summary_since_in_progress: bool = False
    #: Проверки без положительного вердикта **в этом заходе** — среди подшитых после
    #: последнего входа в `in_progress`, каждая с причиной. `None` — «факт не считали»:
    #: проверка истолкует это как «положительных вердиктов нет ни по одной проверке» и
    #: переход запретит. Пустой кортеж означал бы обратное — что все проверки
    #: пройдены, — поэтому значением по умолчанию он быть не может.
    checks_without_passed_verdict: Sequence[CheckGap] | None = None
    #: Ключи блокеров задачи не в `done` и не в `cancelled`. `None` — «факт не считали»,
    #: и переход в `in_progress` запрещается: назвать блокеры при этом нечем, поэтому
    #: отказ приходит с `details.reason`, а не с пустым списком, который соврал бы.
    open_blockers: Sequence[str] | None = None
    #: Ключи детей не в `done` и не в `cancelled`. `None` читается так же, как у
    #: блокеров, и по той же причине.
    unclosed_children: Sequence[str] | None = None


#: Одна проверка перехода: молчит, если всё в порядке, иначе бросает доменную ошибку со
#: своим кодом. Проверки не возвращают список замечаний общим списком намеренно: у них
#: разные HTTP-статусы (незаполненные разделы — `422`, отсутствующая сводка — `409`), и
#: клиент по каждому коду делает своё.
type TransitionCheck = Callable[[TransitionFacts], None]


def check_reason_for_step_back_or_cancel(facts: TransitionFacts) -> None:
    """Любой шаг назад и любой переход в `cancelled` требует причины.

    Причина уезжает в запись `status_changed` — это то, по чему преемник понимает,
    почему задача откатилась, не переживая ситуацию заново.
    """
    if facts.reason is not None:
        return
    if facts.to_status is TaskStatus.CANCELLED:
        rule = "cancel"
    elif is_step_back(facts.from_status, facts.to_status):
        rule = "step_back"
    else:
        return
    raise TransitionReasonRequiredError(
        details={
            "key": facts.key,
            "from": facts.from_status.value,
            "to": facts.to_status.value,
            "rule": rule,
        },
    )


def check_sections_filled_before_open(facts: TransitionFacts) -> None:
    """`backlog → open`: четыре раздела непустые, `checks` содержит хотя бы одну проверку.

    В `details.fields` перечисляются все незаполненные разделы сразу — по тому же
    правилу, что и замечания к полям: одна попытка, а не пять.
    """
    if not (facts.from_status is TaskStatus.BACKLOG and facts.to_status is TaskStatus.OPEN):
        return
    missing = [section.value for section in TEXT_SECTIONS if not facts.sections.get(section)]
    if not facts.checks:
        missing.append(TaskField.CHECKS.value)
    if missing:
        raise TaskSectionsIncompleteError(
            details={
                "key": facts.key,
                "from": facts.from_status.value,
                "to": facts.to_status.value,
                "fields": missing,
            },
        )


def check_summary_before_leaving_in_progress(facts: TransitionFacts) -> None:
    """`in_progress → *`: после последнего входа в работу в деле есть сводка.

    Правило распространяется на **все** выходы, включая `cancelled` и шаг назад в
    `open`: сводка нужна преемнику именно тогда, когда задачу бросают. Считается от
    последнего входа в `in_progress`, а не от начала дела: задача, взятая повторно,
    старой справкой не закрывается — обстановка с тех пор изменилась.

    Харнесс, умерший от исчерпания контекста, из `in_progress` не выходит, и эта
    проверка его не ловит. Она ловит вежливый уход (`CONCEPT.md`, 5.3).
    """
    if facts.from_status is not TaskStatus.IN_PROGRESS:
        return
    if facts.has_summary_since_in_progress:
        return
    raise SummaryRequiredError(
        details={
            "key": facts.key,
            "from": facts.from_status.value,
            "to": facts.to_status.value,
            "entry_type": "summary",
        },
    )


def check_verdicts_before_done(facts: TransitionFacts) -> None:
    """`in_progress → done`: по каждой проверке последний вердикт этого захода — `passed`.

    Обзорные проверки прогоняет исполнитель и подшивает вердикты, не выходя из работы
    (`CONCEPT.md`, 3.3): отдельного статуса под чужой обзор нет, а требование вердикта
    по каждой проверке осталось в полном объёме.

    Последний, а не любой: провалившаяся и переделанная проверка закрывается новым
    вердиктом, а не правкой старого — записи дела неизменяемы.

    Этого захода, а не всего дела: вердикты, подшитые до последнего входа в
    `in_progress`, относились к прошлой работе и не засчитываются. Границу считает
    сценарий (`app/services/case.py`, `verdict_gaps`) — домен получает готовый список
    пар «проверка и причина».
    """
    if not (facts.from_status is TaskStatus.IN_PROGRESS and facts.to_status is TaskStatus.DONE):
        return
    pending = facts.checks_without_passed_verdict
    if pending is None:
        # Факт не посчитан. Считаем, что положительного вердикта нет ни по одной
        # проверке: незаполненный факт обязан запрещать переход, а не пропускать его.
        pending = checks_without_verdict(facts.checks)
    pending = list(pending)
    if not pending:
        return
    raise ChecksNotPassedError(
        details={
            "key": facts.key,
            "from": facts.from_status.value,
            "to": facts.to_status.value,
            "checks": [gap.as_details() for gap in pending],
        },
    )


def check_no_open_blockers(facts: TransitionFacts) -> None:
    """`* → in_progress`: ни одной связи `blocked_by` на незакрытую задачу.

    Единственная валидация, которая читает связи. Она не «ждёт» и ничего не назначает:
    статуса ожидания в трекере нет, а блокировка — это просто отказ взять задачу в
    работу, пока блокер открыт (`CONCEPT.md`, 4.6).
    """
    if facts.to_status is not TaskStatus.IN_PROGRESS:
        return
    blockers = facts.open_blockers
    if blockers is None:
        # Факт не посчитан. Пропустить переход нельзя — незаполненный факт обязан
        # запрещать ход, а не выглядеть успехом; но и назвать блокеры нечем, а пустой
        # список в `details.blockers` соврал бы, что их нет. Поэтому отдельная причина.
        raise TaskBlockedError(
            details={
                "key": facts.key,
                "from": facts.from_status.value,
                "to": facts.to_status.value,
                "reason": "blockers_not_collected",
            },
        )
    if not blockers:
        return
    raise TaskBlockedError(
        details={
            "key": facts.key,
            "from": facts.from_status.value,
            "to": facts.to_status.value,
            "blockers": list(blockers),
        },
    )


def check_children_closed_before_done(facts: TransitionFacts) -> None:
    """`* → done`: все дети в `done` или в `cancelled`.

    `cancelled` закрывает ребёнка наравне с `done`: декомпозиция, от которой отказались,
    родителя держать не должна. Отменять детей сам трекер при этом не станет — статусы
    по связям не распространяются.
    """
    if facts.to_status is not TaskStatus.DONE:
        return
    children = facts.unclosed_children
    if children is None:
        # То же, что у блокеров: незаполненный факт запрещает ход и говорит об этом
        # прямо, а не пустым списком детей.
        raise TaskHasUnclosedChildrenError(
            details={
                "key": facts.key,
                "from": facts.from_status.value,
                "to": facts.to_status.value,
                "reason": "children_not_collected",
            },
        )
    if not children:
        return
    raise TaskHasUnclosedChildrenError(
        details={
            "key": facts.key,
            "from": facts.from_status.value,
            "to": facts.to_status.value,
            "children": list(children),
        },
    )


#: Проверки перехода в порядке выполнения. Первая упавшая останавливает переход.
#:
#: Как подключить новую: добавить факт в `TransitionFacts` со значением по умолчанию,
#: которое **запрещает** переход, заполнить его в `app/services/tasks.py`
#: (`_transition_facts`), написать функцию рядом с соседями и вписать её сюда. Таблицу
#: `TRANSITIONS` при этом не трогать — она описывает, какие ходы существуют, а не при
#: каких условиях они проходят.
TRANSITION_CHECKS: tuple[TransitionCheck, ...] = (
    check_reason_for_step_back_or_cancel,
    check_sections_filled_before_open,
    check_summary_before_leaving_in_progress,
    check_verdicts_before_done,
    check_no_open_blockers,
    check_children_closed_before_done,
)


def normalize_reason(reason: str | None) -> str | None:
    """Пробелы по краям снимаются, пустая строка становится `None`: причина либо есть, либо нет."""
    if reason is None:
        return None
    stripped = reason.strip()
    return stripped or None


def ensure_transition_allowed(facts: TransitionFacts) -> None:
    """Проверяет переход: сначала таблица, потом список проверок.

    Единственное место, где переход разрешается или отклоняется. Сценарий перевода
    статуса зовёт его и ничего не решает сам; так же поступит инструмент MCP.
    """
    allowed = TRANSITIONS[facts.from_status]
    if facts.to_status not in allowed:
        raise TransitionNotAllowedError(
            details={
                "key": facts.key,
                "from": facts.from_status.value,
                "to": facts.to_status.value,
                "allowed": [status.value for status in allowed],
            },
        )
    for check in TRANSITION_CHECKS:
        check(facts)


def parse_status(value: Any) -> TaskStatus:
    """Строка из MCP и член перечисления из REST приводятся к одному значению."""
    try:
        return TaskStatus(value)
    except ValueError:
        raise TaskFieldsInvalidError(
            details={
                "fields": [
                    {
                        "field": TaskField.STATUS.value,
                        "reason": "not_allowed",
                        "allowed": [status.value for status in TaskStatus],
                    }
                ]
            },
        ) from None


def section_values(fields: Mapping[TaskField, Any]) -> dict[TaskField, str]:
    """Четыре текстовых раздела из набора полей — в форме, которую ждёт `TransitionFacts`."""
    return {section: str(fields.get(section) or "") for section in TEXT_SECTIONS}


# --- Вычисляемые признаки -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskFeatures:
    """Признаки, которые не хранятся, а считаются из дела и связей (`CONCEPT.md`, 4.3).

    Колонок под них нет намеренно: колонка — это второе место, где живёт правда, и она
    расходится с делом ровно в тот момент, когда её забыли обновить. Цена — запрос при
    чтении карточки; она приемлема, потому что запрос один и идёт по индексу.

    Все четыре считаются из того, что пакет преемника читает и так: `blocked` — из
    связей, остальные — из открытых вопросов и последней сводки. Отдельного запроса
    ради признака в проекте нет ни одного, и заводить его не нужно.
    """

    blocked: bool
    open_questions: int
    open_blocking_questions: int
    last_summary_at: datetime | None
    #: Когда в дело последний раз подшивали запись агента или человека. Служебные
    #: записи не считаются: `link_added` подшивается в оба дела, когда связь ставят
    #: с другой стороны, и задача, которой никто не касался, выглядела бы живой.
    #: Пусто, пока агент в дело ничего не писал — у свежей задачи там только `created`.
    last_entry_at: datetime | None
