"""Связь области с областью `see_also`: вид, обратная сторона, причина и проверки.

Чистый Python: ни ORM, ни HTTP. Здесь то, что обязано быть одинаковым у таблицы
`area_links`, у сценариев и у ответов API.

Вид один, `see_also`, и называет роль области-источника: «кто работает здесь, читает ещё
там». Со стороны цели та же строка читается как `see_also_from` — так же, как `blocks` и
`blocked_by` у связей задач (`app/domain/links.py`); ставится только `see_also`. Связь
направленная и хранится одной строкой: `A → B` и `B → A` — две разные связи, у каждой своя
причина. Область — не задача: родителя у неё нет (TRK#55), граф никто не обходит, а
читается ровно один шаг от области, поэтому кольцо `A → B → A` не проверяется и не
запрещается — оно ничего не ломает.
"""

from enum import StrEnum

from app.domain.errors import (
    AreaLinkReasonRequiredError,
    AreaLinkReasonTooLongError,
    AreaLinkSelfError,
)

#: Вид связи — роль области-источника.
SEE_ALSO = "see_also"

#: Имя той же связи со стороны области-цели. В таблицу не попадает: вычисляется при чтении.
SEE_ALSO_FROM = "see_also_from"


class AreaLinkKind(StrEnum):
    """Вид связи областей **со стороны области**, чьё дело или чью карточку читают.

    В таблицу попадает только `see_also`; `see_also_from` — то же ребро, прочитанное из
    области-цели (в payload записи дела цели и в `link_kind` описи).
    """

    SEE_ALSO = "see_also"
    SEE_ALSO_FROM = "see_also_from"


#: Заголовок записи о связи в деле области-источника: другая сторона названа фразой с
#: подлежащим (как `other_side_phrase` у задач), «см. также» читалось бы двояко.
SEE_ALSO_PHRASE = "see also {other}"

#: То же в деле области-цели.
SEE_ALSO_FROM_PHRASE = "{other} lists this area in see also"


def see_also_phrase(kind: AreaLinkKind, other_address: str) -> str:
    """Связь словами для заголовка записи дела: `see also TRK/mcp` у источника,
    `TRK/mcp lists this area in see also` у цели."""
    template = SEE_ALSO_PHRASE if kind is AreaLinkKind.SEE_ALSO else SEE_ALSO_FROM_PHRASE
    return template.format(other=other_address)


#: Предел причины в знаках после обрезки пробелов; тот же предел держит
#: `ck_area_links_reason_length`.
MAX_AREA_LINK_REASON_LENGTH = 200


def validate_area_link_reason(reason: str | None) -> str:
    """Причина без пробелов по краям; пустая — `area_link_reason_required`, длиннее
    предела — `area_link_reason_too_long` (не обрезается)."""
    normalized = (reason or "").strip()
    if not normalized:
        raise AreaLinkReasonRequiredError()
    if len(normalized) > MAX_AREA_LINK_REASON_LENGTH:
        raise AreaLinkReasonTooLongError(
            details={"length": len(normalized), "max_length": MAX_AREA_LINK_REASON_LENGTH}
        )
    return normalized


def ensure_not_self(address: str, other_address: str) -> None:
    """Связь области с самой собой запрещена; сравниваются канонические адреса."""
    if address == other_address:
        raise AreaLinkSelfError(details={"address": address})
