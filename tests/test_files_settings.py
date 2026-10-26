"""Файловые параметры читаются из настроек при обращении (TRK-750, TRK~31#4).

Предел файла (`file_max_bytes`) и срок «не открывали» (`file_unopened_days`): запись в
таблицу перекрывает окружение со следующего вызова, пустое значение возвращает окружение
или умолчание. Три входа предела — сценарий ядра, часть формы REST и ссылка MCP.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.project import Project
from app.domain.authors import Author, AuthorKind
from app.domain.errors import FileTooLargeError
from app.mcp.runtime import SessionFactory
from app.services import files as service
from app.services import installation_settings as settings_service
from app.services.auth import Actor
from conftest import call
from test_files import upload as core_upload
from test_files_api import upload as rest_upload
from test_files_unopened import aged
from test_mcp_files import put, served

OWNER = Author(kind=AuthorKind.HUMAN, signature="owner")
TWO_MB = 2 * 1024 * 1024
pytestmark = pytest.mark.usefixtures("auth_client")


async def test_the_unopened_term_follows_the_table_on_the_next_read(
    db_session: AsyncSession, project: Project, main_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пустая таблица и 30 в окружении: 31 день — признак есть; 100 в таблице — признака нет."""
    monkeypatch.setenv("TRACKER_FILE_UNOPENED_DAYS", "30")
    card = await core_upload(db_session, main_actor, project)
    assert (await aged(db_session, main_actor, card, added_days=31)).unopened is True

    await settings_service.set_setting(db_session, OWNER, "file_unopened_days", "100")
    assert (await service.read_file(db_session, card.id, actor=main_actor)).unopened is False

    await settings_service.set_setting(db_session, OWNER, "file_unopened_days", "")
    assert (await service.read_file(db_session, card.id, actor=main_actor)).unopened is True


async def test_the_unopened_border_is_inclusive_at_the_table_value(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    await settings_service.set_setting(db_session, OWNER, "file_unopened_days", "90")
    card = await core_upload(db_session, main_actor, project)
    assert (await aged(db_session, main_actor, card, added_days=89)).unopened is False
    assert (await aged(db_session, main_actor, card, added_days=91)).unopened is True


async def test_the_size_limit_follows_the_table_in_the_core(
    db_session: AsyncSession, project: Project, main_actor: Actor
) -> None:
    """1048576 в таблице отклоняет 2 МБ; пустое значение возвращает умолчание 25 МБ."""
    await settings_service.set_setting(db_session, OWNER, "file_max_bytes", "1048576")
    with pytest.raises(FileTooLargeError) as refusal:
        await core_upload(db_session, main_actor, project, data=bytes(TWO_MB))
    assert refusal.value.details == {"size": TWO_MB, "max_bytes": 1048576}

    await settings_service.set_setting(db_session, OWNER, "file_max_bytes", "")
    assert (
        await core_upload(db_session, main_actor, project, data=bytes(TWO_MB))
    ).size_bytes == TWO_MB


async def test_the_size_limit_follows_the_table_in_rest(
    client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    await settings_service.set_setting(db_session, OWNER, "file_max_bytes", "1048576")
    refused = await rest_upload(client, bytes(TWO_MB))
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "file_too_large"
    assert refused.json()["error"]["details"]["max_bytes"] == 1048576

    await settings_service.set_setting(db_session, OWNER, "file_max_bytes", "3145728")
    assert (await rest_upload(client, bytes(TWO_MB))).status_code == 201


async def test_the_size_limit_follows_the_table_in_the_mcp_link(
    mcp_server: object,
    mcp_sessions: SessionFactory,
    main_secret: str,
    project: Project,
) -> None:
    """Ссылка называет предел из таблицы, а загрузка по ней отказывает 413 по тому же пределу."""
    async with mcp_sessions() as session:
        await settings_service.set_setting(session, OWNER, "file_max_bytes", "1048576")
    async with served(mcp_server, main_secret) as (client, curl):  # type: ignore[arg-type]
        link = await call(client, "request_file_upload", project="TRK", name="big.bin")
        assert link["max_bytes"] == 1048576
        response = await put(curl, link, bytes(TWO_MB))
        assert response.status_code == 413
        assert response.json()["details"]["max_bytes"] == 1048576

        async with mcp_sessions() as session:
            await settings_service.set_setting(session, OWNER, "file_max_bytes", "")
        again = await call(client, "request_file_upload", project="TRK", name="big.bin")
        assert again["max_bytes"] == get_settings().file_max_bytes
        assert (await put(curl, again, bytes(TWO_MB))).status_code == 200
