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

from app.domain.errors import (
    AreaLinkReasonRequiredError,
    AreaLinkReasonTooLongError,
    AreaLinkSelfError,
)

#: Вид связи — роль области-источника.
SEE_ALSO = "see_also"

#: Имя той же связи со стороны области-цели. В таблицу не попадает: вычисляется при чтении.
SEE_ALSO_FROM = "see_also_from"

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
