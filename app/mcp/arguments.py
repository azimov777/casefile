"""Аргументы инструментов: общие аннотации и вложенные модели.

Описание аргумента — то, что модель читает о поле в `tools/list`: смысл, формат,
допустимые значения, как поле заполняется, на что влияет и каким кодом трекер откажет.
Всё, что относится к одному полю, стоит здесь, а не в описании инструмента.

## Правила текста метадаты

Решение владельца TRK-140#8: скила в проекте нет, и правила работы с одним инструментом
(выбор типа записи, части сводки, `unmeasured`, исходы замечания и прочие строки таблицы
TRK-141#15–#17) живут в его метадате. Прежнее правило «дисциплину в описания не
переносить» (TRK-33, TRK-129) этим отменено. Как писать сам текст — TRK-140#18:

- язык — английский: описания инструментов, аргументов, вложенных моделей, полей ответа
  и перечислений в схеме;
- без повелительного наклонения, советов «делай / не делай», оценок, объяснений
  «because» и примеров ситуаций; правило записывается определением или условием;
- примеры — только формата (`TRK-42`, `TRK-42#12`, UUID, язык запросов);
- одно правило — у одного инструмента или поля; свойство всех записей («видна в ленте и
  человеку») стоит один раз в `instructions`.

Всё это стерегут `tests/test_mcp_metadata.py` по живому `tools/list` и README (раздел
`## Tools`).

## Границы значений здесь не повторяются

У схем REST границы длины продублированы ради документации и раннего отсева
(`app/api/schemas/`). Здесь их нет намеренно: проверку делает домен, и его отказ приезжает
агенту предметным кодом со списком полей (`entry_fields_invalid`, `details.fields`), а не
сообщением pydantic о нарушенной схеме. Пустая часть сводки, отсечённая `min_length=1`,
дала бы агенту ошибку валидации аргументов вместо ответа «поле `blockers` обязательно» —
то есть отобрала бы у него имя поля, по которому он чинит вызов.

## Перечисления

Типы перечислений берутся из `app/mcp/enums.py`, а не из домена напрямую: схема домена
несёт русскую докстроку класса (шапка того модуля).
"""

from typing import Annotated

from pydantic import Field

from app.domain.idempotency import KEY_TTL
from app.domain.journal import JOURNAL_START, MAX_TASK_KEYS, MAX_WAIT_SECONDS
from app.mcp.enums import LinkKindSchema, ParticipantKindSchema

# --- Адресация ------------------------------------------------------------------------

TaskKeyArg = Annotated[
    str,
    Field(
        description=(
            "Task key `QUEUE-N`, case-insensitive. An unknown key is refused with `task_not_found`"
        ),
        examples=["TRK-42"],
    ),
]
QueueKeyArg = Annotated[
    str,
    Field(
        description=(
            "Queue key, case-insensitive. An unknown key is refused with `queue_not_found`"
        ),
        examples=["TRK"],
    ),
]
NewQueueKeyArg = Annotated[
    str,
    Field(
        description=(
            "Key of the new queue: a Latin letter followed by 1–15 Latin letters or digits "
            "(`invalid_queue_key` otherwise). It is stored upper-case, never changes and "
            "prefixes the key of every task of the queue. A key already taken, in any "
            "case, is refused with `queue_key_taken`"
        ),
        examples=["TRK"],
    ),
]
ParticipantNameArg = Annotated[
    str,
    Field(
        description=(
            "Participant name, case-insensitive. An unknown name is refused with "
            "`participant_not_found`"
        )
    ),
]
NewParticipantNameArg = Annotated[
    str,
    Field(
        description=(
            "Name of the new participant: a Latin letter followed by 1–63 Latin letters, "
            "digits or `_` (`invalid_participant_name` otherwise). It is stored "
            "lower-case and never changes: it signs the participant's entries. A name "
            "already taken, in any case, is refused with `participant_name_taken`"
        )
    ),
]

# --- Страницы -------------------------------------------------------------------------

LimitArg = Annotated[
    int | None,
    Field(description="Page size. Without a value, the installation's default page size"),
]
CursorArg = Annotated[
    str | None,
    Field(description="`next_cursor` of the previous page; without it, the first page"),
]

# --- Идемпотентность ------------------------------------------------------------------

IdempotencyKeyArg = Annotated[
    str | None,
    Field(
        description=(
            "Retry key chosen by the caller, e.g. a UUID. A repeat with the same key and "
            "the same arguments returns the first result and creates nothing; the same "
            "key with other arguments is refused with `idempotency_key_reused`. A key is "
            "bound to the caller's token and kept for "
            f"{int(KEY_TTL.total_seconds() // 3600)} hours"
        ),
        examples=["6b1f0c34-9b2e-4b0a-9a5f-3f1d6c8e0a11"],
    ),
]

# --- Связи ----------------------------------------------------------------------------

LinkKindArg = Annotated[
    LinkKindSchema,
    Field(
        description=(
            "Role of the task `key` toward the task `other`: "
            "`link(key='TRK-1', kind='blocks', other='TRK-7')` means TRK-1 blocks TRK-7, "
            "and the card of TRK-7 shows the same link as `blocked_by`"
        )
    ),
]
OtherTaskKeyArg = Annotated[
    str,
    Field(description="Key of the task on the other side of the link", examples=["TRK-7"]),
]

# --- Лента --------------------------------------------------------------------------

AfterArg = Annotated[
    int,
    Field(
        ge=JOURNAL_START,
        description=(
            "Journal sequence number `seq` to read after; `0` reads from the start. "
            "Entries are permanent: no `seq` is too old"
        ),
    ),
]
JournalTaskArg = Annotated[
    list[str] | str | None,
    Field(
        description=(
            f"Only entries of these tasks: one key or a list of at most {MAX_TASK_KEYS}. "
            "One wait covers all of them, and an entry in any of them ends it. More keys "
            "are refused with `journal_too_many_tasks`, an unknown key with "
            "`task_not_found`"
        ),
        examples=[["TRK-42", "TRK-43"]],
    ),
]
JournalQueueArg = Annotated[
    str | None,
    Field(description="Only entries of tasks in this queue", examples=["TRK"]),
]
TimeoutArg = Annotated[
    float,
    Field(
        description=(
            "Seconds to wait for the first matching entry when none is there yet, at most "
            f"{MAX_WAIT_SECONDS:.0f} (`journal_wait_too_long` beyond); `0` answers at "
            "once. An empty page after the wait means nothing happened and is not an error"
        )
    ),
]

# --- Реестры ------------------------------------------------------------------------

ParticipantKindArg = Annotated[ParticipantKindSchema, Field(description="Human or permanent agent")]
ParticipantDescriptionArg = Annotated[
    str,
    Field(
        description=(
            "Who the participant is: all that a reader of a case learns about the author "
            "of an entry"
        )
    ),
]
QueueTitleArg = Annotated[str, Field(description="Queue title")]
QueueDescriptionArg = Annotated[
    str,
    Field(description="Queue description in markdown: the shared context of all its tasks"),
]
# Отдельные аннотации для правки: `None` здесь означает «не передано». Осмысленного
# `null` ни у названия, ни у описания нет, поэтому третьего состояния и не нужно — в
# отличие от исполнителя задачи, который `null` как раз снимается.
QueueTitleChangeArg = Annotated[
    str | None, Field(description="New title; when left out, the title stays")
]
QueueDescriptionChangeArg = Annotated[
    str | None, Field(description="New description; when left out, the description stays")
]
