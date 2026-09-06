"""Домен связей без базы: пары видов, канонический вид хранения, имя со стороны задачи."""

import pytest

from app.domain.errors import InvalidLinkKindError, LinkSelfError
from app.domain.links import (
    ACYCLIC_LINK_KINDS,
    BEHAVIOURAL_LINK_KINDS,
    INVERSE_KINDS,
    STORED_LINK_KINDS,
    SYMMETRIC_LINK_KINDS,
    LinkKind,
    canonical_form,
    changes_behaviour,
    ensure_not_self,
    inverse,
    is_acyclic,
    parse_link_kind,
    visible_kind,
)

# --- Пары видов ---------------------------------------------------------------------


def test_the_kinds_match_the_concept() -> None:
    """Ровно три вида связи, пять имён: правка перечисления — правка концепции."""
    assert set(LinkKind) == {
        LinkKind.PARENT,
        LinkKind.CHILD,
        LinkKind.BLOCKS,
        LinkKind.BLOCKED_BY,
        LinkKind.RELATES,
    }


def test_every_kind_has_an_inverse_and_it_is_an_involution() -> None:
    """Неполная таблица означала бы связь, которую видно только с одной стороны."""
    assert set(INVERSE_KINDS) == set(LinkKind)
    for kind in LinkKind:
        assert inverse(inverse(kind)) is kind


def test_exactly_one_side_of_every_pair_is_stored() -> None:
    """Обе стороны в таблице — это две строки на связь, то есть будущая рассинхронизация."""
    for kind in LinkKind:
        pair = {kind, inverse(kind)}
        assert len(pair & STORED_LINK_KINDS) == 1


def test_relates_is_the_only_symmetric_kind() -> None:
    assert set(SYMMETRIC_LINK_KINDS) == {LinkKind.RELATES}


def test_cycles_are_forbidden_in_hierarchy_and_blocking_only() -> None:
    """`relates` кольца не образует: он ничего не запрещает и ни от чего не зависит."""
    assert set(ACYCLIC_LINK_KINDS) == {LinkKind.PARENT, LinkKind.BLOCKS}
    assert is_acyclic(LinkKind.PARENT)
    assert is_acyclic(LinkKind.BLOCKS)
    assert not is_acyclic(LinkKind.RELATES)


def test_every_kind_is_classified_by_whether_it_changes_behaviour() -> None:
    """Новый вид связи обязан попасть в набор или быть из него исключён осознанно.

    От этого зависит, пройдёт ли связь с закрытой задачей: незачисленный вид молча
    оказался бы «ни на что не влияющим» и появился бы у закрытой задачи (`CONCEPT.md`,
    3.5).
    """
    assert BEHAVIOURAL_LINK_KINDS | {LinkKind.RELATES} == set(LinkKind)
    assert all(changes_behaviour(kind) for kind in BEHAVIOURAL_LINK_KINDS)
    assert not changes_behaviour(LinkKind.RELATES)


def test_both_sides_of_a_pair_are_classified_the_same() -> None:
    """Влияние на поведение — свойство связи, а не той стороны, с которой её назвали."""
    for kind in LinkKind:
        assert changes_behaviour(kind) is changes_behaviour(inverse(kind))


# --- Канонический вид ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected_kind", "expected_swap"),
    [
        (LinkKind.PARENT, LinkKind.PARENT, False),
        (LinkKind.CHILD, LinkKind.PARENT, True),
        (LinkKind.BLOCKS, LinkKind.BLOCKS, False),
        (LinkKind.BLOCKED_BY, LinkKind.BLOCKS, True),
    ],
)
def test_an_asymmetric_kind_is_stored_by_its_direct_side(
    kind: LinkKind,
    expected_kind: LinkKind,
    expected_swap: bool,
) -> None:
    canonical = canonical_form(kind, source_key="TRK-1", target_key="TRK-2")

    assert canonical.kind is expected_kind
    assert canonical.swapped is expected_swap


def test_a_symmetric_kind_is_ordered_by_key() -> None:
    """Без этого `A relates B` и `B relates A` легли бы двумя строками про одну связь."""
    straight = canonical_form(LinkKind.RELATES, source_key="TRK-1", target_key="TRK-2")
    reversed_ = canonical_form(LinkKind.RELATES, source_key="TRK-2", target_key="TRK-1")

    assert straight.kind is LinkKind.RELATES
    assert straight.swapped is False
    assert reversed_.swapped is True


def test_the_same_link_from_both_sides_lands_on_the_same_row() -> None:
    """Смысл канонизации: «A blocks B» и «B blocked_by A» — одна строка."""
    from_a = canonical_form(LinkKind.BLOCKS, source_key="TRK-1", target_key="TRK-2")
    from_b = canonical_form(LinkKind.BLOCKED_BY, source_key="TRK-2", target_key="TRK-1")

    assert from_a.kind is from_b.kind
    assert (from_a.swapped, from_b.swapped) == (False, True)


# --- Имя со стороны задачи ----------------------------------------------------------


@pytest.mark.parametrize("stored", sorted(STORED_LINK_KINDS))
def test_a_stored_link_is_named_by_its_kind_from_the_source(stored: LinkKind) -> None:
    assert visible_kind(stored, from_source=True) is stored
    assert visible_kind(stored, from_source=False) is inverse(stored)


def test_relates_looks_the_same_from_both_sides() -> None:
    """Обзорная проверка 5, доменная половина."""
    assert visible_kind(LinkKind.RELATES, from_source=True) is LinkKind.RELATES
    assert visible_kind(LinkKind.RELATES, from_source=False) is LinkKind.RELATES


# --- Разбор и запреты ---------------------------------------------------------------


def test_a_kind_is_parsed_from_a_string() -> None:
    assert parse_link_kind("blocked_by") is LinkKind.BLOCKED_BY
    assert parse_link_kind(LinkKind.RELATES) is LinkKind.RELATES


def test_an_unknown_kind_is_rejected_with_the_allowed_set() -> None:
    with pytest.raises(InvalidLinkKindError) as error:
        parse_link_kind("duplicates")

    assert error.value.code == "invalid_link_kind"
    assert error.value.details["allowed"] == [kind.value for kind in LinkKind]


def test_a_task_cannot_be_linked_to_itself() -> None:
    """Проверка нужна и симметричному виду: кольцом `relates` сам с собой не является."""
    ensure_not_self("TRK-1", "TRK-2")

    with pytest.raises(LinkSelfError) as error:
        ensure_not_self("TRK-1", "TRK-1")

    assert error.value.details["key"] == "TRK-1"
