"""Домен комментариев без базы: текст и разбор упоминаний.

Главное здесь — границы упоминания. На них держится вся адресность обсуждения: цепочек
ответов в проекте нет, и `@ключ` — единственная связь реплики с тем, кому она
адресована. Ошибка в разборе означает не «некрасивый результат», а уведомление,
ушедшее не тому актору.
"""

import pytest

from app.domain.comments import (
    COMMENT_EXCERPT_LENGTH,
    MAX_COMMENT_LENGTH,
    extract_mentions,
    mentions_differ,
    validate_body,
)
from app.domain.errors import InvalidCommentBodyError
from app.domain.fields import SYSTEM_FIELD_KEYS


def test_the_body_keeps_its_text_and_loses_the_edges() -> None:
    """Пробелы по краям снимаются: иначе тот же текст считался бы правкой."""
    assert validate_body("  Починил выдачу ключей\n") == "Починил выдачу ключей"


def test_an_empty_body_is_refused() -> None:
    """Пустая реплика выглядела бы сбоем интерфейса, а уведомление о ней — ничем."""
    with pytest.raises(InvalidCommentBodyError) as error:
        validate_body("   \n  ")
    assert error.value.details["reason"] == "required"


def test_a_body_over_the_limit_is_refused() -> None:
    """Потолок назван прямо: текст уезжает в каждое событие и в каждое уведомление."""
    with pytest.raises(InvalidCommentBodyError) as error:
        validate_body("a" * (MAX_COMMENT_LENGTH + 1))
    assert error.value.details["reason"] == "too_long"
    assert error.value.details["max"] == MAX_COMMENT_LENGTH


def test_mentions_are_collected_in_order_without_repeats() -> None:
    """Порядок сохраняется, повтор отбрасывается: поле адресатов воспроизводимо."""
    body = "@alice посмотри, @release_bot уже собрал. @alice это про твой пункт"
    assert extract_mentions(body) == ["alice", "release_bot"]


def test_an_email_like_string_is_not_a_mention() -> None:
    """Левая граница обязательна: `alice@bob` — адрес, а не упоминание `bob`."""
    assert extract_mentions("напиши на alice@bob про сборку") == []


def test_a_longer_word_after_the_key_is_not_a_mention_of_the_shorter_one() -> None:
    """Правая граница обязательна: без неё `@aliceX` адресовало бы реплику `alice`.

    Это и есть молчаливый сбой, ради которого граница поставлена: уведомление ушло бы
    актору, которого в тексте нет, а автор был бы уверен, что написал кому-то другому.
    """
    assert extract_mentions("@aliceX проверь") == []


def test_a_key_that_cannot_belong_to_an_actor_is_not_a_mention() -> None:
    """Разбор идёт по шаблону ключа актора: `@Alice` и `@1bot` ключами быть не могут."""
    assert extract_mentions("@Alice и @1bot тут ни при чём") == []


def test_mentions_differ_by_membership_not_by_order() -> None:
    """Состав адресатов значим, порядок — нет: перестановка не меняет, кому слать."""
    assert not mentions_differ(["alice", "bob"], ["bob", "alice"])
    assert mentions_differ(["alice"], ["alice", "bob"])


def test_the_journal_field_name_cannot_be_taken_by_a_custom_field() -> None:
    """`comments` — имя поля в журнале, поэтому кастомное поле с таким ключом запрещено.

    Иначе запись истории читалась бы двусмысленно: то ли это обсуждение, то ли чьё-то
    поле с тем же ключом.
    """
    assert "comments" in SYSTEM_FIELD_KEYS


def test_the_excerpt_is_shorter_than_the_body_limit() -> None:
    """Отрывок для журнала обязан быть много короче самого комментария.

    Проверка выглядит тавтологией, но стережёт реальную ошибку: подняв потолок отрывка
    до потолка текста, историю задачи снова сделали бы неподъёмной.
    """
    assert COMMENT_EXCERPT_LENGTH < MAX_COMMENT_LENGTH
