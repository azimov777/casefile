"""Домен уведомлений: адресация по нагрузке, текст, склейка, проверка подписки.

Всё здесь — чистые функции над словарями. База в этих тестах не нужна не из экономии:
если её присутствие когда-нибудь понадобится, значит адресация полезла читать состояние
на момент доставки — ровно то, что задача 14 запрещает.
"""

import pytest

from app.domain.errors import InvalidSubscriptionError
from app.domain.events import EventType
from app.domain.notifications import (
    MAX_TEXT_LENGTH,
    SubscriptionScope,
    audience_of,
    describe,
    digest_key,
    matches_event_type,
    validate_subscription,
)


def issue_snapshot(**overrides: object) -> dict:
    """Снимок задачи в том виде, в каком его кладёт в событие `app/services/events.py`."""
    snapshot = {
        "id": "11111111-1111-1111-1111-111111111111",
        "key": "TRK-7",
        "queue": "TRK",
        "status": "TRK.open",
        "summary": "Починить выдачу ключей",
        "author": "alice",
        "assignee": "bob",
        "followers": ["carol"],
        "project": None,
    }
    snapshot.update(overrides)
    return snapshot


class TestAudience:
    def test_an_issue_event_reaches_author_assignee_and_followers(self) -> None:
        audience = audience_of(EventType.ISSUE_UPDATED, {"issue": issue_snapshot()})

        assert audience.roles == {
            "alice": frozenset({SubscriptionScope.AUTHOR}),
            "bob": frozenset({SubscriptionScope.ASSIGNEE}),
            "carol": frozenset({SubscriptionScope.FOLLOWER}),
        }
        assert audience.issue_key == "TRK-7"
        assert audience.queue_key == "TRK"

    def test_one_actor_can_hold_several_roles_at_once(self) -> None:
        """Автор, назначивший задачу на себя, — и автор, и исполнитель.

        Подписке достаточно совпасть по любой из ролей, поэтому набор, а не одна роль:
        выключив «где я исполнитель», актор обязан продолжить получать события своих
        задач как автор.
        """
        audience = audience_of(
            EventType.ISSUE_ASSIGNED,
            {"issue": issue_snapshot(assignee="alice", followers=[])},
        )

        assert audience.roles == {
            "alice": frozenset({SubscriptionScope.AUTHOR, SubscriptionScope.ASSIGNEE}),
        }

    def test_a_comment_adds_the_mentioned_actors(self) -> None:
        audience = audience_of(
            EventType.COMMENT_CREATED,
            {
                "issue": issue_snapshot(),
                "comment": {"id": "c1", "author": "bob", "mentions": ["dave"], "body": "@dave?"},
                "previous": None,
            },
        )

        assert audience.roles["dave"] == frozenset({SubscriptionScope.MENTION})

    def test_editing_a_comment_notifies_only_the_newly_mentioned(self) -> None:
        """Правка комментария адресует разницу наборов, а не текущее поле целиком.

        Без вычитания прежних упоминаний исправление опечатки уведомляло бы заново
        всех, кого упомянули в первой редакции.
        """
        audience = audience_of(
            EventType.COMMENT_UPDATED,
            {
                "issue": issue_snapshot(),
                "comment": {"id": "c1", "author": "bob", "mentions": ["dave", "erin"]},
                "previous": {"body": "...", "mentions": ["dave"]},
            },
        )

        assert "erin" in audience.roles
        assert audience.roles.get("dave") is None or (
            SubscriptionScope.MENTION not in audience.roles["dave"]
        )

    def test_a_checklist_event_reaches_the_item_assignee(self) -> None:
        """У пункта свой исполнитель, и он может не совпадать с исполнителем задачи."""
        audience = audience_of(
            EventType.CHECKLIST_ITEM_CHECKED,
            {
                "issue": issue_snapshot(),
                "item": {"id": "i1", "text": "Прогнать тесты", "assignee": "dave"},
                "previous": None,
            },
        )

        assert audience.roles["dave"] == frozenset({SubscriptionScope.ASSIGNEE})

    def test_a_link_event_reaches_both_sides(self) -> None:
        audience = audience_of(
            EventType.LINK_CREATED,
            {
                "link": {"id": "l1", "type": "depends_on", "source": "TRK-7", "target": "TRK-9"},
                "issues": {
                    "source": issue_snapshot(),
                    "target": issue_snapshot(
                        key="TRK-9", author="dave", assignee=None, followers=[]
                    ),
                },
            },
        )

        assert {"alice", "bob", "carol", "dave"} <= set(audience.roles)
        assert audience.issue_key == "TRK-7"

    def test_a_project_event_reaches_lead_and_members(self) -> None:
        audience = audience_of(
            EventType.PROJECT_UPDATED,
            {
                "project": {"key": "alpha", "name": "Альфа", "lead": "alice", "members": ["bob"]},
                "fields": ["end_date"],
            },
        )

        assert audience.roles == {
            "alice": frozenset({SubscriptionScope.MEMBER}),
            "bob": frozenset({SubscriptionScope.MEMBER}),
        }
        assert audience.project_keys == frozenset({"alpha"})

    def test_moving_an_issue_between_projects_addresses_both(self) -> None:
        """Уход из проекта выглядит как обычная правка поля, и старый проект о ней узнаёт.

        Без прежнего ключа подписчик проекта, из которого задачу забрали, просто
        перестал бы получать по ней события — молча.
        """
        audience = audience_of(
            EventType.ISSUE_UPDATED,
            {
                "issue": issue_snapshot(project="beta"),
                "fields": ["project"],
                "changes": [{"field": "project", "before": "alpha", "after": "beta"}],
            },
        )

        assert audience.project_keys == frozenset({"alpha", "beta"})

    def test_a_bulk_status_transfer_has_no_issue_and_no_roles(self) -> None:
        """Массовый перенос — одно событие на всю операцию, а не сотня.

        Разворачивать его обратно в уведомление на каждую задачу нельзя: ради этого
        схлопывания событие и делалось таким.
        """
        audience = audience_of(
            EventType.STATUS_ISSUES_MOVED,
            {
                "status": {"from": "TRK.open", "to": "TRK.closed"},
                "queue": "TRK",
                "count": 2,
                "issues": ["TRK-7", "TRK-8"],
            },
        )

        assert audience.roles == {}
        assert audience.issue_key is None
        assert audience.queue_key == "TRK"

    def test_an_unknown_event_type_gives_an_empty_audience(self) -> None:
        """Неизвестный тип не роняет подписчика: он работает в воркере.

        Исключение здесь пометило бы событие недоставленным из-за типа, до которого
        этой механике вообще нет дела.
        """
        assert audience_of("weather.changed", {"whatever": True}).roles == {}


class TestDescribe:
    def test_a_status_change_names_both_ends(self) -> None:
        summary = describe(
            EventType.ISSUE_STATUS_CHANGED,
            {
                "issue": issue_snapshot(status="TRK.in_progress"),
                "fields": ["status"],
                "changes": [{"field": "status", "before": "TRK.open", "after": "TRK.in_progress"}],
            },
        )

        assert "TRK.open" in summary.body
        assert "TRK.in_progress" in summary.body
        assert summary.details["issue"] == "TRK-7"

    def test_the_text_carries_identifiers_for_programmatic_decisions(self) -> None:
        """Агент решает по `details`, а не разбором строки, которую завтра перепишут."""
        summary = describe(EventType.ISSUE_ASSIGNED, {"issue": issue_snapshot()})

        assert summary.details["assignee"] == "bob"
        assert summary.details["queue"] == "TRK"

    def test_a_long_text_is_clamped(self) -> None:
        summary = describe(
            EventType.ISSUE_CREATED,
            {"issue": issue_snapshot(summary="а" * 5000)},  # noqa: RUF001
        )

        assert len(summary.body) <= MAX_TEXT_LENGTH

    def test_an_unknown_event_type_still_says_what_happened(self) -> None:
        """Пустой текст был бы хуже неполного: по инбоксу нельзя было бы понять ничего."""
        summary = describe("weather.changed", {"issue": issue_snapshot()})

        assert "weather.changed" in summary.body
        assert "TRK-7" in summary.body


class TestDigestKey:
    def test_repeats_of_one_event_on_one_object_share_a_key(self) -> None:
        first = digest_key(EventType.ISSUE_UPDATED, "TRK-7")
        second = digest_key(EventType.ISSUE_UPDATED, "TRK-7")

        assert first == second

    def test_different_objects_and_types_do_not_merge(self) -> None:
        assert digest_key(EventType.ISSUE_UPDATED, "TRK-7") != digest_key(
            EventType.ISSUE_UPDATED, "TRK-8"
        )
        assert digest_key(EventType.ISSUE_UPDATED, "TRK-7") != digest_key(
            EventType.ISSUE_ASSIGNED, "TRK-7"
        )

    def test_each_comment_is_its_own_notification(self) -> None:
        """У комментария свой ключ объекта, поэтому новые реплики не склеиваются.

        Склеиваются только правки **одной** реплики — у них ключ объекта совпадает.
        """
        assert digest_key(EventType.COMMENT_CREATED, "TRK-7:c1") != digest_key(
            EventType.COMMENT_CREATED, "TRK-7:c2"
        )


class TestValidateSubscription:
    def test_a_target_scope_requires_a_key(self) -> None:
        with pytest.raises(InvalidSubscriptionError) as error:
            validate_subscription(SubscriptionScope.QUEUE, None, [])

        assert error.value.details["field"] == "scope_key"
        assert error.value.details["reason"] == "required"

    def test_a_role_scope_rejects_a_key(self) -> None:
        with pytest.raises(InvalidSubscriptionError) as error:
            validate_subscription(SubscriptionScope.ASSIGNEE, "TRK", [])

        assert error.value.details["reason"] == "not_applicable"

    def test_an_unknown_event_type_is_rejected(self) -> None:
        """Опечатка иначе дала бы подписку, неотличимую от исправной и никогда не срабатывающую."""
        with pytest.raises(InvalidSubscriptionError) as error:
            validate_subscription(SubscriptionScope.ALL, None, ["issue.updted"])

        assert error.value.details["unknown"] == ["issue.updted"]

    def test_types_are_normalised_and_deduplicated(self) -> None:
        _, types = validate_subscription(
            SubscriptionScope.ALL,
            None,
            [" issue.updated ", "issue.updated", "issue.created"],
        )

        assert types == ["issue.created", "issue.updated"]


class TestMatchesEventType:
    def test_an_empty_set_means_every_type(self) -> None:
        assert matches_event_type([], EventType.ISSUE_UPDATED)

    def test_a_listed_type_passes_and_others_do_not(self) -> None:
        assert matches_event_type(["issue.updated"], EventType.ISSUE_UPDATED)
        assert not matches_event_type(["issue.updated"], EventType.ISSUE_CREATED)
