"""Обсуждение: адрес, статусы, чей ход, части итога (решение проекта `TRK#51`).

Обсуждение — переписка человека и агентов по одному узкому вопросу, от ответа на который
зависит работа. Сущность проекта, рядом с областью, но не задача и не область: у него
своё дело, к нему **привязываются** задачи, которые зависят от его итога, а вопрос без
ответа в нём держит вход этих задач в работу (`TRK#51`, пункты 1–4).

## Адрес

Номер обсуждения считается внутри проекта, как номер задачи, а адрес — ключ проекта и
номер через тильду: `TRK~7`, запись — `TRK~7#3`. Тильды нет ни в ключе проекта, ни в
ключе задачи (`TRK-7`), ни в адресе области (`TRK/promotion`), поэтому четыре формы
ссылки не путаются ни в `refs`, ни в пути запроса. Адресация мягкая, как у задачи:
`trk~7` находит `TRK~7`, а `TRK~07` и `TRK~0` — опечатки, которые отвергаются формой.

## Конечно

`open` → `closed`, и обратно не бывает: закрытое заморожено, уточнение — новое
обсуждение со ссылкой на прежнее (`TRK#51`, пункты 1 и 7).

## Чей ход

Признак вычисляется, а не хранится (`TRK#51`, п. 4): `human` — есть вопрос без ответа;
`agent` — вопросов без ответа нет, но после последнего итога есть ответ или запись
человека; иначе — пусто. Определение одно и живёт запросом
(`app/db/repositories/discussions.py`, `turn_of`): им читаются и карточка, и список, и
отбор, поэтому второй формы на Python здесь нет.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import InvalidDiscussionAddressError
from app.domain.projects import PROJECT_KEY_PATTERN, normalize_project_key
from app.domain.tasks import ENTRY_REF_SEPARATOR, is_plain_number

#: Разделитель адреса обсуждения: `TRK~7`.
DISCUSSION_SEPARATOR = "~"

#: Форма адреса в подробностях отказа: по ней агент чинит запрос.
DISCUSSION_ADDRESS_SHAPE = f"<PROJECT>{DISCUSSION_SEPARATOR}<number>"

#: Номер первого обсуждения в проекте.
FIRST_DISCUSSION_NUMBER = 1

#: Название — одна строка: это сам узкий вопрос, им обсуждение видно в списках. Предел тот
#: же, что у заголовка записи: название и есть заголовок первой записи дела.
MAX_DISCUSSION_TITLE_LENGTH = 255

#: Сколько задач привязывает одно действие заведения. Привязывают только задачи, которые
#: зависят от итога (`TRK#51`, п. 3); список длиннее — это уже не узкий вопрос.
MAX_TASKS_ON_CREATE = 20

_PROJECT_KEY_RE = re.compile(PROJECT_KEY_PATTERN)


class DiscussionStatus(StrEnum):
    """Статус обсуждения: открыто или закрыто. Закрытое не открывается снова."""

    OPEN = "open"
    CLOSED = "closed"


class DiscussionTurn(StrEnum):
    """Чей ход в обсуждении (`TRK#51`, п. 4); отсутствие значения — «ничей».

    `human` — в деле есть вопрос без ответа. `agent` — вопросов без ответа нет, но после
    последнего итога есть ответ или запись человека: агенту читать её и писать итог.
    """

    HUMAN = "human"
    AGENT = "agent"


class DiscussionOrder(StrEnum):
    """Порядок списка обсуждений: входящей — от старых, истории — от свежих.

    Те же два вопроса человека, что у выдачи вопросов (`QuestionOrder`): дольше всех ждёт
    то, что заведено первым, а в истории ищут недавнее.
    """

    OLDEST = "oldest"
    NEWEST = "newest"


#: Части итога в порядке чтения: что решено, что заменено, что открыто (`TRK#51`, п. 2).
#: Все непустые — «ничего» законное значение части, пустота — нет: итог без «открыто»
#: читался бы так, будто открытого не осталось.
CONCLUSION_PARTS: tuple[str, ...] = ("decided", "superseded", "open")


@dataclass(frozen=True, slots=True)
class DiscussionAddress:
    """Адрес обсуждения: ключ проекта в верхнем регистре и номер внутри проекта."""

    project_key: str
    number: int

    def __str__(self) -> str:
        return format_discussion_address(self.project_key, self.number)


def format_discussion_address(project_key: str, number: int) -> str:
    """Адрес обсуждения из ключа проекта и номера: `TRK~7`."""
    return f"{project_key}{DISCUSSION_SEPARATOR}{number}"


def is_discussion_address(value: str) -> bool:
    """Похожа ли строка на адрес обсуждения: голова — ключ проекта, хвост — номер.

    Без отказа: так разбор ссылки решает, ссылка ли это на обсуждение, или строка
    другой формы (`https://example.com/~user`), которую разберут дальше.
    """
    project_key, separator, number = value.strip().partition(DISCUSSION_SEPARATOR)
    return (
        bool(separator)
        and _PROJECT_KEY_RE.match(project_key) is not None
        and is_plain_number(number)
        and int(number) >= FIRST_DISCUSSION_NUMBER
    )


def parse_discussion_address(value: str) -> DiscussionAddress:
    """Разбирает адрес: `trk~7` → `TRK~7`; не по форме — `invalid_discussion_address`.

    Адресация мягкая по регистру и строгая по форме, как у ключа задачи: `TRK~07`, `TRK~0`
    и `TRK-7` не адреса обсуждения, и молча искать по ним нечего.
    """
    if not is_discussion_address(value):
        raise InvalidDiscussionAddressError(
            details={"key": value, "expected": DISCUSSION_ADDRESS_SHAPE}
        )
    project_key, _, number = value.strip().partition(DISCUSSION_SEPARATOR)
    return DiscussionAddress(project_key=normalize_project_key(project_key), number=int(number))


def format_discussion_entry_ref(address: str, no: int) -> str:
    """Ссылка на запись дела обсуждения: `TRK~7#3`."""
    return f"{address}{ENTRY_REF_SEPARATOR}{no}"
