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

`refs` содержит ссылки на записи задач (`TRK-42#12`), на записи проекта (`TRK#7`), на
задачи (`TRK-7`) и адреса. Ссылки внутрь трекера он проверяет на существование, адреса не
проверяет вовсе (`CONCEPT.md`, 3.4). Различить их можно только по форме, поэтому правило
простое: если голова разбирается как ключ задачи — это ссылка внутрь трекера, иначе адрес.
Ловушка здесь одна и она закрыта: `TRK-42#абв` разбирается как ключ задачи с испорченным
номером записи, и молча считать такую строку адресом нельзя — это опечатка в ссылке, а
не URL.

Запись проекта узнаётся уже: голова по шаблону ключа проекта **и** хвост из цифр.
Шаблон ключа проекта ловит любое слово (`README`, `notes`), и ссылка `README#usage` была
адресом до того, как у проекта появилось дело; с нецифровым хвостом она им и остаётся.
Цифровой хвост — уже ссылка: `TRK#007` и `TRK#0` — опечатки, а не адреса.

Запись области (`TRK/promotion#3`, `CONCEPT.md`, 3.7) узнаётся так же узко: голова —
адрес, то есть ключ проекта по шаблону, косая черта и ключ области по шаблону, и хвост
из цифр. Всё прочее с косой чертой (`docs/x.md#3`) — не ссылка трекера и должно быть URL.

## Дело проекта и дело области

У проекта своё дело с той же механикой (`CONCEPT.md`, 3.4, «Дело проекта»), но из
записей агента в нём только `note`, `decision`, `finding` и `artifact`: у проекта нет
ни хода работы, ни проверок, ни исполнителя. Форму такой записи проверяет
`build_project_entry` теми же функциями полей, что и `build_entry`. Дело области
устроено так же (`CONCEPT.md`, 3.7) и проверяется той же функцией, только без
`supersedes`: механика решений проекта на него не распространяется.

## Дело обсуждения

Четвёртый владелец записи — обсуждение (решение `TRK#51`, п. 2). Его дело — переписка:
вопрос, ответ, заметка и итог (`DISCUSSION_ENTRY_TYPES`). Форму проверяет тот же
`build_entry` с контекстом обсуждения (`EntryContext.discussion`): ответ и заметка
устроены как в деле задачи, признак `blocking` у вопроса не выбирают — держит любой
вопрос, и в нагрузке он всегда `true`, — а итог из трёх непустых частей бывает только
здесь. Ссылка на обсуждение — `TRK~7`, на
его запись — `TRK~7#3`: тильды нет ни в ключе задачи, ни в адресе области.
"""

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from app.domain.areas import (
    ADDRESS_SEPARATOR,
    format_area_address,
    is_area_key,
    parse_area_address,
)
from app.domain.authors import Author
from app.domain.discussions import (
    CONCLUSION_PARTS,
    DISCUSSION_SEPARATOR,
    format_discussion_address,
    is_discussion_address,
    parse_discussion_address,
)
from app.domain.errors import EntryFieldsInvalidError, InvalidTaskKeyError
from app.domain.fields import FieldProblem, FieldProblems
from app.domain.links import LinkKind
from app.domain.projects import PROJECT_KEY_PATTERN, normalize_project_key
from app.domain.tasks import (
    ENTRY_REF_SEPARATOR,
    FIRST_CHECK_NUMBER,
    FIRST_ENTRY_NUMBER,
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
    ACCEPTANCE = "acceptance"
    CONCLUSION = "conclusion"
    NOTE = "note"
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    SECTION_CHANGED = "section_changed"
    FIELD_CHANGED = "field_changed"
    ASSIGNEE_CHANGED = "assignee_changed"
    LINK_ADDED = "link_added"
    LINK_REMOVED = "link_removed"
    MOVED = "moved"
    WARNING = "warning"
    ATTACHED = "attached"
    DETACHED = "detached"
    CLOSED = "closed"
    ATTRIBUTE_CREATED = "attribute_created"
    ATTRIBUTE_CHANGED = "attribute_changed"
    ATTRIBUTE_REMOVED = "attribute_removed"
    ARCHIVED = "archived"
    RESTORED = "restored"


class VerdictOutcome(StrEnum):
    """Исход обзорной проверки (`CONCEPT.md`, 3.4; решение TRK-533#27).

    Выбор — два вопроса, ответы на которые исполнитель знает в момент вердикта: прогнал
    ли он проверку так, как она написана, и получил ли ожидаемое целиком.

    - `passed` — прогнана как написана, ожидаемое получено целиком. Доказательство, где
      названо несделанное, подменённый объект или окружение либо красный прогон, — уже
      не `passed`.
    - `partial` — прогнана как написана, ожидаемое получено частью.
    - `unverifiable` — как написана, её прогнать нельзя: объекта или окружения нет под
      рукой, или требования сменились.
    - `failed` — прогнана как написана, ожидаемого нет.

    `partial` и `unverifiable` задачу закрыть дают, но с предупреждением
    (`INCOMPLETE_OUTCOMES`); `failed` — не даёт. До них честного исхода у недоделанной и
    невыполнимой проверки не было, и её закрывали `passed` с оговоркой рядом (TRK-545#11).
    """

    PASSED = "passed"
    PARTIAL = "partial"
    UNVERIFIABLE = "unverifiable"
    FAILED = "failed"


#: Исходы «не целиком»: проверка засчитывается для закрытия, но закрытие подшивает
#: предупреждение `warning`, и доказательство у вердикта обязательно — именно в нём
#: названо, чего нет или почему прогнать нельзя. Трекер текст не читает (как и
#: `unmeasured`): он требует, чтобы объяснение было, а не проверяет, какое оно.
INCOMPLETE_OUTCOMES: frozenset[VerdictOutcome] = frozenset(
    {VerdictOutcome.PARTIAL, VerdictOutcome.UNVERIFIABLE}
)

#: Записи, которые снимают предупреждение, подшитые **после** него: `acceptance` —
#: недостаток принят, `remark` — задачу возвращают на доработку замечанием, и дальше она
#: живёт по правилам замечаний (решение TRK-561#11). Одно определение на карточку
#: (`open_warning`) и на поиск (`app/db/repositories/entries.py`, `open_warning_count`).
WARNING_REACTIONS: frozenset[EntryType] = frozenset({EntryType.ACCEPTANCE, EntryType.REMARK})


class QuestionOrder(StrEnum):
    """Порядок выдачи вопросов поперёк задач (`GET /api/v1/questions`).

    Два порядка — два вопроса человека. «Входящая» идёт от старых: дольше всех ждёт
    ответа тот, кого спросили первым, и он обязан стоять сверху. История идёт от свежих:
    там ищут недавний разговор, а не долг, и первым экраном нужно последнее.
    """

    OLDEST = "oldest"
    NEWEST = "newest"


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


class AnswerOutcome(StrEnum):
    """Чем закрыт вопрос записью `answer` (`CONCEPT.md`, 3.4; решение TRK-549#16).

    `answered` — ответ по существу, как было всегда. `withdrawn` — вопрос снят: устарел,
    и ответ на него больше не нужен. `replaced` — вопрос заменён другим вопросом той же
    задачи (`replaced_by`). Снятие и замена — тоже записи `answer`, а не новый тип и не
    флаг у вопроса: записи неизменяемы, и вопрос закрывается так же, как всегда, —
    первым ответом. Поэтому формула «вопрос открыт» (`app/db/repositories/entries.py`,
    `_unanswered`) снятия не знает и знать не должна.
    """

    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"
    REPLACED = "replaced"


#: Исход, при котором ответ обязан назвать заменивший вопрос, — и единственный, при
#: котором `replaced_by` вообще принимается. Устроено как `OUTCOME_WITH_CONTINUATION`.
OUTCOME_WITH_REPLACEMENT = AnswerOutcome.REPLACED

#: Исходы, которые закрывают вопрос без ответа по существу. Такой исход бывает только у
#: **первого** ответа: снять отвеченный вопрос нельзя — в деле остался бы ответ без
#: вопроса (слово владельца, TRK-549#14). Это проверяет сценарий под очередью изменений.
#: У обоих причина в теле записи обязательна: снятие без причины — это вопрос, который
#: молча исчез из входящей.
CLOSING_WITHOUT_ANSWER: frozenset[AnswerOutcome] = frozenset(
    {AnswerOutcome.WITHDRAWN, AnswerOutcome.REPLACED}
)


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
        EntryType.MOVED,
        EntryType.WARNING,
        EntryType.ATTACHED,
        EntryType.DETACHED,
        EntryType.CLOSED,
        EntryType.ATTRIBUTE_CREATED,
        EntryType.ATTRIBUTE_CHANGED,
        EntryType.ATTRIBUTE_REMOVED,
        EntryType.ARCHIVED,
        EntryType.RESTORED,
    }
)

#: Служебные записи об атрибутах проекта и области (`CONCEPT.md`, 3.2, 3.4 и 3.7):
#: заведение, изменение и снятие. Бывают только в делах проекта и области — атрибутов у
#: задач нет, — и тип из трёх выбирает сценарий `set_attribute`/`remove_attribute`, а не
#: вызывающий.
ATTRIBUTE_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {EntryType.ATTRIBUTE_CREATED, EntryType.ATTRIBUTE_CHANGED, EntryType.ATTRIBUTE_REMOVED}
)

#: Служебные записи об архивировании проекта и области (`CONCEPT.md`, 3.2 и 3.7):
#: `archived` и `restored` с причиной. Бывают только в делах проекта и области —
#: отдельного архива у задачи нет.
ARCHIVE_ENTRY_TYPES: frozenset[EntryType] = frozenset({EntryType.ARCHIVED, EntryType.RESTORED})

#: Записи агента и человека — всё, что не служебное.
AGENT_ENTRY_TYPES: frozenset[EntryType] = frozenset(EntryType) - SERVICE_ENTRY_TYPES

#: Служебные записи о привязке задачи к обсуждению и её снятии (решение `TRK#51`, п. 3):
#: подшиваются в дело задачи и в дело обсуждения одним действием, как `link_added`.
ATTACHMENT_ENTRY_TYPES: frozenset[EntryType] = frozenset({EntryType.ATTACHED, EntryType.DETACHED})

#: Записи агента и человека в деле обсуждения (решение `TRK#51`, п. 2): переписка и итог.
#: Сводок, вердиктов, замечаний и решений здесь нет — у обсуждения нет ни хода работы, ни
#: проверок; работу ведут привязанные задачи.
DISCUSSION_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {EntryType.QUESTION, EntryType.ANSWER, EntryType.NOTE, EntryType.CONCLUSION}
)

#: Записи, которые бывают только в деле обсуждения: итог и закрытие.
DISCUSSION_ONLY_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {EntryType.CONCLUSION, EntryType.CLOSED}
)

#: Записи агента и человека в деле задачи: всё агентское, кроме итога обсуждения.
TASK_ENTRY_TYPES: frozenset[EntryType] = AGENT_ENTRY_TYPES - DISCUSSION_ONLY_ENTRY_TYPES

#: Записи агента и человека в деле проекта (`CONCEPT.md`, 3.4, «Дело проекта») и в деле
#: области (3.7). Сводок, вопросов, вердиктов, замечаний и попыток у них нет: нет ни
#: хода работы, ни проверок, ни исполнителя, а спрашивают и возражают в делах задач.
PROJECT_ENTRY_TYPES: frozenset[EntryType] = frozenset(
    {EntryType.NOTE, EntryType.DECISION, EntryType.FINDING, EntryType.ARTIFACT}
)

#: Записи знания дела проекта — решение и заметка (решение TRK#48, раздел 2): только они
#: заменяются через `supersedes` и только у них есть статус «действует / заменена»,
#: который считается при чтении (`app/domain/decisions.py`). Запись заменяет прежнюю
#: своего типа: решение — решение, заметка — заметку.
REPLACEABLE_ENTRY_TYPES: frozenset[EntryType] = frozenset({EntryType.DECISION, EntryType.FINDING})

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
        EntryType.ACCEPTANCE,
        EntryType.NOTE,
    }
)

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

#: Поле нагрузки решения и заметки дела проекта: номера записей того же типа и того же
#: дела, которые новая запись заменяет (`CONCEPT.md`, 3.2; TRK#48). Им же называется
#: аргумент `add_project_entry`.
SUPERSEDES_FIELD = "supersedes"

#: Сколько записей заменяет одна. Замена пересказывает то, что остаётся в силе, и запись,
#: сводящая два десятка решений в одно, — уже пересмотр проекта, а не замена.
MAX_SUPERSEDES = 20

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

#: Форма ссылки на запись в подробностях отказа: по ней агент чинит опечатку. Форм
#: четыре — запись задачи, проекта, области и обсуждения; дефис есть только в ключе
#: задачи, косая черта — только в адресе области, тильда — только в адресе обсуждения.
ENTRY_REF_SHAPE = (
    f"<PROJECT>-<task number>{ENTRY_REF_SEPARATOR}<entry number>, "
    f"<PROJECT>{ENTRY_REF_SEPARATOR}<entry number>, "
    f"<PROJECT>{ADDRESS_SEPARATOR}<area>{ENTRY_REF_SEPARATOR}<entry number> or "
    f"<PROJECT>{DISCUSSION_SEPARATOR}<discussion number>{ENTRY_REF_SEPARATOR}<entry number>"
)

#: Голова ссылки на запись проекта: ключ проекта по его шаблону.
_PROJECT_KEY_RE = re.compile(PROJECT_KEY_PATTERN)

#: Что считается внешним адресом: схема по RFC 3986 (буква и буквы, цифры, `+ - .`) не
#: короче двух знаков — буква диска `C:\x` не схема — и непустой остаток после «:» без
#: пробелов. `TRK-42` двоеточия не содержит и сюда не попадает.
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:\S+$")

#: Допустимые виды ссылки в подробностях отказа `not_a_reference`.
REF_SHAPE = (
    "TRK-42#12, TRK#7, TRK/promotion#3, TRK~7#3, TRK-7, TRK~7 or a URL with a scheme such as "
    "https://example.com"
)

#: Чем обрезается слишком длинный выведенный заголовок. Обрезка, а не отказ: у сводки
#: заголовок берётся из текста автора, и отклонять справку из-за длинной первой строки
#: `done` значило бы терять её содержимое ради описи.
TITLE_ELLIPSIS = "…"

#: Что снимается с хвоста обрезанного заголовка перед многоточием: разделители, после
#: которых «…» читалось бы как оборванная фраза («слово,…» вместо «слово…»).
TITLE_CUT_TRAILING = " ,;:.-—"


def format_entry_ref(task_key: str, no: int) -> str:
    """Ссылка на запись: ключ задачи и номер записи в ней.

    Та же форма у записи проекта — `TRK#7`: ключ проекта на месте ключа задачи. Функция
    одна, потому что разделитель один; различает их дефис в ключе.
    """
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
    """`answer`: на какой вопрос отвечено, чем он закрыт и каким вопросом заменён.

    `outcome` у ответа, подшитого до появления исхода, читается как `answered`
    (`answer_outcome`): опись называет его так же, как называла всегда.
    """

    type: Literal[EntryType.ANSWER] = EntryType.ANSWER
    question_no: int | None = None
    outcome: AnswerOutcome | None = None
    replaced_by: int | None = None


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


@dataclass(frozen=True, slots=True)
class AttributeFacts:
    """`attribute_created`, `attribute_changed`, `attribute_removed`: имя атрибута.

    Имя ограничено шаблоном (`app/domain/attributes.py`) и потому едет в опись; значения
    и причина — свободный текст, они остаются в записи. Один вариант на три типа, как у
    связей: форма одна, разметку несёт `type`.
    """

    type: Literal[
        EntryType.ATTRIBUTE_CREATED, EntryType.ATTRIBUTE_CHANGED, EntryType.ATTRIBUTE_REMOVED
    ]
    name: str | None = None


@dataclass(frozen=True, slots=True)
class MovedFacts:
    """`moved`: с какого ключа на какой перенесена задача (`CONCEPT.md`, 3.3).

    Ключи — факты: они коротки и называют оба проекта своей левой частью. Причина —
    свободный текст и остаётся в записи.
    """

    type: Literal[EntryType.MOVED] = EntryType.MOVED
    from_key: str | None = None
    to_key: str | None = None


@dataclass(frozen=True, slots=True)
class WarningCheck:
    """Проверка, закрытая не целиком: номер и исход — `partial` или `unverifiable`."""

    check_no: int
    outcome: VerdictOutcome

    def as_payload(self) -> dict[str, Any]:
        """Вид, в котором пара лежит в нагрузке `warning` и уезжает в факты описи."""
        return {"check_no": self.check_no, "outcome": self.outcome.value}


@dataclass(frozen=True, slots=True)
class WarningFacts:
    """`warning`: номера проверок, закрытых `partial`, и закрытых `unverifiable`.

    Списки короткие по построению — не длиннее списка проверок задачи — и состоят из
    номеров, поэтому едут в опись целиком: по ним интерфейс называет предупреждение на
    языке человека, не разбирая английский заголовок. Два списка номеров, а не список
    пар, как в нагрузке, — ради цены схемы: факты стоят в `outputSchema` каждого
    инструмента с описью, и вложенная модель пары стоила бы там вдвое дороже
    (замер TRK-561).
    """

    type: Literal[EntryType.WARNING] = EntryType.WARNING
    partial: tuple[int, ...] | None = None
    unverifiable: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class AttachmentFacts:
    """`attached` и `detached`: какая задача и какое обсуждение (решение `TRK#51`, п. 3).

    Обе стороны названы в обоих делах — ключ задачи и адрес обсуждения коротки, — поэтому
    строка описи читается одинаково и в деле задачи, и в деле обсуждения. Один вариант на
    два типа, как у связей: форма одна, разметку несёт `type`.
    """

    type: Literal[EntryType.ATTACHED, EntryType.DETACHED]
    task_key: str | None = None
    discussion: str | None = None


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
    | AttributeFacts
    | MovedFacts
    | WarningFacts
    | AttachmentFacts
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
    EntryType.ACCEPTANCE: NoFacts,
    # Части итога — свободный текст, заголовок выведен из «решено».
    EntryType.CONCLUSION: NoFacts,
    EntryType.NOTE: NoFacts,
    EntryType.CREATED: NoFacts,
    EntryType.STATUS_CHANGED: StatusChangedFacts,
    EntryType.SECTION_CHANGED: SectionChangedFacts,
    EntryType.FIELD_CHANGED: FieldChangedFacts,
    EntryType.ASSIGNEE_CHANGED: AssigneeChangedFacts,
    EntryType.LINK_ADDED: LinkFacts,
    EntryType.LINK_REMOVED: LinkFacts,
    EntryType.MOVED: MovedFacts,
    EntryType.WARNING: WarningFacts,
    EntryType.ATTACHED: AttachmentFacts,
    EntryType.DETACHED: AttachmentFacts,
    # Номер итога, с которым закрыто, — в нагрузке; в описи он стоит строкой выше.
    EntryType.CLOSED: NoFacts,
    EntryType.ATTRIBUTE_CREATED: AttributeFacts,
    EntryType.ATTRIBUTE_CHANGED: AttributeFacts,
    EntryType.ATTRIBUTE_REMOVED: AttributeFacts,
    # Причина — свободный текст и остаётся в записи, в опись ехать нечему.
    EntryType.ARCHIVED: NoFacts,
    EntryType.RESTORED: NoFacts,
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

    `action_id` — признак одного действия (TRK-118, `app/db/models/entry.py`): записи
    одного вызова несут одно значение, разных вызовов — разные. `None` у записей,
    подшитых до появления этого поля.
    """

    no: int
    type: EntryType
    author: Author
    created_at: datetime
    title: str
    facts: EntryFacts
    action_id: uuid.UUID | None


# --- Ссылки -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskRef:
    """Ссылка на задачу: `TRK-7`. Ключ уже канонизирован."""

    key: str


@dataclass(frozen=True, slots=True)
class EntryRef:
    """Ссылка на запись задачи: `TRK-42#12`. Ключ уже канонизирован."""

    key: str
    no: int


@dataclass(frozen=True, slots=True)
class ProjectEntryRef:
    """Ссылка на запись дела проекта: `TRK#7`. Ключ проекта уже канонизирован."""

    key: str
    no: int


@dataclass(frozen=True, slots=True)
class AreaEntryRef:
    """Ссылка на запись дела области: `TRK/promotion#3`. Обе части канонизированы."""

    project_key: str
    area_key: str
    no: int

    @property
    def key(self) -> str:
        """Адрес области — та часть ссылки, что стоит перед номером."""
        return format_area_address(self.project_key, self.area_key)


@dataclass(frozen=True, slots=True)
class DiscussionRef:
    """Ссылка на обсуждение: `TRK~7`. Ключ проекта уже канонизирован."""

    project_key: str
    number: int

    @property
    def key(self) -> str:
        """Адрес обсуждения."""
        return format_discussion_address(self.project_key, self.number)


@dataclass(frozen=True, slots=True)
class DiscussionEntryRef:
    """Ссылка на запись дела обсуждения: `TRK~7#3`. Ключ проекта уже канонизирован."""

    project_key: str
    number: int
    no: int

    @property
    def key(self) -> str:
        """Адрес обсуждения — та часть ссылки, что стоит перед номером записи."""
        return format_discussion_address(self.project_key, self.number)


type TrackerRef = (
    TaskRef | EntryRef | ProjectEntryRef | AreaEntryRef | DiscussionRef | DiscussionEntryRef
)
"""Ссылка внутрь трекера: её существование проверяет сценарий."""


def parse_ref(ref: str) -> TrackerRef | None:
    """Разбирает ссылку. `None` означает «это URL со схемой» — его трекер не проверяет.

    Внешний адрес в `refs` — только URL со схемой (`https://…`, `file://…`, `mailto:…`):
    слово владельца, TRK-375#2. Строка, которая не ссылка трекера и не URL (`7`, `#7`,
    `запись 7`, `docs/x.md`), — `FieldProblem("not_a_reference")`: агент, написавший «7»
    вместо `TRK-42#7`, узнаёт об опечатке при подшивке, а не читатель дела потом.
    Проверка действует только на запись: записи неизменяемы, старые `refs` вида «7» лежат
    как лежали, а читающий код `parse_ref` не вызывает.

    Бросает `FieldProblem`, если строка выглядит ссылкой внутрь трекера, но номер
    записи в ней испорчен (`TRK-42#0`, `TRK-42#абв`, `TRK#007`): молча превратить такую
    строку в непроверяемый адрес значило бы потерять опечатку ровно там, где ссылка
    нужна надёжной.
    """
    head, separator, tail = ref.partition(ENTRY_REF_SEPARATOR)
    if is_discussion_address(head):
        # Обсуждение или его запись: голова — ключ проекта, тильда и номер. Строгая форма
        # (`is_discussion_address`), поэтому адрес с тильдой в пути (`https://x/~user#3`)
        # сюда не попадает и разбирается дальше как URL.
        address = parse_discussion_address(head)
        if not separator:
            return DiscussionRef(project_key=address.project_key, number=address.number)
        return DiscussionEntryRef(
            project_key=address.project_key,
            number=address.number,
            no=_entry_ref_no(ref, tail),
        )
    if separator and ADDRESS_SEPARATOR in head and tail.isascii() and tail.isdigit():
        # Запись области: голова — адрес с ключом проекта и ключом области по
        # шаблонам. Иначе это не ссылка трекера, и решает проверка на URL ниже.
        address = parse_area_address(head.strip())
        if _PROJECT_KEY_RE.match(address.project_key) and is_area_key(address.key):
            return AreaEntryRef(
                project_key=address.project_key,
                area_key=address.key,
                no=_entry_ref_no(ref, tail),
            )
        if _URL_RE.match(ref):
            return None
        raise FieldProblem("not_a_reference", ref=ref, expected=REF_SHAPE)
    try:
        key = normalize_task_key(head)
    except InvalidTaskKeyError:
        # Голова не ключ задачи. Запись проекта — голова по шаблону ключа проекта и
        # хвост из цифр; всё прочее должно быть URL со схемой. URL с якорем
        # (`https://example.com/a#b`) проходит: голова не ключ, а вся строка — URL.
        if separator and _PROJECT_KEY_RE.match(head.strip()) and tail.isascii() and tail.isdigit():
            return ProjectEntryRef(key=normalize_project_key(head), no=_entry_ref_no(ref, tail))
        if _URL_RE.match(ref):
            return None
        raise FieldProblem("not_a_reference", ref=ref, expected=REF_SHAPE) from None
    if not separator:
        return TaskRef(key=key)
    return EntryRef(key=key, no=_entry_ref_no(ref, tail))


def _entry_ref_no(ref: str, tail: str) -> int:
    """Номер записи из хвоста ссылки: число без ведущих нулей, с 1."""
    if not is_plain_number(tail) or int(tail) < FIRST_ENTRY_NUMBER:
        raise FieldProblem("malformed_entry_ref", ref=ref, expected=ENTRY_REF_SHAPE)
    return int(tail)


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
    tracker_refs: tuple[TrackerRef, ...] = ()


@dataclass(frozen=True, slots=True)
class EntryContext:
    """Всё о владельце, что нужно проверкам формы записи: ключ, проверки и повод.

    `closing` — не свойство задачи, а повод, по которому подшивают: та же сводка при
    закрытии обязана нести пятую часть, а посреди работы не смеет. Признак стоит здесь,
    а не в сценарии закрытия, потому что форма записи целиком живёт в домене: иначе у
    одного поля оказалось бы два разных отказа — `entry_fields_invalid` из `build_entry`
    для пустого значения и чужая ошибка сценария для отсутствующего (TRK-78).

    `discussion` — владелец не задача, а обсуждение (решение `TRK#51`, п. 2): тогда
    `task_key` держит его адрес (`TRK~7`), проверок нет, набор типов —
    `DISCUSSION_ENTRY_TYPES`, а `blocking` у вопроса не выбирают. Ключ один на обоих
    владельцев, потому что используется он одинаково: им названа запись в отказе и в
    выведенном заголовке ответа (`Answer to TRK~7#3`).
    """

    task_key: str
    checks: Sequence[str]
    closing: bool = False
    discussion: bool = False


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
    entry_type = _entry_type(
        type, problems, DISCUSSION_ENTRY_TYPES if context.discussion else TASK_ENTRY_TYPES
    )
    body_text = _entry_body(body, problems)
    tracker_refs, ref_strings = _entry_refs(refs, problems)

    payload_values: dict[str, Any] = {}
    entry_title = ""
    if entry_type is not None:
        payload_values = _PAYLOAD_BUILDERS[entry_type](dict(payload or {}), context, problems)
        # Тело не той формы уже получило своё замечание, второе о том же поле сбивало бы.
        if entry_type is EntryType.ANSWER and isinstance(body, str):
            _answer_reason(payload_values, body_text, problems)
        if entry_type is EntryType.VERDICT and isinstance(body, str):
            _verdict_evidence(payload_values, body_text, problems)
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


def build_project_entry(
    project_key: str,
    *,
    type: Any,
    title: Any,
    body: Any = "",
    refs: Any = (),
    supersedes: Any = None,
    replaceable: bool = True,
) -> EntryDraft:
    """Проверяет запись агента в дело проекта или области и приводит её к
    каноническому виду.

    Поля и их правила — те же функции, что у `build_entry`: заголовок, тело и ссылки
    записи проекта не отличаются от записи задачи ничем. Отличается набор типов
    (`PROJECT_ENTRY_TYPES`), поэтому ни контекста задачи, ни построителей нагрузки здесь
    не нужно. Тип задачи (`summary`, `question`, `attempt`, ...) — `not_allowed` со
    списком допустимых, служебный — `service_type`, как и в деле задачи.

    Нагрузка есть у записей знания — решения и заметки (`REPLACEABLE_ENTRY_TYPES`):
    `supersedes`, номера записей того же типа, которые новая заменяет (`CONCEPT.md`, 3.2;
    TRK#48). Ключ кладётся у них всегда, в том числе пустым: форма записи одна на все
    интерфейсы. У остальных типов `supersedes` отвергается, а не выбрасывается молча.
    Есть ли такие записи, того ли они типа и действуют ли, проверяет сценарий
    (`app/services/decisions.py`).

    `replaceable=False` — дело области (`CONCEPT.md`, 3.7): механики замены у него
    нет, и `supersedes` отвергается у любого типа, а нагрузка решения и заметки остаётся
    пустой, как у записей задачи. Первым параметром тогда приходит адрес области — им
    отказ называет, куда подшивали.
    """
    problems = FieldProblems()
    entry_type = _project_entry_type(type, problems)
    body_text = _entry_body(body, problems)
    tracker_refs, ref_strings = _entry_refs(refs, problems)
    entry_title = ""
    with problems.field("title"):
        entry_title = _entry_title(title)
    replaced: list[int] = []
    with problems.field(SUPERSEDES_FIELD):
        replaced = _superseded_numbers(supersedes)
    if replaced and not replaceable:
        problems.add(SUPERSEDES_FIELD, "not_allowed", allowed_in="project_case")
    elif replaced and entry_type is not None and entry_type not in REPLACEABLE_ENTRY_TYPES:
        problems.add(
            SUPERSEDES_FIELD,
            "not_allowed",
            allowed_for=sorted(item.value for item in REPLACEABLE_ENTRY_TYPES),
            got=entry_type.value,
        )
    problems.raise_as(EntryFieldsInvalidError, key=project_key)

    assert entry_type is not None  # иначе замечание о типе уже прервало бы работу
    payload: dict[str, Any] = {}
    if entry_type in REPLACEABLE_ENTRY_TYPES and replaceable:
        payload[SUPERSEDES_FIELD] = replaced
    return EntryDraft(
        type=entry_type,
        title=entry_title,
        body=body_text,
        payload=payload,
        refs=ref_strings,
        tracker_refs=tracker_refs,
    )


def superseded_numbers(payload: Mapping[str, Any]) -> list[int]:
    """Номера записей, которые заменяет решение или заметка дела проекта, — из нагрузки.

    Решение, подшитое до механизма замены, и заметка, подшитая до TRK-656, ключа не
    несут и не заменяют ничего. Одно определение на сценарий статуса и на чтение — как
    `answer_outcome` у ответа.
    """
    value = payload.get(SUPERSEDES_FIELD)
    return [item for item in value if isinstance(item, int)] if isinstance(value, list) else []


def _superseded_numbers(value: Any) -> list[int]:
    """Номера заменяемых записей: целые с 1, без повторов, по возрастанию.

    Порядок канонический, а не присланный: заменяемые записи — множество, и два
    порядка одного набора не должны давать двух разных записей.
    """
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise FieldProblem("not_a_list")
    numbers = sorted({_entry_number(item) for item in value})
    if len(numbers) > MAX_SUPERSEDES:
        raise FieldProblem("too_many", max=MAX_SUPERSEDES, got=len(numbers))
    return numbers


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


def answer_outcome(payload: Mapping[str, Any]) -> AnswerOutcome:
    """Чем закрыт вопрос — из нагрузки ответа.

    Ответ, подшитый до появления исхода, ключа `outcome` не несёт и читается как
    `answered`: тогда других исходов не было. Одно определение на опись, сценарий и
    чтение — иначе старый ответ звался бы где-то «ответом», а где-то «без исхода».
    """
    return AnswerOutcome(payload.get("outcome") or AnswerOutcome.ANSWERED)


def warning_title(checks: Sequence[WarningCheck]) -> str:
    """Заголовок предупреждения: какие проверки закрыты не целиком и чем.

    Английский, как у прочих служебных записей (`Status changed: backlog -> open`):
    выведенный заголовок — служебный слой. На языке человека его называет интерфейс по
    фактам (`WarningFacts`).
    """
    listed = ", ".join(f"check {item.check_no} {item.outcome.value}" for item in checks)
    return f"Closed not in full: {listed}"


def open_warning(index: Sequence[EntryHeading]) -> EntryHeading | None:
    """Открытое предупреждение задачи — строка описи `warning` без реакции после неё.

    Реакция — `acceptance` или `remark` (`WARNING_REACTIONS`), подшитая **после**
    предупреждения: замечание, оставленное по ходу работы, до закрытия, его не снимает.
    Предупреждение у задачи одно — закрытие бывает один раз, — поэтому достаточно
    дойти с конца описи до первой из двух записей.

    Питоновский двойник подзапроса `open_warning_count` (`app/db/repositories/entries.py`):
    карточка считает признак из описи, которую и так читает, поиск — запросом. Тест
    сверяет обе формы на одних данных.
    """
    for heading in reversed(index):
        if heading.type in WARNING_REACTIONS:
            return None
        if heading.type is EntryType.WARNING:
            return heading
    return None


def read_payload(entry_type: EntryType, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Нагрузка записи в том виде, в каком её отдают наружу, — одна на REST и на MCP.

    Записи неизменяемы, а форма нагрузки со временем растёт: ключ, которого у старой
    записи нет, при чтении получает значение, которое он имел тогда, и в базе ничего не
    переписывается. Правило стоит здесь, а не в схеме одного интерфейса: пока REST
    подставлял умолчание полем модели, а MCP отдавал нагрузку как лежит, агент и человек
    читали один и тот же ответ по-разному (TRK-563).

    Так читаются четыре типа. Ответ, подшитый до появления исходов (`question_no` и ничего
    более), читается как `answered` без заменившего вопроса (TRK-563). Решение и заметка
    без `supersedes` — запись задачи, запись области (TRK-555), решение проекта до
    замены (TRK-554) и заметка проекта до TRK-656 — ничего не заменяют. Правка раздела
    без `check_no` — любая, кроме точечной правки проверки — читается с `check_no: null`
    (TRK-565). Нагрузка остальных типов отдаётся как лежит: трекер всегда кладёт в неё
    все ключи, которые есть у модели чтения (сверка TRK-565); новый ключ в чужой нагрузке
    получает ветвь здесь же.
    """
    data = dict(payload)
    if entry_type is EntryType.ANSWER:
        data["outcome"] = answer_outcome(payload).value
        data.setdefault("replaced_by", None)
    elif entry_type in REPLACEABLE_ENTRY_TYPES:
        data.setdefault(SUPERSEDES_FIELD, [])
    elif entry_type is EntryType.SECTION_CHANGED:
        data.setdefault("check_no", None)
    return data


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


def _entry_type(
    value: Any, problems: FieldProblems, owned: frozenset[EntryType]
) -> EntryType | None:
    """Тип записи агента из набора владельца. Служебные, неизвестные и чужие владельцу
    отвергаются с допустимым списком.

    `None` означает «тип не разобрался»: замечание уже записано, и остальные проверки
    идут без него, чтобы клиент получил все замечания разом, а не одно про тип.
    """
    allowed = sorted(owned)
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
    if entry_type not in owned:
        # Тип агента, но не этого дела: итог — только в обсуждении, сводка и вердикт —
        # только в задаче.
        problems.add("type", "not_allowed", allowed=allowed, got=entry_type.value)
        return None
    return entry_type


def _project_entry_type(value: Any, problems: FieldProblems) -> EntryType | None:
    """Тип записи агента в деле проекта: `note`, `decision`, `finding`, `artifact`."""
    allowed = sorted(PROJECT_ENTRY_TYPES)
    try:
        entry_type = EntryType(value)
    except ValueError:
        problems.add("type", "not_allowed", allowed=allowed)
        return None
    if entry_type in SERVICE_ENTRY_TYPES:
        problems.add("type", "service_type", allowed=allowed, got=entry_type.value)
        return None
    if entry_type not in PROJECT_ENTRY_TYPES:
        problems.add("type", "not_allowed", allowed=allowed, got=entry_type.value)
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
) -> tuple[tuple[TrackerRef, ...], list[str]]:
    """Разбирает ссылки: трекерные отдельно для проверки существования, все — строками."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        problems.add("refs", "not_a_list")
        return (), []

    parsed: list[TrackerRef] = []
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


def _format_ref(target: TrackerRef) -> str:
    if isinstance(target, EntryRef | ProjectEntryRef | AreaEntryRef | DiscussionEntryRef):
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
    """У `decision`, `attempt`, `finding`, `artifact`, `remark`, `acceptance` и `note`
    нагрузки нет."""
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
    """Адресаты и признак `blocking`. Существование адресатов проверяет сценарий.

    У вопроса обсуждения признак не выбирают (решение `TRK#51`, п. 2): любой вопрос
    обсуждения держит привязанные задачи. Присланный `blocking` отвергается, а не
    выбрасывается молча, и в нагрузку трекер кладёт `blocking: true` сам — так нагрузка
    вопроса одной формы в любом деле и говорит правду: без ответа работа не идёт.
    """
    allowed = ("addressees",) if context.discussion else ("addressees", "blocking")
    _reject_extra(raw, allowed, problems)
    payload: dict[str, Any] = {}
    with problems.field("addressees"):
        payload["addressees"] = _addressees(raw.get("addressees"))
    if context.discussion:
        payload["blocking"] = True
        return payload
    with problems.field("blocking"):
        blocking = raw.get("blocking")
        if not isinstance(blocking, bool):
            # Обязателен и без значения по умолчанию: «можно ли продолжать без ответа»
            # знает только спрашивающий, а угаданное значение решает за него.
            raise FieldProblem("required" if blocking is None else "not_a_boolean")
        payload["blocking"] = blocking
    return payload


def _conclusion_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Части итога обсуждения, все непустые: «решено», «заменено», «открыто».

    Правила части — те же, что у сводки (`_summary_part`): «ничего» — законное значение,
    пустота — нет. Ссылки на записи, из которых следует строка итога, пишет автор в
    тексте и в `refs`; трекер текст не читает, как и `unmeasured`.
    """
    _reject_extra(raw, CONCLUSION_PARTS, problems)
    payload: dict[str, Any] = {}
    for part in CONCLUSION_PARTS:
        with problems.field(part):
            payload[part] = _summary_part(raw.get(part))
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
    """Номер вопроса той же задачи, исход и заменивший вопрос.

    Здесь только форма: что `question_no` и `replaced_by` указывают на вопросы этой
    задачи и что снимаемый вопрос ещё без ответа, проверяет сценарий — ему нужна база.
    Исход без значения — `answered`: прежние вызовы ответа его не присылают и не должны
    меняться. `outcome` и `replaced_by` кладутся в нагрузку всегда, в том числе
    пустыми, — по той же причине, что `task` у резолюции: форма записи одна на все
    интерфейсы.
    """
    _reject_extra(raw, ("question_no", "outcome", "replaced_by"), problems)
    payload: dict[str, Any] = {}
    with problems.field("question_no"):
        payload["question_no"] = _entry_number(raw.get("question_no"))

    outcome: AnswerOutcome | None = None
    with problems.field("outcome"):
        value = raw.get("outcome")
        try:
            outcome = AnswerOutcome.ANSWERED if value is None else AnswerOutcome(value)
        except ValueError:
            raise FieldProblem(
                "not_allowed", allowed=[item.value for item in AnswerOutcome]
            ) from None
        payload["outcome"] = outcome.value

    with problems.field("replaced_by"):
        payload["replaced_by"] = _replacement_no(
            raw.get("replaced_by"), outcome, payload.get("question_no")
        )
    return payload


def _replacement_no(value: Any, outcome: AnswerOutcome | None, question_no: Any) -> int | None:
    """Номер заменившего вопроса: обязателен при `replaced` и не принимается при остальных.

    Правило пары «исход — адрес» то же, что у `task` резолюции (`_continuation_key`).
    Сверх него — порядок: заменивший вопрос задан **после** снимаемого. Это отсекает
    и замену вопроса самим собой, и замену на более ранний — тот уже стоял в деле, когда
    задавали снимаемый, и ничем его заменить не мог. Что под номером именно вопрос этой
    задачи, проверяет сценарий.
    """
    if outcome is None:
        return None
    if outcome is not OUTCOME_WITH_REPLACEMENT:
        if value is not None:
            raise FieldProblem(
                "not_allowed", required_for=OUTCOME_WITH_REPLACEMENT.value, got=outcome.value
            )
        return None
    if value is None:
        raise FieldProblem("required", required_for=OUTCOME_WITH_REPLACEMENT.value)
    number = _entry_number(value)
    if isinstance(question_no, int) and number <= question_no:
        raise FieldProblem("not_after_question", question_no=question_no, got=number)
    return number


def _answer_reason(payload: Mapping[str, Any], body: str, problems: FieldProblems) -> None:
    """Причина снятия или замены — тело записи, и оно обязательно.

    Проверка стоит отдельно от `_answer_payload`, потому что тело не нагрузка: его
    форму проверяет `_entry_body`, а здесь только правило «у исхода без ответа по
    существу тело непусто». Замечание идёт полем `body` — чинить агенту именно его.
    """
    outcome = payload.get("outcome")
    if outcome in CLOSING_WITHOUT_ANSWER and not body:
        problems.add("body", "required", required_for=outcome)


def _verdict_evidence(payload: Mapping[str, Any], body: str, problems: FieldProblems) -> None:
    """Доказательство у `partial` и `unverifiable` обязательно — тело записи вердикта.

    Устроено как `_answer_reason`: тело не нагрузка, его форму проверяет `_entry_body`, а
    здесь только правило «у исхода не целиком тело непусто». Замечание идёт полем
    `evidence` — под этим именем доказательство принимают `add_verdict` и закрытие, и
    чинить агенту именно его; у `POST /tasks/{key}/entries` это тело записи вердикта.
    """
    outcome = payload.get("outcome")
    if outcome in INCOMPLETE_OUTCOMES and not body:
        problems.add("evidence", "required", required_for=outcome)


def _verdict_payload(
    raw: dict[str, Any], context: EntryContext, problems: FieldProblems
) -> dict[str, Any]:
    """Номер обзорной проверки в пределах списка задачи и исход из `VerdictOutcome`."""
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
    EntryType.ACCEPTANCE: _no_payload,
    EntryType.CONCLUSION: _conclusion_payload,
    EntryType.NOTE: _no_payload,
}

#: Откуда берётся заголовок у типов, которые его не принимают. Строка уезжает в
#: подробности отказа: клиент, приславший заголовок, должен понять, чем его заменили.
_TITLE_SOURCES: dict[EntryType, str] = {
    EntryType.SUMMARY: "done",
    EntryType.ANSWER: "question_no, outcome, replaced_by",
    EntryType.VERDICT: "check_no, outcome",
    EntryType.RESOLUTION: "remark_no, outcome",
    EntryType.CONCLUSION: "decided",
}


def _derive_title(entry_type: EntryType, payload: dict[str, Any], context: EntryContext) -> str:
    """Заголовок типов, которые его не принимают.

    Выведенные заголовки — служебный слой, поэтому английские, как и у записей трекера
    (`Status changed: backlog -> open`). Исключение — сводка: её заголовок это первая
    строка текста автора, то есть пользовательские данные.
    """
    if entry_type is EntryType.SUMMARY:
        return summary_title(payload["done"])
    if entry_type is EntryType.CONCLUSION:
        # Как у сводки: опись — хронология, и итог в ней говорит о решённом.
        return summary_title(payload["decided"])
    if entry_type is EntryType.ANSWER:
        # Исход назван в описи: снятый вопрос иначе выглядел бы там отвеченным, и
        # преемник читал бы тело записи, чтобы узнать, что ответа не было.
        title = f"Answer to {format_entry_ref(context.task_key, payload['question_no'])}"
        outcome = answer_outcome(payload)
        if outcome is AnswerOutcome.WITHDRAWN:
            return f"{title}: withdrawn"
        if outcome is OUTCOME_WITH_REPLACEMENT:
            replacement = format_entry_ref(context.task_key, payload["replaced_by"])
            return f"{title}: replaced by {replacement}"
        return title
    if entry_type is EntryType.VERDICT:
        return f"Verdict on check {payload['check_no']}: {payload['outcome']}"
    if entry_type is EntryType.RESOLUTION:
        remark = format_entry_ref(context.task_key, payload["remark_no"])
        return f"Resolution of {remark}: {payload['outcome']}"
    raise AssertionError(f"Entry type {entry_type.value} carries its own title")
