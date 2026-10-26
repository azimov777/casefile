"""Настройки установки (TRK-743): реестр, правила значений, чтение «база → окружение →
умолчание» без перезапуска, запись с проверкой, таблица вне архива."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.installation_setting import InstallationSetting
from app.domain.archive import EXCLUDED_TABLES
from app.domain.authors import Author, AuthorKind
from app.domain.errors import InstallationSettingInvalidError, InstallationSettingNotFoundError
from app.domain.installation_settings import SETTINGS, get_spec, parse_value
from app.services import installation_settings as service
from app.services.installation_settings import SettingSource

OWNER = Author(kind=AuthorKind.HUMAN, signature="owner")


async def count_rows(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(InstallationSetting)) or 0)


def test_the_registry_holds_exactly_the_seven_parameters() -> None:
    assert [spec.env_var for spec in SETTINGS] == [
        "TRACKER_SESSION_HOURS",
        "TRACKER_OAUTH_ACCESS_TTL",
        "TRACKER_MCP_PAGE_SIZE",
        "TRACKER_MCP_TEXT_LIMIT",
        "TRACKER_RELEASE_CHECK",
        "TRACKER_FILE_MAX_BYTES",
        "TRACKER_FILE_UNOPENED_DAYS",
    ]


def test_registry_defaults_and_minimums_match_the_settings_class() -> None:
    """Умолчание кода живёт в двух местах (реестр и `Settings`); тест их не даёт разойтись."""
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    for spec in SETTINGS:
        assert getattr(defaults, spec.name) == spec.default, spec.name


async def test_read_goes_database_then_environment_then_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRACKER_MCP_PAGE_SIZE", raising=False)
    resolved = await service.resolve_setting(db_session, "mcp_page_size")
    assert (resolved.value, resolved.source) == (25, SettingSource.DEFAULT)

    monkeypatch.setenv("TRACKER_MCP_PAGE_SIZE", "40")
    resolved = await service.resolve_setting(db_session, "mcp_page_size")
    assert (resolved.value, resolved.source) == (40, SettingSource.ENVIRONMENT)

    await service.set_setting(db_session, OWNER, "mcp_page_size", "10")
    assert await service.get_setting(db_session, "mcp_page_size") == 10

    # Смена значения действует на следующий вызов: `Settings` не пересоздаётся.
    await service.set_setting(db_session, OWNER, "mcp_page_size", "12")
    assert await service.get_setting(db_session, "mcp_page_size") == 12

    # Пустая строка возвращает настройку окружению; строка остаётся с автором.
    await service.set_setting(db_session, OWNER, "mcp_page_size", "")
    resolved = await service.resolve_setting(db_session, "mcp_page_size")
    assert (resolved.value, resolved.source) == (40, SettingSource.ENVIRONMENT)
    row = (await db_session.scalars(select(InstallationSetting))).one()
    assert (row.value, row.updated_by) == ("", OWNER)


async def test_read_sees_a_change_made_by_another_session_without_restart(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прямая запись в таблицу мимо сервиса видна следующему чтению: кеша нет."""
    monkeypatch.delenv("TRACKER_SESSION_HOURS", raising=False)
    assert await service.get_setting(db_session, "session_hours") == 168
    db_session.add(
        InstallationSetting(name="session_hours", value="24", updated_by_kind=AuthorKind.TRACKER)
    )
    await db_session.flush()
    assert await service.get_setting(db_session, "session_hours") == 24


async def test_types_are_read_as_integer_boolean_and_duration(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("TRACKER_RELEASE_CHECK", "TRACKER_OAUTH_ACCESS_TTL"):
        monkeypatch.delenv(var, raising=False)
    assert await service.get_setting(db_session, "release_check") is True
    await service.set_setting(db_session, OWNER, "release_check", "False")
    assert await service.get_setting(db_session, "release_check") is False

    from datetime import timedelta

    assert await service.get_setting(db_session, "oauth_access_ttl") == timedelta(days=30)
    await service.set_setting(db_session, OWNER, "oauth_access_ttl", "PT1H")
    assert await service.get_setting(db_session, "oauth_access_ttl") == timedelta(hours=1)
    await service.set_setting(db_session, OWNER, "oauth_access_ttl", "P1DT12H")
    assert await service.get_setting(db_session, "oauth_access_ttl") == timedelta(hours=36)


@pytest.mark.parametrize(
    ("name", "raw", "reason"),
    [
        ("mcp_text_limit", "100", "too_small"),
        ("oauth_access_ttl", "сорок", "not_a_duration"),
        ("oauth_access_ttl", "PT", "not_a_duration"),
        ("oauth_access_ttl", "PT1S", "too_small"),
        ("session_hours", "0", "too_small"),
        ("session_hours", "40.5", "not_an_integer"),
        ("mcp_page_size", "201", "too_large"),
        ("release_check", "может", "not_a_boolean"),
        ("file_unopened_days", "-3", "too_small"),
    ],
)
async def test_values_outside_the_rules_are_refused_and_nothing_is_stored(
    db_session: AsyncSession, name: str, raw: str, reason: str
) -> None:
    with pytest.raises(InstallationSettingInvalidError) as caught:
        await service.set_setting(db_session, OWNER, name, raw)
    assert caught.value.code == "installation_setting_invalid"
    assert caught.value.details["name"] == name
    assert caught.value.details["reason"] == reason
    assert await count_rows(db_session) == 0


async def test_an_unknown_name_is_refused_on_write_and_on_read(db_session: AsyncSession) -> None:
    with pytest.raises(InstallationSettingNotFoundError) as caught:
        await service.set_setting(db_session, OWNER, "tracker_password_hash", "x")
    assert caught.value.code == "installation_setting_not_found"
    with pytest.raises(InstallationSettingNotFoundError):
        await service.get_setting(db_session, "database_url")
    assert await count_rows(db_session) == 0


async def test_an_invalid_environment_value_falls_to_the_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRACKER_MCP_TEXT_LIMIT", "100")
    resolved = await service.resolve_setting(db_session, "mcp_text_limit")
    assert (resolved.value, resolved.source) == (2000, SettingSource.DEFAULT)


async def test_one_row_per_name_and_the_last_author_is_kept(db_session: AsyncSession) -> None:
    agent = Author(kind=AuthorKind.AGENT, signature="claude")
    await service.set_setting(db_session, OWNER, "file_max_bytes", "1048576")
    await service.set_setting(db_session, agent, "file_max_bytes", "2097152")
    row = (await db_session.scalars(select(InstallationSetting))).one()
    assert (row.value, row.updated_by) == ("2097152", agent)
    assert row.updated_at >= row.created_at


def test_parse_value_normalises_the_stored_form() -> None:
    assert parse_value(get_spec("release_check"), " YES ") is True
    assert parse_value(get_spec("session_hours"), "+24") == 24


def test_the_table_is_not_in_the_installation_archive() -> None:
    assert "installation_settings" in EXCLUDED_TABLES
