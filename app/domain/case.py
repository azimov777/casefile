"""Дело: словарь типов записей, форма нагрузки по каждому типу и ссылки.

Дело — упорядоченный список неизменяемых записей (`CONCEPT.md`, 3.4). Здесь всё, что не
зависит от базы: типы записей, правила нагрузки, разбор ссылки `TRK-42#12`, строка
описи. Форма строки в базе описана моделью в `app/db/models/entry.py`, а проверки,
которым нужна база (существует ли адресат, есть ли такая запись), живут в
`app/services/case.py` — домен в базу не ходит.

## Словарь закрыт

Соглашения требуют держать типы записей одним перечислением и не заводить новых по
месту: новый тип записи — это изменение концепции, а не задачи. Тип служебной записи
при этом выводится из сценария в `services`, а не задаётся вызывающим кодом: два
независимых словаря имён разъехались бы, и новое действие молча осталось бы без записи.

## Заголовок либо пишут, либо выводят

Заголовок — единственное, что видно в описи, поэтому он обязателен у каждой записи. Но
у трёх типов писать его руками нечего и незачем: у `summary` он равен первой строке
`done`, у `answer` и `verdict` собирается из нагрузки. Поэтому заголовок у них
**не принимается**: принять и проигнорировать значило бы дать клиенту думать, что он
задаёт опись, а принять и использовать — развести опись с нагрузкой.

У сводки это именно `done`, а не `next_step`. Каждая строка описи отвечает на вопрос
«что случилось», и сводка не исключение: заголовок из следующего шага протухал вместе с
ним, и к закрытию задачи опись читалась списком давно исполненных распоряжений, а у
закрывающей сводки следующего шага нет вовсе. Факт стареет лучше приказа.

Заголовок при этом **хранится**, а не вычисляется при чтении: он собирается один раз,
здесь, и уезжает в `entries.title`. Поэтому сводки, подшитые до этой правки, остались с
заголовками из `next_step` — в одной описи законно соседствуют два поколения строк.
Переписать их нельзя: записи неизменяемы, и это стережёт триггер `entries_immutable`.

## Ссылка либо тракторная, либо адрес

`refs` содержит ссылки на записи (`TRK-42#12`), на задачи (`TRK-7`) и адреса. Первые
две трекер проверяет на существование, адреса не проверяет вовсе (`CONCEPT.md`, 3.4).
Различить их можно только по форме, поэтому правило простое: если строка разбирается
как ключ задачи — это ссылка внутрь трекера, иначе адрес. Ловушка здесь одна и она
закрыта: `TRK-42#абв` разбирается как ключ задачи с испорченным номером записи, и
молча считать такую строку адресом нельзя — это опечатка в ссылке, а не URL.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from app.domain.authors import Author
from app.domain.errors import EntryFieldsInvalidError, InvalidTaskKeyError
from app.domain.fields import FieldProblem, FieldProblems
from app.domain.links import LinkKind
from app.domain.tasks import (
    FIRST_CHECK_NUMBER,
    TaskField,
    TaskStatus,
    is_plain_number,
    normalize_task_key,
)


class EntryType(StrEnum):
    """Тип записи дела. Записи агента и человека — до `NOTE`, служебные — после."""

    SUMMARY = "summary"
    DECISION = "decision"
    ATTEMPT = "attempt"
    FINDING = "finding"
    ARTIFACT = "artifact"
    QUESTION = "question"
    ANSWER = "answer"
    VERDICT = "verdict"
    REMARK = "remark"
    RESOLUTION = "resolution"
    NOTE = "note"
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    SECTION_CHANGED = "section_changed"
    FIELD_CHANGED = "field_changed"
    ASSIGNEE_CHANGED = "assignee_changed"
    LINK_ADDED = "link_added"
    LINK_REMOVED = "link_removed"


class VerdictOutcome(StrEnum):
    """Исход обзорной проверки. Значений ровно два: третьего состояния у проверки нет."""

    PASSED = "passed"
    FAILED = "failed"


class RemarkOutcome(StrEnum):
    """Чем разобрано замечание (`CONCEPT.md`, 3.4).

    Список закрыт и покрывает все четыре судьбы претензии: поправили сразу, приняли в
    работу отдельной задачей, не поняли и ждём уточнения, менять не будем. Свободного
    «прочее» здесь нет намеренно — оно снова сделало бы исход текстом.
    """

    FIXED = "fixed"
    ACCEPTED = "accepted"
    NEEDS_DETAIL = "needs_detail"
    DECLINED = "declined"


#: Исход, при котором резолюция обязана назвать задачу-продолжение, — и единственный, при
#: котором поле `task` вообще принимается. «Приняли в работу» без адреса работы это
#: обещание без ссылки, а «поправлено сразу» с адресом — два способа сказать одно.
OUTCOME_WITH_CONTINUATION = RemarkOutcome.ACCEPTED


#: Записи, которые подшивает сам трекер в той же транзакции, что и изменение. Агент
#: подшить такую запись напрямую не может: `build_entry` отвергает эти типы на входе.
SERVICE_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {
        EntryType.CREATED,
        EntryType.STATUS_CHANGED,
        EntryType.SECTION_CHANGED,
        EntryType.FIELD_CHANGED,
        EntryType.ASSIGNEE_CHANGED,
        EntryType.LINK_ADDED,
        EntryType.LINK_REMOVED,
    }
)

#: Записи агента и человека — всё, что не служебное.
AGENT_ENTRY_TYPES: frozenset[EntryType] = frozenset(EntryType) - SERVICE_ENTRY_TYPES

#: Типы, у которых заголовок пишет автор. У остальных он выводится из нагрузки — см.
#: раздел «Заголовок либо пишут, либо выводят» в начале файла.
TITLED_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {
        EntryType.DECISION,
        EntryType.ATTEMPT,
        EntryType.FINDING,
        EntryType.ARTIFACT,
        EntryType.QUESTION,
        EntryType.REMARK,
        EntryType.NOTE,
    }
)

#: Номер первой записи в задаче. Сквозной `seq` выдаёт база, а `no` считается по задаче.
FIRST_ENTRY_NUMBER = 1

#: Заголовок — одна строка: это то, что видно в описи дела.
MAX_ENTRY_TITLE_LENGTH = 255

#: Потолок тела записи. Тело читается точечно, а не в каждом пакете преемника, поэтому
#: предел тот же, что у раздела задачи, — этого хватает на протокол попытки с выводом.
MAX_ENTRY_BODY_LENGTH = 65_536

#: Потолок одной части сводки. Заметно меньше тела: сводка целиком уезжает в **каждый**
#: пакет преемника, и мегабайтная справка съела бы контекст агента до того, как он
#: дошёл бы до дела.
MAX_SUMMARY_PART_LENGTH = 16_384

#: Ссылок в записи немного по смыслу: длинный список означает, что запись сшивает то,
#: что должно быть несколькими записями.
MAX_REFS = 50
MAX_REF_LENGTH = 2_000

#: Адресатов у вопроса немного: вопрос, разосланный двадцати участникам, не получит
#: ответа ни от кого.
MAX_ADDRESSEES = 20

#: Части сводки в порядке чтения: сделано, осталось, что мешает, следующий шаг.
SUMMARY_PARTS: tuple[str, ...] = ("done", "remaining", "blockers", "next_step")

#: Часть, которая есть только у закрывающей сводки: какую часть цели не измерила ни одна
#: обзорная проверка. Вердикт отвечает **проверке**, а не цели, и разница между «проверки
#: зелёные» и «цель выполнена» до сих пор жила в голове того, кто разбирал последствия:
#: UI-98 закрылась тремя зелёными вердиктами с невыполненной половиной цели, UI-107 —
#: четырьмя, сломав дев-путь `/config.json`, которого не касалась ни одна проверка. Дело
#: об этом молчало, и преемник с чистым контекстом не узнавал (TRK-78).
#:
#: У промежуточных сводок её нет намеренно: посреди работы «чего не измерили» — это весь
#: невыполненный объём, то есть `remaining` другими словами. Смысл появляется ровно в тот
#: момент, когда работа объявлена законченной.
CLOSING_SUMMARY_PART = "unmeasured"

#: Части закрывающей сводки: те же четыре и пятая. Порядок чтения сохранён — «чего не
#: измерили» идёт последним, после следующего шага, как приписка к подведённому итогу.
CLOSING_SUMMARY_PARTS: tuple[str, ...] = (*SUMMARY_PARTS, CLOSING_SUMMARY_PART)

#: Разделитель ссылки на запись: `TRK-42#12` — двенадцатая запись задачи `TRK-42`.
ENTRY_REF_SEPARATOR = "#"

#: Форма ссылки на запись в подробностях отказа: по ней агент чинит опечатку.
ENTRY_REF_SHAPE = f"<QUEUE>-<task number>{ENTRY_REF_SEPARATOR}<entry number>"

#: Чем обрезается слишком длинный выведенный заголовок. Обрезка, а не отказ: у сводки
#: заголовок берётся из текста автора, и отклонять справку из-за длинной первой строки
#: `done` значило бы терять её содержимое ради описи.
TITLE_ELLIPSIS = "…"

#: Что снимается с хвоста обрезанного заголовка перед многоточием: разделители, после
#: которых «…» читалось бы как оборванная фраза («слово,…» вместо «слово…»).
TITLE_CUT_TRAILING = " ,;:.-—"


def format_entry_ref(task_key: str, no: int) -> str:
    """Ссылка на запись: ключ задачи и номер записи в ней."""
    return f"{task_key}{ENTRY_REF_SEPARATOR}{no}"


# --- Факты записи ---------------------------------------------------------------------
#
# Факты — то, чем запись называют строкой, не читая тела: значения перечислений, ключи,
# имена полей и участников, номера и признаки да/нет. Свободного текста тут не бывает и
# быть не должно — ни причины перехода, ни значений разделов, ни тел. Опись входит в
# каждый пакет задачи, и её дешевизна держится ровно на этом.
#
# Форма фактов зависит от типа записи, поэтому они объявлены **размеченным
# объединением**, а не одним объектом со всеми полями всех типов. Одним объектом это и
# было: шестнадцать полей, из которых у любой записи заполнено одно-три, а остальные
# ехали как `null` — строка описи весила 339 байт вместо ста. Хуже цены было то, что
# состав фактов каждого типа нигде не назывался: читающий узнавал его из того, какие
# ключи пришли непустыми, то есть из побочного эффекта сериализации.
#
# Разметка — `type`, тот же тип записи. Он повторяет `type` строки описи, и это
# осознанная плата: без него `facts` нельзя истолковать, не заглянув в соседнее поле, а
# значение путешествует отдельно от строки — его отдельно принимает сборка заголовка в
# интерфейсе. Варианты сгруппированы по форме, а не по типам: у восьми типов фактов нет
# вовсе, и восемь одинаково пустых моделей отличались бы только строкой разметки.


@dataclass(frozen=True, slots=True)
class NoFacts:
    """Фактов нет: заголовок записи пишет её автор, и он осмыслен сам по себе.

    Тип всё равно назван — иначе объединение не размечено, и «фактов нет» стало бы
    неотличимо от «факты не приехали».
    """

    type: EntryType


@dataclass(frozen=True, slots=True)
class StatusChangedFacts:
    """`status_changed`: откуда, куда и была ли причина. Сама причина — в теле записи."""

    type: Literal[EntryType.STATUS_CHANGED] = EntryType.STATUS_CHANGED
    from_status: TaskStatus | None = None
    to_status: TaskStatus | None = None
    has_reason: bool | None = None


@dataclass(frozen=True, slots=True)
class SectionChangedFacts:
    """`section_changed`: какой раздел правили. Значения — в записи, они бывают длинными.

    `check_no` стоит у точечной правки проверки и отсутствует у правки списка целиком:
    различать их надо именно здесь, они задевают разные вердикты
    (`mark_outdated_verdicts`).
    """

    type: Literal[EntryType.SECTION_CHANGED] = EntryType.SECTION_CHANGED
    field: TaskField | None = None
    check_no: int | None = None


@dataclass(frozen=True, slots=True)
class FieldChangedFacts:
    """`field_changed`: какое поле обвязки правили. Значения — в записи.

    Без `check_no`: проверки — раздел задания, а обвязка правится в любом незакрытом
    статусе, и точечной правки у неё не бывает.
    """

    type: Literal[EntryType.FIELD_CHANGED] = EntryType.FIELD_CHANGED
    field: TaskField | None = None


@dataclass(frozen=True, slots=True)
class AssigneeChangedFacts:
    """`assignee_changed`: имена участников коротки, поэтому их видно прямо в описи."""

    type: Literal[EntryType.ASSIGNEE_CHANGED] = EntryType.ASSIGNEE_CHANGED
    assignee_from: str | None = None
    assignee_to: str | None = None


@dataclass(frozen=True, slots=True)
class LinkFacts:
    """`link_added` и `link_removed`: чем задача стала другой и какой.

    Один вариант на два типа: форма у них одна, а разметка различает их сама — `type`
    здесь без значения по умолчанию именно поэтому.
    """

    type: Literal[EntryType.LINK_ADDED, EntryType.LINK_REMOVED]
    link_kind: LinkKind | None = None
    other_key: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionFacts:
    """`question`: кому адресовано и держит ли работу."""

    type: Literal[EntryType.QUESTION] = EntryType.QUESTION
    addressees: tuple[str, ...] | None = None
    blocking: bool | None = None


@dataclass(frozen=True, slots=True)
class AnswerFacts:
    """`answer`: на какой вопрос отвечено."""

    type: Literal[EntryType.ANSWER] = EntryType.ANSWER
    question_no: int | None = None


@dataclass(frozen=True, slots=True)
class VerdictFacts:
    """`verdict`: какая проверка и чем кончилась.

    `outdated` — относится ли вердикт к нынешней формулировке своей проверки. Считается
    при чтении описи, в нагрузке записи его нет и быть не может: он о том, что случилось
    **после** неё.
    """

    type: Literal[EntryType.VERDICT] = EntryType.VERDICT
    check_no: int | None = None
    outcome: VerdictOutcome | None = None
    outdated: bool | None = None


@dataclass(frozen=True, slots=True)
class ResolutionFacts:
    """`resolution`: какое замечание разобрано, чем и куда ушла работа.

    Исход зовётся `outcome`, как и у вердикта: перечисления у них разные, но разметка
    развела их по разным вариантам, и одно имя больше ни с чем не сливается.
    """

    type: Literal[EntryType.RESOLUTION] = EntryType.RESOLUTION
    remark_no: int | None = None
    outcome: RemarkOutcome | None = None
    continuation_key: str | None = None


type EntryFacts = (
    NoFacts
    | StatusChangedFacts
    | SectionChangedFacts
    | FieldChangedFacts
    | AssigneeChangedFacts
    | LinkFacts
    | QuestionFacts
    | AnswerFacts
    | VerdictFacts
    | ResolutionFacts
)
"""Факты записи: размеченное по `type` объединение всех форм."""


#: Какой форме фактов отвечает какой тип записи. Словарь **сплошной** по `EntryType` и
#: этим ценен: тип, заведённый завтра, обязан назвать здесь свою форму или сказать
#: `NoFacts` вслух, и пока он этого не сделал, набор его фактов нигде не объявлен.
#: Сплошность стережёт тест — перечислять типы руками в нём нельзя.
FACTS_BY_ENTRY_TYPE: Mapping[EntryType, type[EntryFacts]] = {
    EntryType.SUMMARY: NoFacts,
    EntryType.DECISION: NoFacts,
    EntryType.ATTEMPT: NoFacts,
    EntryType.FINDING: NoFacts,
    EntryType.ARTIFACT: NoFacts,
    EntryType.QUESTION: QuestionFacts,
    EntryType.ANSWER: AnswerFacts,
    EntryType.VERDICT: VerdictFacts,
    EntryType.REMARK: NoFacts,
    EntryType.RESOLUTION: ResolutionFacts,
    EntryType.NOTE: NoFacts,
    EntryType.CREATED: NoFacts,
    EntryType.STATUS_CHANGED: StatusChangedFacts,
    EntryType.SECTION_CHANGED: SectionChangedFacts,
    EntryType.FIELD_CHANGED: FieldChangedFacts,
    EntryType.ASSIGNEE_CHANGED: AssigneeChangedFacts,
    EntryType.LINK_ADDED: LinkFacts,
    EntryType.LINK_REMOVED: LinkFacts,
}


def mark_outdated_verdicts(index: Sequence[EntryHeading]) -> list[EntryHeading]:
    """Помечает вердикты, чью проверку переписали после них.

    Записи неизменяемы, и подшитый вердикт не правится и не исчезает — меняется то, как
    его читают (`CONCEPT.md`, 4.4). Без пометки дело становится тихо неверным: вердикт
    ссылается на **номер**, а не на текст, и читающий уверен, что проверка 3 пройдена,
    хотя пройдена была её прежняя формулировка.

    Считается одним проходом с конца: правка проверки помечает всё, что подшито до неё.
    Правка списка целиком (`check_no` у записи нет) задевает любой номер — состав мог
    измениться, и номера могли сдвинуться.

    Опись приходит упорядоченной по номеру записи, и порядок здесь существенен: он и
    есть «до» и «после».
    """
    rewritten: set[int] = set()
    whole_list_rewritten = False
    marked: list[EntryHeading] = []
    for heading in reversed(index):
        facts = heading.facts
        if isinstance(facts, SectionChangedFacts) and facts.field is TaskField.CHECKS:
            if facts.check_no is None:
                whole_list_rewritten = True
            else:
                rewritten.add(facts.check_no)
        elif isinstance(facts, VerdictFacts) and facts.check_no is not None:
            outdated = whole_list_rewritten or facts.check_no in rewritten
            heading = replace(heading, facts=replace(facts, outdated=outdated))
        marked.append(heading)
    marked.reverse()
    return marked


@dataclass(frozen=True, slots=True)
class EntryHeading:
    """Строка описи дела: то, что преемник видит о записи, не читая её тела.

    Поля концепции (4.2) — `no`, `type`, `author`, `created_at`, `title` — плюс `facts`:
    ограниченный по длине набор, по которому ту же запись можно назвать строкой на
    любом языке, не разбирая собранный трекером английский заголовок. Тело и `payload`
    по-прежнему читаются точечно по номеру.

    Значения по умолчанию у `facts` нет: форма фактов следует из типа записи, и «строка
    описи без фактов» — это `NoFacts` с названным типом, а не пропущенный аргумент.
    """

    no: int
    type: EntryType
    author: Author
    created_at: datetime
    title: str
    facts: EntryFacts


# --- Ссылки -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskRef:
    """Ссылка на задачу: `TRK-7`. Ключ уже канонизирован."""

    key: str


@dataclass(frozen=True, slots=True)
class EntryRef:
    """Ссылка на запись: `TRK-42#12`. Ключ уже канонизирован."""

    key: str
    no: int


def parse_ref(ref: str) -> TaskRef | EntryRef | None:
    """Разбирает ссылку. `None` означает «это адрес» — его трекер не проверяет.

    Бросает `FieldProblem`, если строка выглядит ссылкой внутрь трекера, но номер
    записи в ней испорчен (`TRK-42#0`, `TRK-42#абв`): молча превратить такую строку в
    непроверяемый адрес значило бы потерять опечатку ровно там, где ссылка нужна
    надёжной.
    """
    head, separator, tail = ref.partition(ENTRY_REF_SEPARATOR)
    try:
        key = normalize_task_key(head)
    except InvalidTaskKeyError:
        # Голова не ключ задачи — значит, вся строка адрес. Сюда попадает и URL с
        # якорем (`https://example.com/a#b`): его голова ключом не разбирается.
        return None
    if not separator:
        return TaskRef(key=key)
    if not is_plain_number(tail) or int(tail) < FIRST_ENTRY_NUMBER:
        raise FieldProblem("malformed_entry_ref", ref=ref, expected=ENTRY_REF_SHAPE)
    return EntryRef(key=key, no=int(tail))


# --- Запись агента ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntryDraft:
    """Проверенная запись до подшивки: всё, что зависело только от формы, уже сошлось.

    Проверки, которым нужна база (существует ли адресат, есть ли такая запись, тот ли
    это вопрос), делает `app/services/case.py` — домен в базу не ходит.
    """

    type: EntryType
    title: str
    body: str
    payload: dict[str, Any]
    refs: list[str]
    #: Ссылки внутрь трекера, уже разобранные: их существование проверяет сценарий.
    tracker_refs: tuple[TaskRef | EntryRef, ...] = ()


@dataclass(frozen=True, slots=True)
class EntryContext:
    """Всё о задаче, что нужно проверкам формы записи: ключ, её проверки и повод.

    `closing` — не свойство задачи, а повод, по которому подшивают: та же сводка при
    закрытии обязана нести пятую часть, а посреди работы не смеет. Признак стоит здесь,
    а не в сценарии закрытия, потому что форма записи целиком живёт в домене: иначе у
    одного поля оказалось бы два разных отказа — `entry_fields_invalid` из `build_entry`
    для пустого значения и чужая ошибка сценария для отсутствующего (TRK-78).
    """

    task_key: str
    checks: Sequence[str]
    closing: bool = False


def build_entry(
    context: EntryContext,
    *,
    type: Any,
    title: Any = None,
    body: Any = "",
    payload: Mapping[str, Any] | None = None,
    refs: Any = (),
) -> EntryDraft:
    """Проверяет запись агента и приводит её к каноническому виду.

    Замечания собираются **все сразу** и уезжают списком в `details.fields` — по тому
    же правилу, что и у полей задачи: агент исправляет запрос за одну попытку, а не за
    пять кругов.

    Служебные типы (`created`, `status_changed`, ...) отвергаются здесь: их подшивает
    сценарий, выводя тип из действия, и принять такой тип снаружи значило бы позволить
    подделать историю задачи.
    """
    problems = FieldProblems()
    entry_type = _entry_type(type, problems)
    body_text = _entry_body(body, problems)
    tracker_refs, ref_strings = _entry_refs(refs, problems)

    payload_values: dict[str, Any] = {}
    entry_title = ""
    if entry_type is not None:
        payload_values = _PAYLOAD_BUILDERS[entry_type](dict(payload or {}), context, problems)
        if entry_type in TITLED_ENTRY_TYPES:
            with problems.field("title"):
                entry_title = _entry_title(title)
        elif title is not None:
            problems.add("title", "not_allowed", derived_from=_TITLE_SOURCES[entry_type])

    problems.raise_as(EntryFieldsInvalidError, key=context.task_key)

    assert entry_type is not None  # иначе замечание о типе уже прервало бы работу
    if entry_type not in TITLED_ENTRY_TYPES:
        entry_title = _derive_title(entry_type, payload_values, context)
    return EntryDraft(
        type=entry_type,
        title=entry_title,
        body=body_text,
        payload=payload_values,
        refs=ref_strings,
        tracker_refs=tracker_refs,
    )


def summary_title(done: str) -> str:
    """Заголовок сводки — первая непустая строка `done`.

    Именно «сделано», а не следующий шаг: преемник читает столбец заголовков сверху
    вниз, и там должна стоять хронология. Следующий шаг протухает — исполненный,
    отменённый или выдуманный ради закрытия задачи, он занимал бы самое видное место
    записи, ничего о ней не говоря. Сам `next_step` от этого никуда не делся: его
    читают в последней сводке, которая приезжает в пакет задачи целиком.
    """
    for line in done.splitlines():
        stripped = line.strip()
        if stripped:
            return _shorten(stripped)
    # Пустых частей у сводки не бывает — их отвергает проверка, — но текст из одних
    # переводов строки формально непуст, и заголовку нужно хоть что-то.
    return _shorten(done.strip())


def continuation_key(payload: Mapping[str, Any]) -> str | None:
    """Задача, в которую ушла работа по замечанию, — из нагрузки резолюции.

    Отдельной функцией по той же причине, что и `is_blocking_question`: тот же ключ
    ищет запросом отбор `remarks_in_work` (`app/db/repositories/entries.py`,
    `continuation_of`), и двум формам одного определения нужно общее имя.
    """
    key = payload.get("task")
    return key if isinstance(key, str) else None


def is_blocking_question(payload: Mapping[str, Any]) -> bool:
    """Помечен ли вопрос как блокирующий — определение признака `open_blocking_questions`.

    Отдельной функцией, хотя это одно обращение к словарю: тот же признак поиск считает
    массово запросом (`app/db/repositories/entries.py`, `blocking_is`), и две формы
    одного определения обязаны совпадать. Пока они лежат по разным слоям, единственное,
    что их удерживает вместе, — имя, ссылка отсюда туда и тест, сверяющий карточку с
    выдачей поиска на одних и тех же данных.

    `is True`, а не приведение к логическому: у записи не-вопроса ключа нет вовсе, и
    `bool(None)` совпал бы с ответом «не блокирующий» случайно, а не по правилу.
    """
    return payload.get("blocking") is True


# --- Внутреннее: форма полей --------------------------------------------------------


def _entry_type(value: Any, problems: FieldProblems) -> EntryType | None:
    """Тип записи агента. Служебные и неизвестные отвергаются с допустимым списком.

    `None` означает «тип не разобрался»: замечание уже записано, и остальные проверки
    идут без него, чтобы клиент получил все замечания разом, а не одно про тип.
    """
    allowed = sorted(AGENT_ENTRY_TYPES)
    try:
        entry_type = EntryType(value)
    except ValueError:
        problems.add("type", "not_allowed", allowed=allowed)
        return None
    if entry_type in SERVICE_ENTRY_TYPES:
        # Служебную запись подшивает сценарий, выводя тип из действия. Принять такой
        # тип снаружи значило бы позволить подделать историю задачи.
        problems.add("type", "service_type", allowed=allowed, got=entry_type.value)
        return None
    return entry_type


def _entry_title(value: Any) -> str:
    title = _text(value).strip()
    if not title:
        raise FieldProblem("required")
    if "\n" in title or "\r" in title:
        raise FieldProblem("multiline_not_allowed")
    if len(title) > MAX_ENTRY_TITLE_LENGTH:
        raise FieldProblem("too_long", max=MAX_ENTRY_TITLE_LENGTH, got=len(title))
    return title


def _entry_body(value: Any, problems: FieldProblems) -> str:
    """Тело необязательно: у записи вроде `artifact` всё содержание в заголовке и ссылках."""
    if not isinstance(value, str):
        problems.add("body", "not_a_string")
        return ""
    if len(value) > MAX_ENTRY_BODY_LENGTH:
        problems.add("body", "too_long", max=MAX_ENTRY_BODY_LENGTH, got=len(value))
        return ""
    return value.strip()


def _entry_refs(
    value: Any,
    problems: FieldProblems,
) -> tuple[tuple[TaskRef | EntryRef, ...], list[str]]:
    """Разбирает ссылки: трекерные отдельно для проверки существования, все — строками."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        problems.add("refs", "not_a_list")
        return (), []

    parsed: list[TaskRef | EntryRef] = []
    strings: list[str] = []
    seen: set[str] = set()
    for item in value:
        with problems.field("refs"):
            ref = _text(item).strip()
            if not ref:
                raise FieldProblem("empty_item")
            if len(ref) > MAX_REF_LENGTH:
                raise FieldProblem("too_long", ref=ref, max=MAX_REF_LENGTH, got=len(ref))
            target = parse_ref(ref)
            # Ссылка внутрь трекера хранится канонической (`trk-42#7` → `TRK-42#7`):
            # иначе одна и та же запись выглядела бы в делах по-разному.
            canonical = _format_ref(target) if target is not None else ref
            if canonical not in seen:
                seen.add(canonical)
                strings.append(canonical)
                if target is not None:
                    parsed.append(target)
    if len(strings) > MAX_REFS:
        problems.add("refs", "too_many", max=MAX_REFS, got=len(strings))
    return tuple(parsed), strings


def _format_ref(target: TaskRef | EntryRef) -> str:
    if isinstance(target, EntryRef):
        return format_entry_ref(target.key, target.no)
    return target.key


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise FieldProblem("not_a_string")
    return value


def _shorten(title: str) -> str:
    """Обрезает заголовок по границе слова: первая строка `done` бывает длинной.

    Посимвольная обрезка рвала бы слово и разметку посередине («…(кирпичи `shared/…»).
    Поэтому лишнее отбрасывается до последнего пробела, влезающего в потолок, а хвост
    из разделителей снимается, чтобы многоточие не приклеивалось к запятой. Пробела в
    пределах потолка может не быть вовсе — одно длинное слово, — и тогда остаётся
    посимвольная обрезка: заголовок у записи обязателен, и отказаться от него нельзя.
    """
    if len(title) <= MAX_ENTRY_TITLE_LENGTH:
        return title
    head = title[: MAX_ENTRY_TITLE_LENGTH - len(TITLE_ELLIPSIS)]
    boundary = head.rfind(" ")
    if boundary > 0:
        head = head[:boundary].rstrip(TITLE_CUT_TRAILING)
    return head + TITLE_ELLIPSIS


# --- Внутреннее: нагрузка по типам --------------------------------------------------
#
# Одна функция на тип, все с одной сигнатурой: сырая нагрузка, контекст задачи,
# накопитель замечаний. Поле, которого нет в нагрузке типа, отвергается — «лишнее»
# молча выброшенное поле означало бы, что агент считает записанным то, чего в деле нет.


type _PayloadBuilder = Callable[[dict[str, Any], EntryContext, FieldProblems], dict[str, Any]]


def _no_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """У `decision`, `attempt`, `finding`, `artifact` и `note` нагрузки нет."""
    _reject_extra(raw, (), problems)
    return {}


def _summary_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Части сводки, все непустые: справка без «осталось» бесполезна преемнику.

    Набор частей задаёт повод, а не тип записи: при закрытии к четырём добавляется
    `unmeasured`, и там она обязательна ровно так же, как остальные. Посреди работы её
    не принимают — не молча выбрасывают, а отвергают как всякое чужое поле: агент,
    пославший её в `add_summary`, должен узнать, что подшилась сводка без неё.
    """
    parts = CLOSING_SUMMARY_PARTS if context.closing else SUMMARY_PARTS
    _reject_extra(raw, parts, problems)
    payload: dict[str, Any] = {}
    for part in parts:
        with problems.field(part):
            payload[part] = _summary_part(raw.get(part))
    return payload


def _summary_part(value: Any) -> str:
    if value is None:
        # Непереданная часть и присланная пустой — одна ошибка агента: части нет.
        # `not_a_string` от `_text` звал бы его разбираться с типами, хотя тип он не
        # присылал вовсе; так же отвечают `_entry_number` и `_check_number`.
        raise FieldProblem("required")
    part = _text(value).strip()
    if not part:
        raise FieldProblem("required")
    if len(part) > MAX_SUMMARY_PART_LENGTH:
        raise FieldProblem("too_long", max=MAX_SUMMARY_PART_LENGTH, got=len(part))
    return part


def _question_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Адресаты и признак `blocking`. Существование адресатов проверяет сценарий."""
    _reject_extra(raw, ("addressees", "blocking"), problems)
    payload: dict[str, Any] = {}
    with problems.field("addressees"):
        payload["addressees"] = _addressees(raw.get("addressees"))
    with problems.field("blocking"):
        blocking = raw.get("blocking")
        if not isinstance(blocking, bool):
            # Обязателен и без значения по умолчанию: «можно ли продолжать без ответа»
            # знает только спрашивающий, а угаданное значение решает за него.
            raise FieldProblem("required" if blocking is None else "not_a_boolean")
        payload["blocking"] = blocking
    return payload


def _addressees(value: Any) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise FieldProblem("not_a_list")
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise FieldProblem("not_a_string")
        name = item.strip().lower()
        if not name:
            raise FieldProblem("empty_item")
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        raise FieldProblem("required")
    if len(names) > MAX_ADDRESSEES:
        raise FieldProblem("too_many", max=MAX_ADDRESSEES, got=len(names))
    return names


def _answer_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Номер вопроса той же задачи. Что это именно вопрос, проверяет сценарий."""
    _reject_extra(raw, ("question_no",), problems)
    payload: dict[str, Any] = {}
    with problems.field("question_no"):
        payload["question_no"] = _entry_number(raw.get("question_no"))
    return payload


def _verdict_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Номер обзорной проверки в пределах списка задачи и исход из двух значений."""
    _reject_extra(raw, ("check_no", "outcome"), problems)
    payload: dict[str, Any] = {}
    with problems.field("check_no"):
        payload["check_no"] = _check_number(raw.get("check_no"), context.checks)
    with problems.field("outcome"):
        try:
            payload["outcome"] = VerdictOutcome(raw.get("outcome")).value
        except ValueError:
            raise FieldProblem(
                "not_allowed", allowed=[outcome.value for outcome in VerdictOutcome]
            ) from None
    return payload


def _resolution_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Номер разбираемого замечания, исход из четырёх и адрес работы.

    Что `remark_no` указывает именно на замечание **этой** задачи, проверяет сценарий, —
    как и у ответа. Здесь только форма: номер, значение исхода и правило про `task`.
    """
    _reject_extra(raw, ("remark_no", "outcome", "task"), problems)
    payload: dict[str, Any] = {}
    with problems.field("remark_no"):
        payload["remark_no"] = _entry_number(raw.get("remark_no"))

    outcome: RemarkOutcome | None = None
    with problems.field("outcome"):
        try:
            outcome = RemarkOutcome(raw.get("outcome"))
        except ValueError:
            raise FieldProblem(
                "not_allowed", allowed=[item.value for item in RemarkOutcome]
            ) from None
        payload["outcome"] = outcome.value

    with problems.field("task"):
        # Ключ кладётся всегда, в том числе пустым: форма записи одна на все интерфейсы,
        # и `payload` без ключа в MCP против `"task": null` в REST означал бы два разных
        # описания одной записи. Так же устроен `reason` у `status_changed`.
        payload["task"] = _continuation_key(raw.get("task"), outcome)
    return payload


def _continuation_key(value: Any, outcome: RemarkOutcome | None) -> str | None:
    """Ключ задачи-продолжения: обязателен при `accepted` и не принимается при остальных.

    Существование задачи проверяет сценарий; здесь только форма ключа и правило пары
    «исход — адрес». Пока исход не разобрался, поле молчит: сказать о нём нечего, а
    второе замечание о том же поле сбивало бы с толку.
    """
    if outcome is None:
        return None
    if outcome is not OUTCOME_WITH_CONTINUATION:
        if value is not None:
            raise FieldProblem(
                "not_allowed", required_for=OUTCOME_WITH_CONTINUATION.value, got=outcome.value
            )
        return None
    if value is None:
        raise FieldProblem("required", required_for=OUTCOME_WITH_CONTINUATION.value)
    try:
        return normalize_task_key(_text(value))
    except InvalidTaskKeyError:
        # Ключ разбирается тем же кодом, что и ссылки, но замечание о нём приходит
        # полем нагрузки: агент чинит `task`, а не гадает, какая часть запроса не та.
        raise FieldProblem("malformed_task_key", got=value) from None


def _entry_number(value: Any) -> int:
    """Номер записи: целое с 1. `bool` — тоже `int`, поэтому отсеивается явно."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldProblem("required" if value is None else "not_an_integer")
    if value < FIRST_ENTRY_NUMBER:
        raise FieldProblem("out_of_range", min=FIRST_ENTRY_NUMBER, got=value)
    return value


def _check_number(value: Any, checks: Sequence[str]) -> int:
    """Номер проверки: позиция в списке `checks` задачи, нумерация с 1.

    Допустимый диапазон уезжает в подробностях: агент не обязан помнить, сколько
    проверок в задаче, а из ответа это должно быть видно без второго запроса.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldProblem("required" if value is None else "not_an_integer")
    last = FIRST_CHECK_NUMBER + len(checks) - 1
    if not checks:
        raise FieldProblem("no_checks", got=value)
    if not FIRST_CHECK_NUMBER <= value <= last:
        raise FieldProblem("out_of_range", min=FIRST_CHECK_NUMBER, max=last, got=value)
    return value


def _reject_extra(raw: dict[str, Any], allowed: Sequence[str], problems: FieldProblems) -> None:
    for name in sorted(set(raw) - set(allowed)):
        problems.add(name, "not_allowed", allowed=list(allowed))


_PAYLOAD_BUILDERS: dict[EntryType, _PayloadBuilder] = {
    EntryType.SUMMARY: _summary_payload,
    EntryType.DECISION: _no_payload,
    EntryType.ATTEMPT: _no_payload,
    EntryType.FINDING: _no_payload,
    EntryType.ARTIFACT: _no_payload,
    EntryType.QUESTION: _question_payload,
    EntryType.ANSWER: _answer_payload,
    EntryType.VERDICT: _verdict_payload,
    EntryType.REMARK: _no_payload,
    EntryType.RESOLUTION: _resolution_payload,
    EntryType.NOTE: _no_payload,
}

#: Откуда берётся заголовок у типов, которые его не принимают. Строка уезжает в
#: подробности отказа: клиент, приславший заголовок, должен понять, чем его заменили.
_TITLE_SOURCES: dict[EntryType, str] = {
    EntryType.SUMMARY: "done",
    EntryType.ANSWER: "question_no",
    EntryType.VERDICT: "check_no, outcome",
    EntryType.RESOLUTION: "remark_no, outcome",
}


def _derive_title(entry_type: EntryType, payload: dict[str, Any], context: EntryContext) -> str:
    """Заголовок типов, которые его не принимают.

    Выведенные заголовки — служебный слой, поэтому английские, как и у записей трекера
    (`Status changed: backlog -> open`). Исключение — сводка: её заголовок это первая
    строка текста автора, то есть пользовательские данные.
    """
    if entry_type is EntryType.SUMMARY:
        return summary_title(payload["done"])
    if entry_type is EntryType.ANSWER:
        return f"Answer to {format_entry_ref(context.task_key, payload['question_no'])}"
    if entry_type is EntryType.VERDICT:
        return f"Verdict on check {payload['check_no']}: {payload['outcome']}"
    if entry_type is EntryType.RESOLUTION:
        remark = format_entry_ref(context.task_key, payload["remark_no"])
        return f"Resolution of {remark}: {payload['outcome']}"
    raise AssertionError(f"Entry type {entry_type.value} carries its own title")
