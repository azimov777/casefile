"""Связи: типы, обратные стороны, канонический вид хранения. Чистая логика, без базы.

Главное свойство, которое здесь стерегут, — связь хранится один раз. Из него следует
всё остальное: у каждого типа есть обратная сторона, ровно одна сторона каждой пары
попадает в таблицу, а симметричный тип дополнительно упорядочивается по ключам. Стоит
одному из трёх утверждений перестать быть верным — уникальное ограничение перестанет
ловить дубликат, и связь молча запишется дважды.
"""

import pytest

from app.domain.errors import InvalidTreeDepthError
from app.domain.links import (
    DEFAULT_TREE_DEPTH,
    HIERARCHY_STORED_TYPE,
    INVERSE_TYPES,
    MAX_TREE_DEPTH,
    STORED_LINK_TYPES,
    LinkType,
    canonical_form,
    inverse,
    is_hierarchy,
    validate_tree_depth,
    visible_type,
)


def test_every_type_has_an_inverse_and_the_table_is_symmetric() -> None:
    """Таблица обратных сторон полна и обратима.

    Неполная таблица означала бы связь, видимую только с одной стороны, — то есть
    ровно то, ради чего связь и заводят.
    """
    assert set(INVERSE_TYPES) == set(LinkType)
    for link_type in LinkType:
        assert inverse(inverse(link_type)) is link_type


def test_exactly_one_side_of_every_pair_is_stored() -> None:
    """Из пары в таблицу попадает ровно одна сторона.

    Ноль означал бы тип, который негде хранить; два — что «A blocks B» и
    «B depends_on A» лягут разными строками, и дубликат пройдёт мимо ограничения.
    """
    for link_type in LinkType:
        pair = {link_type, inverse(link_type)}
        assert len(pair & STORED_LINK_TYPES) == 1


@pytest.mark.parametrize(
    ("requested", "stored", "swapped"),
    [
        (LinkType.DEPENDS_ON, LinkType.DEPENDS_ON, False),
        (LinkType.BLOCKS, LinkType.DEPENDS_ON, True),
        (LinkType.SUBTASK_OF, LinkType.SUBTASK_OF, False),
        (LinkType.PARENT_OF, LinkType.SUBTASK_OF, True),
        (LinkType.DUPLICATES, LinkType.DUPLICATES, False),
        (LinkType.DUPLICATED_BY, LinkType.DUPLICATES, True),
    ],
)
def test_an_asymmetric_type_collapses_to_one_direction(
    requested: LinkType,
    stored: LinkType,
    swapped: bool,
) -> None:
    """Обратная сторона приводится к прямой обменом задач местами."""
    form = canonical_form(requested, source_key="TRK-1", target_key="TRK-2")

    assert form.link_type is stored
    assert form.swapped is swapped


def test_a_symmetric_type_is_ordered_by_key() -> None:
    """`A relates B` и `B relates A` — одна строка, а не две.

    Уникальное ограничение на тройку тут бессильно: у симметричного типа обе записи
    отличаются только порядком колонок. Поэтому порядок задают ключи.
    """
    direct = canonical_form(LinkType.RELATES, source_key="TRK-1", target_key="TRK-2")
    reverse = canonical_form(LinkType.RELATES, source_key="TRK-2", target_key="TRK-1")

    assert (direct.link_type, direct.swapped) == (LinkType.RELATES, False)
    assert (reverse.link_type, reverse.swapped) == (LinkType.RELATES, True)


def test_each_side_reads_the_link_under_its_own_name() -> None:
    """Одна строка — два имени. Второе вычисляется, а не хранится."""
    assert visible_type(LinkType.DEPENDS_ON, from_source=True) is LinkType.DEPENDS_ON
    assert visible_type(LinkType.DEPENDS_ON, from_source=False) is LinkType.BLOCKS
    assert visible_type(LinkType.SUBTASK_OF, from_source=False) is LinkType.PARENT_OF
    # Симметричный тип называется одинаково с обеих сторон — на то он и симметричный.
    assert visible_type(LinkType.RELATES, from_source=False) is LinkType.RELATES


def test_only_the_parent_child_pair_is_hierarchical() -> None:
    """Иерархия — одна пара типов; эпик к типам связи отношения не имеет.

    Эпик — это тип задачи. Отдельная связь для него означала бы вторую иерархию с
    собственным родителем, собственными циклами и собственным деревом.
    """
    hierarchical = {link_type for link_type in LinkType if is_hierarchy(link_type)}

    assert hierarchical == {LinkType.SUBTASK_OF, LinkType.PARENT_OF}
    assert HIERARCHY_STORED_TYPE in STORED_LINK_TYPES


def test_tree_depth_defaults_and_refuses_values_out_of_range() -> None:
    """Выход за границы — ошибка, а не тихое срезание до потолка."""
    assert validate_tree_depth(None) == DEFAULT_TREE_DEPTH
    assert validate_tree_depth(1) == 1
    assert validate_tree_depth(MAX_TREE_DEPTH) == MAX_TREE_DEPTH

    for bad in (0, -1, MAX_TREE_DEPTH + 1):
        with pytest.raises(InvalidTreeDepthError) as failure:
            validate_tree_depth(bad)
        assert failure.value.details["max"] == MAX_TREE_DEPTH
