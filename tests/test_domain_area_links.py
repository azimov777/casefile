"""Домен связи областей `see_also` без базы: причина и связь с собой (TRK-732)."""

import pytest

from app.domain.area_links import (
    MAX_AREA_LINK_REASON_LENGTH,
    SEE_ALSO,
    SEE_ALSO_FROM,
    ensure_not_self,
    validate_area_link_reason,
)
from app.domain.errors import (
    AreaLinkReasonRequiredError,
    AreaLinkReasonTooLongError,
    AreaLinkSelfError,
)


def test_the_kind_names_the_role_of_the_source_area() -> None:
    assert (SEE_ALSO, SEE_ALSO_FROM) == ("see_also", "see_also_from")
    assert MAX_AREA_LINK_REASON_LENGTH == 200


@pytest.mark.parametrize("reason", ["", "   ", "\n\t ", None])
def test_a_blank_reason_is_refused(reason: str | None) -> None:
    with pytest.raises(AreaLinkReasonRequiredError) as caught:
        validate_area_link_reason(reason)
    assert caught.value.code == "area_link_reason_required"


def test_a_reason_of_201_characters_is_refused_and_200_pass() -> None:
    assert validate_area_link_reason("я" * 200) == "я" * 200
    with pytest.raises(AreaLinkReasonTooLongError) as caught:
        validate_area_link_reason("я" * 201)
    assert caught.value.code == "area_link_reason_too_long"
    assert caught.value.details == {"length": 201, "max_length": 200}


def test_spaces_around_the_reason_do_not_count() -> None:
    assert validate_area_link_reason("  " + "x" * 200 + "  ") == "x" * 200
    assert validate_area_link_reason("  почему  ") == "почему"


def test_an_area_cannot_be_linked_to_itself() -> None:
    ensure_not_self("TRK/db", "TRK/links")
    ensure_not_self("TRK/db", "OPS/db")
    with pytest.raises(AreaLinkSelfError) as caught:
        ensure_not_self("TRK/db", "TRK/db")
    assert caught.value.code == "area_link_self_not_allowed"
