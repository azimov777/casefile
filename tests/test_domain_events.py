"""Словарь событий и правило выбора типа: чистая логика, без базы.

Проверяется главное свойство словаря — он один. Действия для проверки прав задаёт
задача 05, события — задача 06, и разъехаться им нельзя: действие без события означает
изменение, которое молча не дойдёт до автоматики и уведомлений.
"""

import re

import pytest

from app.domain.events import (
    ACTION_EVENTS,
    EventType,
    changed_fields,
    decode_changes,
    encode_changes,
    event_type_for,
)
from app.domain.issues import IssueChange, IssueField

#: Действия, которые сценарии задач передают в `apply_issue_changes` и `ensure_allowed`,
#: плюс действия над окружением задачи: связями (задача 08), обсуждением и чеклистом
#: (задача 09), проектами и портфелями (задача 10). Саму строку задачи они не меняют,
#: но событие обязаны порождать так же.
#: Список записан руками: он должен ломаться при появлении нового действия без события,
#: а вычисленный из самого словаря — не сломался бы никогда.
MUTATING_ACTIONS = (
    "issue.create",
    "issue.update",
    "issue.transition",
    "issue.assign",
    "issue.follow",
    "issue.unfollow",
    "issue.tag",
    "issue.untag",
    "issue.delete",
    "link.create",
    "link.delete",
    "comment.create",
    "comment.update",
    "comment.delete",
    "checklist.item_add",
    "checklist.item_update",
    "checklist.item_check",
    "checklist.item_uncheck",
    "checklist.item_move",
    "checklist.item_remove",
    "issue.set_project",
    "project.create",
    "project.update",
    "project.archive",
    "project.restore",
    "portfolio.create",
    "portfolio.update",
    "portfolio.archive",
    "portfolio.restore",
)


def test_every_mutating_action_has_an_event_type() -> None:
    """Каждое действие, меняющее задачу, порождает событие известного типа."""
    assert set(MUTATING_ACTIONS) == set(ACTION_EVENTS)


def test_an_unknown_action_is_refused_loudly() -> None:
    """Незнакомое действие — ошибка, а не тихая подстановка `issue.updated`.

    Тихая подстановка дала бы событие неверного типа: подписчик на него не среагирует,
    и искать причину будут в подписчике, а не в забытой строке словаря.
    """
    with pytest.raises(ValueError, match=re.escape("issue.archive")):
        event_type_for("issue.archive")


def test_a_status_change_wins_over_the_generic_update() -> None:
    """Смена статуса выделяется в свой тип, даже если поменялось что-то ещё."""
    assert event_type_for("issue.update", ["summary"]) is EventType.ISSUE_UPDATED
    assert (
        event_type_for("issue.update", [IssueField.STATUS.value, "summary"])
        is EventType.ISSUE_STATUS_CHANGED
    )


def test_a_dedicated_action_keeps_its_own_type() -> None:
    """Назначение остаётся назначением; подписка и отписка — это изменение задачи."""
    assert event_type_for("issue.assign", [IssueField.ASSIGNEE.value]) is EventType.ISSUE_ASSIGNED
    assert event_type_for("issue.follow", [IssueField.FOLLOWERS.value]) is EventType.ISSUE_UPDATED
    assert event_type_for("issue.unfollow", [IssueField.FOLLOWERS.value]) is EventType.ISSUE_UPDATED


def test_changes_survive_the_round_trip() -> None:
    """Запись изменения переживает укладку в JSONB и обратное чтение без потерь."""
    changes = (
        IssueChange(field="status", before="open", after="in_progress"),
        IssueChange(field="assignee", before=None, after="alice"),
        IssueChange(field="TRK.severity", before=["minor"], after=["major", "minor"]),
    )

    encoded = encode_changes(changes)

    assert encoded[0] == {"field": "status", "before": "open", "after": "in_progress"}
    assert decode_changes(encoded) == changes
    assert changed_fields(changes) == ("status", "assignee", "TRK.severity")
