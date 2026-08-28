"""Доски, колонки, спринты и шкала порядка карточек.

Чистый Python: ни ORM, ни HTTP. Здесь описано то, что одинаково верно для REST, MCP и
фоновых процессов, — поэтому проверки живут тут, а не в схемах запросов.

## Доска ничего не отбирает сама

Источник задач доски — сохранённый фильтр (`app/domain/search.py` и задача 12), а не
собственный набор условий. Второй способ описать отбор разошёлся бы с языком запросов
на первом же краевом случае, и одна и та же доска показывала бы разное во фронте и в
автодействии. Доска добавляет к фильтру ровно две вещи: разбиение по колонкам (набор
статусов) и порядок карточек.

## Колонка — это набор статусов, а не статус

Колонка «В работе» может собирать `in_progress`, `in_review` и `testing`: доска
показывает процесс крупнее, чем он записан в воркфлоу. Обратное запрещено — один статус
не может попасть в две колонки одной доски, иначе карточка показалась бы дважды, и
вопрос «в какой она колонке» перестал бы иметь единственный ответ.

Колонка без статусов запрещена отдельно: пустой набор в фильтре означает «не
фильтровать», и такая колонка молча показала бы все задачи доски.

## Порядок карточек: у каждой задачи позиция есть всегда

Ранг хранится отдельной строкой (`issue_ranks`) и есть далеко не у всех задач: доска
отбирает задачи фильтром, и новая задача попадает на неё, ничего об этом не зная.
Соблазн отсортировать «ранжированные, потом остальные по времени создания» (`NULLS
LAST`) ошибочен: в таком порядке «поставить карточку в самый конец» становится
недостижимым — ранжированная задача не может оказаться после неранжированной.

Поэтому позиция вычислима у **любой** задачи: либо явный ранг, либо виртуальная
позиция, выведенная из времени создания (`virtual_position`). Обе — целые одной шкалы,
поэтому вставка «между этими двумя» всегда сводится к обычной арифметике
`app/domain/ranking.py` и меняет одну строку.

Шкала выбрана так, что между задачами, созданными с разницей в микросекунду, помещается
`POSITION_STEP` позиций. Совпасть виртуальные позиции могут только у задач с одинаковым
`created_at` — то есть созданных одной транзакцией (`now()` — время её начала). Этот
случай разбирается перенумерацией доски, как исчерпание зазора в чеклисте.

## Спринт принадлежит доске, а задача — не более чем одному спринту

`issues.sprint_id` — обычная колонка задачи, как и `project_id`, и по той же причине:
множественное членство немедленно породило бы вопрос «в каком спринте задача горит», а
любой ответ на него был бы произволом.

Из этого следует ограничение, которое надо знать: спринт не проверяет, попадает ли
задача в область доски. Область задаёт фильтр, а фильтр динамический — задача,
подходящая сегодня, завтра может не подойти. Проверка на запись создавала бы видимость
согласованности, которой нет; завершение спринта при этом всё равно найдёт задачу, куда
бы её ни увёл фильтр.
"""

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from app.core.errors import AppError
from app.domain.errors import InvalidBoardError, InvalidSprintError
from app.domain.ranking import POSITION_STEP

#: Название доски и колонки — одна строка: они живут в заголовке экрана и в шапке
#: колонки, где перевод строки просто ломает вёрстку.
MAX_BOARD_NAME_LENGTH = 255
MAX_COLUMN_NAME_LENGTH = 255
MAX_SPRINT_NAME_LENGTH = 255

#: Потолок описания доски — тот же, что у задачи и проекта: описание уезжает в каждый
#: ответ и в каждое событие.
MAX_BOARD_DESCRIPTION_LENGTH = 65_536

#: Цель спринта — абзац, а не документ: она показывается в шапке доски целиком.
MAX_SPRINT_GOAL_LENGTH = 4096

#: Потолок числа колонок. Ограничение неочевидное, поэтому названо прямо: колонки
#: приезжают в карточке доски целиком, без пагинации, и доска из сотни колонок — это
#: не доска, а таблица.
MAX_BOARD_COLUMNS = 20

#: Потолок числа статусов в одной колонке. Набор уезжает в каждый ответ с доской и
#: превращается в условие `status: a, b, c` при сборке колонки.
MAX_COLUMN_STATUSES = 50

#: Множитель виртуальной шкалы. Виртуальная позиция — это микросекунды эпохи, умноженные
#: на шаг: так между двумя задачами, созданными с разницей в микросекунду, помещается
#: ровно столько же вставок, сколько между двумя явно проранжированными соседями.
#:
#: Верхняя граница проверена: микросекунд эпохи сейчас около 1.8e15, умножение на 1024
#: даёт 1.8e18 при потолке `bigint` 9.2e18 — запаса хватает примерно до 2200 года.
RANK_SCALE = POSITION_STEP

#: Начало отсчёта виртуальной шкалы. Совпадает с эпохой Unix, чтобы то же число можно
#: было получить в SQL (`extract(epoch from created_at)`), не заводя второй константы.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


class SprintState(StrEnum):
    """Состояние спринта.

    Перечисление, а не редактируемый справочник, — в отличие от статусов задач: набор
    состояний спринта одинаков во всей установке и процесса команды не описывает.
    Переходы между ними односторонние: `planned → active → completed`. Возврата из
    `completed` нет намеренно — завершение спринта уже увело незакрытые задачи, и
    «отменить» его значило бы восстанавливать состояние, которого никто не записывал.
    """

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"


class UnfinishedPolicy(StrEnum):
    """Куда девать незакрытые задачи при завершении спринта.

    Решение принимает вызывающий, а не система: «перенести в следующий спринт» и
    «вернуть в бэклог» — разные способы работать, и выбор за командой. Значения по
    умолчанию нет — молчаливый выбор одного из них однажды растащил бы чужой спринт.
    """

    BACKLOG = "backlog"
    SPRINT = "sprint"


def virtual_position(created_at: datetime) -> int:
    """Позиция задачи, у которой явного ранга нет.

    Микросекунды эпохи, умноженные на шаг шкалы. Считается целочисленно, а не через
    `datetime.timestamp()`: тот возвращает `float`, а микросекунд эпохи уже
    шестнадцать значащих цифр — двойная точность начинает их терять, и две соседние
    задачи получили бы одну позицию.

    То же число обязан давать SQL (`app/db/repositories/boards.py`), иначе порядок в
    выдаче разойдётся с порядком, из которого сценарий считал новую позицию. Совпадение
    стережёт тест `test_the_virtual_position_matches_the_one_computed_in_sql`.
    """
    micros = (created_at.astimezone(UTC) - _EPOCH) // _MICROSECOND
    return micros * RANK_SCALE


def validate_board_name(name: str) -> str:
    """Проверяет название доски и возвращает канонический вид."""
    return _validate_line(
        name, field="name", max_length=MAX_BOARD_NAME_LENGTH, error=InvalidBoardError
    )


def validate_board_description(description: str) -> str:
    """Проверяет описание доски. Пустая строка допустима и означает «описания нет»."""
    if len(description) > MAX_BOARD_DESCRIPTION_LENGTH:
        raise InvalidBoardError(
            details={
                "field": "description",
                "reason": "too_long",
                "max": MAX_BOARD_DESCRIPTION_LENGTH,
                "got": len(description),
            },
        )
    return description.strip()


def validate_column_name(name: str) -> str:
    """Проверяет название колонки."""
    return _validate_line(
        name, field="name", max_length=MAX_COLUMN_NAME_LENGTH, error=InvalidBoardError
    )


def validate_wip_limit(limit: int | None) -> int | None:
    """Лимит задач в работе: положительное число или `None`.

    Ноль отвергается, а не считается «запретить колонку»: колонка, в которую нельзя
    положить ни одной карточки, — это отсутствующая колонка, и выражать её лимитом
    значило бы завести второй способ сказать то же самое.
    """
    if limit is None:
        return None
    if limit < 1:
        raise InvalidBoardError(
            details={"field": "wip_limit", "reason": "must_be_positive", "got": limit},
        )
    return limit


def ensure_column_count(count: int) -> None:
    """Итоговое число колонок доски не больше потолка."""
    if count > MAX_BOARD_COLUMNS:
        raise InvalidBoardError(
            details={
                "field": "columns",
                "reason": "too_many",
                "max": MAX_BOARD_COLUMNS,
                "got": count,
            },
        )


def ensure_column_capacity(count: int) -> None:
    """Отклоняет добавление колонки сверх потолка. `count` — сколько их уже есть."""
    ensure_column_count(count + 1)


def ensure_column_statuses(count: int) -> None:
    """Колонка обязана иметь хотя бы один статус и не больше потолка.

    Пустой набор запрещён не из аккуратности: в фильтре пустой список значений означает
    «не фильтровать», поэтому колонка без статусов молча показала бы все задачи доски.
    """
    if count == 0:
        raise InvalidBoardError(details={"field": "statuses", "reason": "required"})
    if count > MAX_COLUMN_STATUSES:
        raise InvalidBoardError(
            details={
                "field": "statuses",
                "reason": "too_many",
                "max": MAX_COLUMN_STATUSES,
                "got": count,
            },
        )


def validate_sprint_name(name: str) -> str:
    """Проверяет название спринта."""
    return _validate_line(
        name, field="name", max_length=MAX_SPRINT_NAME_LENGTH, error=InvalidSprintError
    )


def validate_sprint_goal(goal: str) -> str:
    """Проверяет цель спринта. Пустая строка допустима и означает «цель не записана»."""
    if len(goal) > MAX_SPRINT_GOAL_LENGTH:
        raise InvalidSprintError(
            details={
                "field": "goal",
                "reason": "too_long",
                "max": MAX_SPRINT_GOAL_LENGTH,
                "got": len(goal),
            },
        )
    return goal.strip()


def validate_sprint_period(start_date: date | None, end_date: date | None) -> None:
    """Период спринта не вывернут наизнанку. Обе даты необязательны.

    Календарные даты, а не моменты времени, — как у проекта и по той же причине:
    спринт не начинается в 14:37, а хранимое время заставило бы клиента его придумывать.
    Совпадение дат допустимо: однодневный спринт — законный план.
    """
    if start_date is None or end_date is None:
        return
    if end_date < start_date:
        raise InvalidSprintError(
            details={
                "field": "end_date",
                "reason": "before_start",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )


def _validate_line(
    value: str,
    *,
    field: str,
    max_length: int,
    error: type[AppError],
) -> str:
    """Однострочное название: непустое, без переносов, не длиннее потолка.

    Одно правило на доску, колонку и спринт: все три показываются строкой в заголовке,
    и три копии проверки разошлись бы обработкой возврата каретки.
    """
    normalized = value.strip()
    if not normalized:
        raise error(details={"field": field, "reason": "required"})
    if "\n" in normalized or "\r" in normalized:
        raise error(details={"field": field, "reason": "multiline_not_allowed"})
    if len(normalized) > max_length:
        raise error(
            details={
                "field": field,
                "reason": "too_long",
                "max": max_length,
                "got": len(normalized),
            },
        )
    return normalized
