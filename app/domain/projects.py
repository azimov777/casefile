"""Проекты и портфели: ключи, состояние, период, прогресс, границы вложенности.

Чистый Python: ни ORM, ни HTTP. Здесь описано то, что одинаково верно для REST, MCP и
фоновых процессов, — поэтому проверки живут тут, а не в схемах запросов.

## Проект — не очередь, и это разные оси

Очередь отражает процесс команды и владеет задачей целиком: у задачи ровно одна очередь,
и её ключ (`TRK-123`) из очереди и собран. Проект отражает результат, ради которого
работают несколько команд, и собирает задачи **из разных очередей**. Поэтому связь с
проектом — отдельная необязательная колонка задачи, а не свойство её очереди.

Задача входит не более чем в один проект. Множественное членство немедленно порождает
вопрос «в прогресс какого проекта она засчитывается» — и любой ответ на него был бы
произволом.

## Состояние проекта не выводится из задач

`ProjectStatus` — самостоятельное поле, а не функция от статусов задач. Проект бывает
приостановлен при полностью закрытых задачах (ждём решения заказчика) и бывает «идёт»
при нулевом прогрессе. Выводить одно из другого значило бы отнять у планирования
возможность сказать то, чего в задачах не написано.

## Прогресс считается, а не хранится

`Progress` собирается из счётчиков задач по запросу. Колонка «процент готовности»,
которую кто-то обязан обновлять, расходится с реальностью в первую же неделю: задачу
закрыли из MCP, из автоматики, массовым переносом статуса — и каждое из этих мест
обязано было бы вспомнить про пересчёт.

Портфель агрегирует **по задачам**, а не по среднему от детей: портфель из проекта на
девятьсот задач и проекта на сто отвечает на вопрос «сколько работы под ним сделано», и
закрытый мелкий проект не должен двигать это число как крупный. Формула — в `aggregate`.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.core.errors import AppError
from app.domain.errors import InvalidPortfolioError, InvalidProjectError

#: Ключ проекта и портфеля: латиница в нижнем регистре, как ключи акторов, полей и
#: статусов. Верхний регистр отдан очередям (`TRK`), чтобы одно от другого отличалось
#: на глаз. Области действия у проекта нет — он надочередной, — поэтому точка в ключ
#: не входит и разбор ссылки (`app/domain/refs.py`) здесь не нужен.
PLANNING_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
MAX_PLANNING_KEY_LENGTH = 64

_PLANNING_KEY_RE = re.compile(PLANNING_KEY_PATTERN)

MAX_PLANNING_NAME_LENGTH = 255

#: Потолок описания — тот же, что у задачи: описание уезжает в каждый ответ и в каждое
#: событие, и мегабайтный текст сделал бы неподъёмными оба.
MAX_PLANNING_DESCRIPTION_LENGTH = 65_536

#: Потолок числа участников. Ограничение неочевидное, поэтому названо прямо: список
#: участников целиком приезжает в каждом ответе с проектом и в каждом событии о нём.
MAX_PLANNING_MEMBERS = 200

#: Предел вложенности портфелей при обходе. Ровно та же роль, что у
#: `MAX_HIERARCHY_DEPTH` в связях задач: отсутствие цикла — свойство графа целиком, в
#: схеме его не выразить, и проверка сценария на гонку двух одновременных запросов не
#: рассчитана. Ограничитель нужен, чтобы кольцо, если оно всё-таки возникнет, ломало
#: один запрос, а не крутило рекурсию вечно.
MAX_PORTFOLIO_DEPTH = 32


class ProjectStatus(StrEnum):
    """Состояние проекта или портфеля в планировании.

    Перечисление, а не редактируемый справочник, — в отличие от статусов задач. Причина
    та же, что у приоритета задачи: справочник статусов описывает **процесс команды**, и
    у каждой очереди он свой, а состояние проекта одинаково во всей установке и процесса
    не описывает. Набор закрыт, расширяется заменой одного ограничения CHECK.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    DONE = "done"


#: Состояние по умолчанию: у только что заведённого проекта работа ещё не началась.
DEFAULT_PROJECT_STATUS = ProjectStatus.NOT_STARTED


class PlanningKind(StrEnum):
    """Проект или портфель. Нужен там, где код общий для обоих.

    Значения совпадают с префиксами кодов ошибок (`project_not_found`,
    `portfolio_key_taken`) и с полем `kind` в составе портфеля, по которому клиент
    отличает вложенный портфель от проекта.
    """

    PROJECT = "project"
    PORTFOLIO = "portfolio"


#: Класс ошибки валидации по виду объекта: коды обязаны оставаться точными
#: (`invalid_project` против `invalid_portfolio`), а правила у них общие.
INVALID_ERRORS: dict[PlanningKind, type[AppError]] = {
    PlanningKind.PROJECT: InvalidProjectError,
    PlanningKind.PORTFOLIO: InvalidPortfolioError,
}


@dataclass(frozen=True, slots=True)
class Progress:
    """Готовность по задачам: сколько всего и сколько в статусах категории `done`.

    Счётчики лежат рядом с долей намеренно. Доля без них неинформативна и опасна: «0%»
    у проекта без единой задачи и «0%» у проекта из тысячи незакрытых — разные вещи, а
    выглядят одинаково. Клиент, которому нужен ровно процент, берёт `ratio`; клиент,
    которому нужно «есть ли вообще работа», смотрит на `total`.

    `ratio is None` означает «считать не по чему»: задач нет. Ноль здесь был бы ложью —
    он читается как «ничего не сделано», хотя делать было нечего.
    """

    total: int = 0
    done: int = 0

    def __post_init__(self) -> None:
        if self.total < 0 or self.done < 0:
            raise ValueError("Progress counters cannot be negative")
        if self.done > self.total:
            raise ValueError("Progress cannot have more done issues than total")

    @property
    def ratio(self) -> float | None:
        """Доля закрытых задач от нуля до единицы; `None` — задач нет."""
        if self.total == 0:
            return None
        return self.done / self.total


def aggregate(parts: Iterable[Progress]) -> Progress:
    """Складывает прогресс потомков портфеля **по задачам**, а не по среднему от них.

    Формула — `сумма done / сумма total`, поэтому портфель отвечает на вопрос «сколько
    работы под ним сделано». Среднее от детей отвечало бы на другой вопрос — «какая
    доля инициатив готова», — и на портфеле из проекта в девятьсот задач и проекта в сто
    дало бы 75% там, где сделано 55%.

    Выбор не косметический: у среднего пришлось бы отдельно решать, что делать с пустым
    проектом (он тянет среднее вниз, хотя работы в нём нет) и как взвешивать вложенный
    портфель против одиночного проекта. У суммы этих вопросов не возникает — пустой
    проект добавляет ноль к обоим счётчикам, а вложенность схлопывается сама.
    """
    total = 0
    done = 0
    for part in parts:
        total += part.total
        done += part.done
    return Progress(total=total, done=done)


def normalize_planning_key(key: str) -> str:
    """Канонический вид ключа: без пробелов по краям, в нижнем регистре.

    Адресация в проекте мягкая: `/api/v1/projects/Alpha` находит проект `alpha`.
    """
    return key.strip().lower()


def validate_planning_key(key: str, *, kind: PlanningKind, error: type[AppError]) -> str:
    """Проверяет ключ проекта или портфеля и возвращает канонический вид.

    Класс ошибки передаёт вызывающий, а не выбирает эта функция: коды
    `invalid_project_key` и `invalid_portfolio_key` — часть контракта, и склеивать их в
    один общий значило бы заставить клиента разбирать `details`, чтобы понять, что он
    прислал не так.
    """
    normalized = normalize_planning_key(key)
    if not _PLANNING_KEY_RE.match(normalized):
        raise error(
            details={
                "kind": kind.value,
                "key": key,
                "reason": "pattern_mismatch",
                "pattern": PLANNING_KEY_PATTERN,
            },
        )
    return normalized


def validate_planning_name(name: str, *, kind: PlanningKind) -> str:
    """Проверяет название и возвращает канонический вид.

    Пустое название отвергается, а не заменяется заглушкой: проект без названия
    нечитаем в любом списке, а придумать его за пользователя нечем. Многострочность
    запрещена по той же причине, что у названия задачи: строка живёт в списках и в
    карточках портфеля.
    """
    error = INVALID_ERRORS[kind]
    normalized = name.strip()
    if not normalized:
        raise error(details={"kind": kind.value, "field": "name", "reason": "required"})
    if "\n" in normalized or "\r" in normalized:
        raise error(
            details={"kind": kind.value, "field": "name", "reason": "multiline_not_allowed"},
        )
    if len(normalized) > MAX_PLANNING_NAME_LENGTH:
        raise error(
            details={
                "kind": kind.value,
                "field": "name",
                "reason": "too_long",
                "max": MAX_PLANNING_NAME_LENGTH,
                "got": len(normalized),
            },
        )
    return normalized


def validate_planning_description(description: str, *, kind: PlanningKind) -> str:
    """Проверяет описание. Пустая строка допустима и означает «описания нет».

    Пустая строка, а не `NULL`, — как у очереди, задачи и сохранённого фильтра: два
    способа выразить одно состояние неизбежно разъехались бы у клиентов.
    """
    if len(description) > MAX_PLANNING_DESCRIPTION_LENGTH:
        raise INVALID_ERRORS[kind](
            details={
                "kind": kind.value,
                "field": "description",
                "reason": "too_long",
                "max": MAX_PLANNING_DESCRIPTION_LENGTH,
                "got": len(description),
            },
        )
    return description.strip()


def validate_period(
    start_date: date | None,
    end_date: date | None,
    *,
    kind: PlanningKind,
) -> None:
    """Проверяет, что период не вывернут наизнанку. Обе даты необязательны.

    Даты здесь календарные (`date`), а не моменты времени, — в отличие от дедлайна
    задачи. Это осознанное расхождение: дедлайн наступает в конкретный момент и
    сравнивается с `now()` в правилах автоматики, а проект не начинается в 14:37.
    Хранить у него время значило бы вынудить клиента придумывать часы и минуты, а потом
    объяснять, почему проект, начатый «сегодня», в другом часовом поясе начался вчера.

    Совпадение дат допустимо: проект длиной в один день — законный план.
    """
    if start_date is None or end_date is None:
        return
    if end_date < start_date:
        raise INVALID_ERRORS[kind](
            details={
                "kind": kind.value,
                "field": "end_date",
                "reason": "before_start",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
