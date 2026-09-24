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
