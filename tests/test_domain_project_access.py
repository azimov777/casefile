"""Домен доступа агента к проектам без базы: три режима и неверный режим (TRK-746)."""

import uuid

import pytest

from app.domain.errors import ProjectAccessModeInvalidError, ProjectNotAllowedError
from app.domain.project_access import (
    UNRESTRICTED,
    ProjectAccess,
    ProjectAccessMode,
    is_open,
    parse_project_access_mode,
)

LISTED = uuid.uuid4()
OTHER = uuid.uuid4()
NEW = uuid.uuid4()


def test_all_opens_any_project_and_ignores_the_list() -> None:
    access = ProjectAccess.of("all", [LISTED])
    assert is_open(access, LISTED) and is_open(access, NEW)
    assert is_open(UNRESTRICTED, NEW)


def test_except_closes_the_listed_project_and_opens_the_rest() -> None:
    access = ProjectAccess.of("except", [LISTED])
    assert not is_open(access, LISTED)
    assert is_open(access, OTHER) and is_open(access, NEW)


def test_only_opens_the_listed_project_and_closes_a_new_one() -> None:
    access = ProjectAccess.of("only", [LISTED, OTHER])
    assert is_open(access, LISTED) and is_open(access, OTHER)
    assert not is_open(access, NEW)
    assert not is_open(ProjectAccess.of("only"), LISTED)


def test_an_unknown_mode_is_refused_with_the_allowed_ones() -> None:
    with pytest.raises(ProjectAccessModeInvalidError) as raised:
        ProjectAccess.of("some")
    assert raised.value.code == "project_access_mode_invalid"
    assert raised.value.status_code == 422
    assert raised.value.details == {"mode": "some", "allowed": ["all", "except", "only"]}
    with pytest.raises(ProjectAccessModeInvalidError):
        parse_project_access_mode("ALL")
    with pytest.raises(ProjectAccessModeInvalidError):
        ProjectAccess(mode="nope")  # type: ignore[arg-type]
    assert parse_project_access_mode("only") is ProjectAccessMode.ONLY


def test_a_closed_project_refusal_is_a_403_with_its_own_code() -> None:
    error = ProjectNotAllowedError(details={"project": "OPS"})
    assert (error.code, error.status_code) == ("project_not_allowed", 403)
