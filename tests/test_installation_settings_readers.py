"""Пять существующих параметров читаются из настроек при обращении (TRK-745).

Страница и обрезка MCP — на следующем вызове, срок сеанса и срок подключения — на новых
сеансах и подключениях (выданные не меняются), проверка выпуска — на следующей проверке.
Значение в окружении здесь задано явно, в `Settings` приложения: так же, как его задаёт
боевая установка, — и запись в таблицу перекрывает его без пересоздания приложения.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models.project import Project
from app.db.models.token import Token
from app.domain.authors import Author, AuthorKind
from app.domain.tokens import hash_token
from app.mcp.runtime import Runtime, SessionFactory
from app.mcp.server import create_server
from app.services import installation_settings as service
from app.services.auth import Actor
from app.services.login import PasswordLogin
from app.services.releases import ReleaseWatch
from conftest import call, connect_mcp, make_task
from test_mcp_oauth import _http, _server, _sign_in
from test_password_login import ALICE, PASSWORD, make_account

OWNER = Author(kind=AuthorKind.HUMAN, signature="owner")


async def write(sessions: SessionFactory, name: str, value: str) -> None:
    """Запись настройки под замком сессии теста: сервер MCP читает её параллельно."""
    async with sessions() as session:
        await service.set_setting(session, OWNER, name, value)


async def test_the_mcp_page_size_follows_the_table_on_the_next_call(
    mcp_sessions: SessionFactory,
    db_session: AsyncSession,
    main_actor: Actor,
    main_secret: str,
    project: Project,
) -> None:
    """При `TRACKER_MCP_PAGE_SIZE=25` запись 10 в таблицу даёт страницу в 10 записей."""
    for number in range(12):
        await make_task(
            db_session,
            actor=main_actor,
            project=project,
            title=f"Задача {number}",
            description="Для страницы",
        )
    settings = get_settings().model_copy(update={"mcp_page_size": 25})
    server = create_server(runtime=Runtime(sessions=mcp_sessions), settings=settings)

    async with connect_mcp(server, main_secret) as session:
        before = await call(session, "search_tasks", project=[project.key], fields=["key"])
        await write(mcp_sessions, "mcp_page_size", "10")
        after = await call(session, "search_tasks", project=[project.key], fields=["key"])
        explicit = await call(
            session, "search_tasks", project=[project.key], fields=["key"], limit=3
        )
        await write(mcp_sessions, "mcp_page_size", "")
        reset = await call(session, "search_tasks", project=[project.key], fields=["key"])

    assert len(before["items"]) == 12
    assert len(after["items"]) == 10
    assert len(explicit["items"]) == 3
    assert len(reset["items"]) == 12


async def test_the_mcp_text_limit_follows_the_table_on_the_next_call(
    mcp_sessions: SessionFactory,
    db_session: AsyncSession,
    main_actor: Actor,
    main_secret: str,
    project: Project,
) -> None:
    await make_task(
        db_session,
        actor=main_actor,
        project=project,
        title="Длинное описание",
        description="д" * 1000,
    )
    server = create_server(runtime=Runtime(sessions=mcp_sessions))

    async with connect_mcp(server, main_secret) as session:
        await write(mcp_sessions, "mcp_text_limit", "200")
        cut = await call(session, "search_tasks", project=[project.key], fields=["description"])
        await write(mcp_sessions, "mcp_text_limit", "5000")
        whole = await call(session, "search_tasks", project=[project.key], fields=["description"])

    assert cut["items"][0]["description_length"] == 1000
    assert "description_truncated" in cut["items"][0]
    assert "description_truncated" not in whole["items"][0]


async def test_the_session_hours_setting_applies_to_new_sessions_only(
    db_session: AsyncSession,
) -> None:
    """Запись 24 в `session_hours` даёт новому сеансу сутки, выданный раньше не меняется."""
    await make_account(db_session, "alice", ALICE)
    login = PasswordLogin.from_settings(Settings(session_hours=2))

    first = await login.open(db_session, email=ALICE, password=PASSWORD, client=None)
    await service.set_setting(db_session, OWNER, "session_hours", "24")
    second = await login.open(db_session, email=ALICE, password=PASSWORD, client=None)

    now = datetime.now(UTC)
    assert timedelta(hours=1, minutes=55) < first.expires_at - now < timedelta(hours=2, minutes=5)
    assert (
        timedelta(hours=23, minutes=55) < second.expires_at - now < timedelta(hours=24, minutes=5)
    )
    assert first.token.expires_at is not None
    assert first.token.expires_at - now < timedelta(hours=2, minutes=5)


async def test_the_oauth_access_ttl_setting_applies_to_the_next_connection(
    mcp_sessions: SessionFactory, db_session: AsyncSession
) -> None:
    """Запись `PT1H` в `oauth_access_ttl` даёт новому подключению час без пересборки сервера."""
    async with _http(_server(mcp_sessions, ttl=timedelta(days=30))) as client:
        _, first = await _sign_in(client)
        await write(mcp_sessions, "oauth_access_ttl", "PT1H")
        _, second = await _sign_in(client)

    assert first["expires_in"] == int(timedelta(days=30).total_seconds())
    assert second["expires_in"] == 3600
    stored = await db_session.scalar(
        select(Token).where(Token.token_hash == hash_token(second["access_token"]))
    )
    assert stored is not None and stored.expires_at is not None
    assert abs(stored.expires_at - stored.created_at - timedelta(hours=1)) < timedelta(minutes=1)
    # Выданное раньше подключение осталось со своим сроком.
    old = await db_session.scalar(
        select(Token).where(Token.token_hash == hash_token(first["access_token"]))
    )
    assert old is not None and old.expires_at is not None
    assert old.expires_at - old.created_at > timedelta(days=29)


async def test_release_check_false_in_the_table_switches_the_check_off(
    db_session: AsyncSession,
) -> None:
    """`TRACKER_RELEASE_CHECK=false` в таблице отключает проверку при `true` в окружении."""
    calls = 0

    async def fetch() -> None:
        nonlocal calls
        calls += 1

    watch = ReleaseWatch.from_settings(Settings(environment="production", release_check=True))
    watch._fetch = fetch

    await watch.read(db_session)
    assert calls == 1

    await service.set_setting(db_session, OWNER, "release_check", "false")
    state = await watch.read(db_session)
    assert state.latest is None and state.update_available is False
    assert calls == 1  # к GitHub не ходили, кэш не нужен

    await service.set_setting(db_session, OWNER, "release_check", "")
    await watch.read(db_session)
    assert calls == 1  # проверка снова включена, срок кэша ещё не вышел
