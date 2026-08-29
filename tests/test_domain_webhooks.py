"""Домен вебхуков без базы: подпись, области, проверка описания подписки.

Подпись проверяется здесь, а не в тестах доставки, намеренно: это единственное место
проекта, где ошибка не видна ни по коду ответа, ни в логе — получатель просто молча
отвергает вызовы, а мы считаем их отправленными.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.errors import InvalidWebhookSubscriptionError
from app.domain.notifications import EventAudience
from app.domain.webhooks import (
    DIRECT_EVENT_TYPE,
    SECRET_PREFIX,
    DeliveryStatus,
    WebhookScope,
    build_direct_payload,
    build_payload,
    generate_secret,
    masked_secret,
    matches_event_type,
    matches_scope,
    sign,
    signature_base,
    validate_subscription,
    verify,
)

MOMENT = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


def valid(**overrides: object) -> dict:
    """Описание подписки, проходящее проверку. Тесты меняют по одному полю."""
    return {
        "url": "https://ci.example.com/hooks/tracker",
        "scope": WebhookScope.ALL,
        "scope_key": None,
        "event_types": None,
        "secret": None,
    } | overrides


# --- Подпись ------------------------------------------------------------------------


def test_signature_covers_the_timestamp_as_well_as_the_body() -> None:
    """Подпись только по телу позволяла бы переиграть перехваченный вызов через сутки."""
    body = b'{"delivery":"1"}'

    assert sign("whsec_x" * 3, 1000, body) != sign("whsec_x" * 3, 2000, body)
    assert signature_base(1000, body) == b"1000." + body


def test_signature_names_its_algorithm() -> None:
    """Без имени смена алгоритма стала бы ломающим изменением без единого признака."""
    assert sign("whsec_secret_value", 1000, b"{}").startswith("sha256=")


def test_verify_accepts_only_the_matching_signature() -> None:
    secret = generate_secret()
    body = b'{"event":{"type":"issue.created"}}'
    signature = sign(secret, 1700000000, body)

    assert verify(secret, 1700000000, body, signature)
    assert not verify(secret, 1700000001, body, signature)
    assert not verify(generate_secret(), 1700000000, body, signature)
    assert not verify(secret, 1700000000, body + b" ", signature)


def test_generated_secret_is_recognisable() -> None:
    """Префикс нужен, чтобы секрет не приняли в логах получателя за что-то безобидное."""
    assert generate_secret().startswith(SECRET_PREFIX)


def test_masked_secret_shows_enough_to_tell_two_apart_and_not_enough_to_sign() -> None:
    """Начала в маске нет: у секрета, заданного вручную, префикса `whsec_` не бывает."""
    masked = masked_secret("already-known-shared-secret")

    assert masked == "…cret"
    assert not masked.startswith(SECRET_PREFIX)


# --- Описание подписки ---------------------------------------------------------------


def test_subscription_requires_a_key_for_a_target_scope() -> None:
    """Область без ключа отбирала бы весь поток, а выглядела бы настроенной на очередь."""
    with pytest.raises(InvalidWebhookSubscriptionError) as error:
        validate_subscription(**valid(scope=WebhookScope.QUEUE, scope_key=None))

    assert error.value.details["field"] == "scope_key"
    assert error.value.details["reason"] == "required"


def test_subscription_refuses_a_key_where_it_is_never_read() -> None:
    with pytest.raises(InvalidWebhookSubscriptionError) as error:
        validate_subscription(**valid(scope=WebhookScope.ALL, scope_key="TRK"))

    assert error.value.details["reason"] == "not_applicable"


@pytest.mark.parametrize("url", ["ftp://example.com/hook", "example.com/hook", "https://"])
def test_subscription_refuses_an_address_it_could_never_call(url: str) -> None:
    """Иначе подписка выглядит рабочей, а доставка не уйдёт никогда."""
    with pytest.raises(InvalidWebhookSubscriptionError) as error:
        validate_subscription(**valid(url=url))

    assert error.value.details["field"] == "url"


def test_subscription_refuses_an_unknown_event_type() -> None:
    """Опечатка дала бы подписку, которую невозможно отличить от исправной."""
    with pytest.raises(InvalidWebhookSubscriptionError) as error:
        validate_subscription(**valid(event_types=["issue.created", "issue.exploded"]))

    assert error.value.details["unknown"] == ["issue.exploded"]


def test_subscription_accepts_the_direct_call_type() -> None:
    """Подписка «только вызовы правил» иначе получала бы весь поток в придачу."""
    _, _, types, _ = validate_subscription(**valid(event_types=[DIRECT_EVENT_TYPE]))

    assert types == [DIRECT_EVENT_TYPE]


def test_subscription_generates_a_secret_when_none_is_given() -> None:
    _, _, _, secret = validate_subscription(**valid(secret=None))

    assert secret.startswith(SECRET_PREFIX)


def test_subscription_keeps_a_secret_that_is_already_wired_on_the_other_side() -> None:
    """Отвергать чужой секрет за форму значило бы запрещать подключение к существующему."""
    _, _, _, secret = validate_subscription(**valid(secret="already-known-shared-secret"))

    assert secret == "already-known-shared-secret"


def test_subscription_refuses_a_secret_too_short_to_sign_with() -> None:
    with pytest.raises(InvalidWebhookSubscriptionError) as error:
        validate_subscription(**valid(secret="short"))

    assert error.value.details["field"] == "secret"


# --- Отбор --------------------------------------------------------------------------


def test_scope_all_takes_everything() -> None:
    assert matches_scope(WebhookScope.ALL, None, EventAudience())


def test_queue_scope_compares_the_queue_of_the_event() -> None:
    audience = EventAudience(queue_key="TRK")

    assert matches_scope(WebhookScope.QUEUE, "TRK", audience)
    assert not matches_scope(WebhookScope.QUEUE, "OPS", audience)


def test_project_scope_matches_any_of_the_projects_in_the_event() -> None:
    """В наборе лежат и прежний проект, и новый: подписчик покинутого обязан узнать."""
    audience = EventAudience(project_keys=frozenset({"alpha", "beta"}))

    assert matches_scope(WebhookScope.PROJECT, "alpha", audience)
    assert matches_scope(WebhookScope.PROJECT, "beta", audience)
    assert not matches_scope(WebhookScope.PROJECT, "gamma", audience)


def test_empty_type_filter_means_every_type() -> None:
    """Иначе заведение подписки стало бы обрядом из двух шагов."""
    assert matches_event_type([], "issue.created")
    assert matches_event_type(["issue.created"], "issue.created")
    assert not matches_event_type(["issue.created"], "issue.updated")


# --- Полезная нагрузка ---------------------------------------------------------------


def test_payload_carries_keys_and_text_but_not_the_whole_issue() -> None:
    """Наружу уходит то, по чему получатель решает, а не дамп задачи со всеми полями."""
    delivery_id = str(uuid.uuid4())
    payload = {
        "issue": {
            "key": "TRK-7",
            "queue": "TRK",
            "summary": "Починить выдачу ключей",
            "description": "Очень длинный текст, которому наружу делать нечего",
            "values": {"TRK.severity": "critical"},
        },
        "fields": ["status"],
        "changes": [{"field": "status", "before": "TRK.open", "after": "TRK.done"}],
    }

    body = build_payload(
        delivery_id=delivery_id,
        event_id="11111111-1111-1111-1111-111111111111",
        event_type="issue.status_changed",
        object_type="issue",
        object_key="TRK-7",
        actor_key="alice",
        occurred_at=MOMENT,
        payload=payload,
        audience=EventAudience(issue_key="TRK-7", queue_key="TRK"),
    )

    assert body["delivery"] == delivery_id
    assert body["event"]["type"] == "issue.status_changed"
    assert body["event"]["actor"] == "alice"
    assert body["issue"] == "TRK-7"
    assert body["queue"] == "TRK"
    assert "status" in body["summary"]
    assert "description" not in str(body)
    assert "values" not in body


def test_direct_payload_has_the_same_shape_as_an_event_one() -> None:
    """Получатель обязан разбирать любой вызов одним и тем же кодом."""
    from_event = build_payload(
        delivery_id="1",
        event_id="2",
        event_type="issue.created",
        object_type="issue",
        object_key="TRK-7",
        actor_key="alice",
        occurred_at=MOMENT,
        payload={"issue": {"key": "TRK-7"}},
        audience=EventAudience(issue_key="TRK-7"),
    )
    direct = build_direct_payload(
        delivery_id="1",
        actor_key="system",
        occurred_at=MOMENT,
        object_type="issue",
        object_key="TRK-7",
        issue_key="TRK-7",
        body="Release is ready",
    )

    assert set(from_event) == set(direct)
    assert direct["event"]["id"] is None
    assert direct["event"]["type"] == DIRECT_EVENT_TYPE
    assert direct["summary"] == "Release is ready"


def test_delivery_status_has_no_separate_state_for_waiting_a_retry() -> None:
    """Момент следующей попытки лежит в `available_at`, и второй статус лишь раздвоил бы правду."""
    assert {item.value for item in DeliveryStatus} == {"pending", "delivered", "failed"}
