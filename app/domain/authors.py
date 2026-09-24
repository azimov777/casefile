"""Автор действия: род и подпись.

Одна структура на весь трекер. Ею подписываются записи дела, переходы, связи и строки
реестров; она же приезжает сервисам из аутентификации вместе с набором токена
(`app/services/auth.py`). Заводить второй способ сказать «кто это сделал» нельзя: два
описания автора разъедутся, и запись дела начнёт называть того же агента иначе, чем
карточка проекта, который он завёл.

Чистый Python: ни ORM, ни HTTP. Поэтому функции принимают род и имя, а не объект
участника — модель живёт в `db`, а `domain` про неё не знает.

## Почему подпись отдельно от участника

Агенты бывают постоянные и временные (`CONCEPT.md`, 3.1). У постоянного есть участник в
реестре, у временного — только метка из заголовка `X-Actor-Label`. Общее у них ровно
одно: строка, которой подписано действие. Она и лежит в `Author.signature`, а есть ли за
ней строка в реестре — вопрос, на который отвечает `Actor.participant`, и только там, где
это действительно нужно (адресовать вопрос можно лишь участнику).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import InvalidActorLabelError

#: Метка временного агента живёт в одном пространстве имён с именами участников: обе
#: строки попадают в одно и то же поле подписи, и разные правила написания превратили бы
#: `release_bot` и `Release-Bot` в двух разных на вид авторов одного и того же действия.
ACTOR_LABEL_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{1,63}$"
_ACTOR_LABEL_RE = re.compile(ACTOR_LABEL_PATTERN)

#: Заголовок, которым временный агент называет свою метку.
ACTOR_LABEL_HEADER = "X-Actor-Label"


class AuthorKind(StrEnum):
    """Кто именно сделал действие.

    `tracker` — сам трекер: этим родом подписаны служебные записи дела и строки,
    заведённые командой первичной инициализации. У него нет подписи, потому что
    называть себя по имени ему незачем: трекер в установке один.
    """

    AGENT = "agent"
    HUMAN = "human"
    TRACKER = "tracker"


@dataclass(frozen=True, slots=True)
class Author:
    """Род и подпись. Неизменяемая: автор записанного действия не переписывается.

    Инвариант проверяется в конструкторе, а не соглашением в голове: `tracker` без
    подписи и все остальные — с подписью. Нарушение — ошибка программиста, поэтому
    `ValueError`, а не доменная ошибка с кодом: до пользователя такое состояние дойти
    не может, а до разработчика обязано дойти сразу.
    """

    kind: AuthorKind
    signature: str | None = None

    def __post_init__(self) -> None:
        if self.kind is AuthorKind.TRACKER:
            if self.signature is not None:
                raise ValueError("Tracker author has no signature")
        elif not self.signature:
            raise ValueError(f"Author of kind {self.kind.value} requires a signature")


#: Автор служебного действия. Один на процесс: у него нет состояния.
TRACKER = Author(kind=AuthorKind.TRACKER)


def participant_author(kind: str, name: str) -> Author:
    """Автор-участник: род берётся из рода участника, подпись — из его имени.

    Значения `ParticipantKind` и `AuthorKind` совпадают намеренно (`human`, `agent`):
    род автора — это и есть род участника, и таблица перевода между двумя списками
    была бы местом, где они однажды разойдутся.
    """
    return Author(kind=AuthorKind(kind), signature=name)


def label_author(label: str) -> Author:
    """Автор-временный агент: род всегда `agent`, подпись — проверенная метка.

    Род зашит, а не берётся из запроса: метку предъявляет тот, кто пришёл с общим
    агентским токеном, и другого рода у такого запроса быть не может.
    """
    return Author(kind=AuthorKind.AGENT, signature=validate_actor_label(label))


def normalize_actor_label(label: str) -> str:
    """Канонический вид метки: без пробелов по краям, в нижнем регистре."""
    return label.strip().lower()


def validate_actor_label(label: str) -> str:
    """Проверяет метку и возвращает канонический вид.

    Метка не проверяется на совпадение с именем участника, и это осознанно: общий
    агентский токен по своей природе доверенный, а лишний запрос в реестр стоял бы на
    каждом вызове временного агента. Следствие названо в `docs/notes/api.md`.
    """
    normalized = normalize_actor_label(label)
    if not _ACTOR_LABEL_RE.match(normalized):
        raise InvalidActorLabelError(
            details={
                "header": ACTOR_LABEL_HEADER,
                "label": label,
                "reason": "pattern_mismatch",
                "pattern": ACTOR_LABEL_PATTERN,
            },
        )
    return normalized
