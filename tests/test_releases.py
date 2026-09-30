"""Последний выпуск Casefile: `GET /api/v1/installation/release` (TRK-416).

В настоящий GitHub тесты не ходят. Подменяется либо чтение выпуска целиком
(`app.services.releases.read_latest_release` — до `create_app`, который его берёт),
либо `urlopen` под ним: так проверяется и разбор ответа GitHub, и сбой сети.
"""

import asyncio
import io
import json
import urllib.error
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import Settings
from app.db.session import get_session
from app.domain.releases import Release, is_newer, parse_version
from app.main import create_app
from app.services import releases
from app.services.releases import CHECK_INTERVAL, FAILURE_RETRY, ReleaseWatch

#: Поля ответа. Список закрытый: поле, добавленное мимо него, роняет тест.
RELEASE_FIELDS = ["latest_url", "latest_version", "update_available", "version"]

NEWER = Release(version="99.0.0", url="https://github.com/azimov777/casefile/releases/tag/v99.0.0")
SAME = Release(
    version=__version__,
    url=f"https://github.com/azimov777/casefile/releases/tag/v{__version__}",
)


class FakeGitHub:
    """Подмена чтения выпуска: отвечает заданным и считает походы."""

    def __init__(self, answer: Release | None) -> None:
        self.answer = answer
        self.calls = 0

    async def __call__(self) -> Release | None:
        self.calls += 1
        return self.answer


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub(NEWER)
    monkeypatch.setattr(releases, "read_latest_release", fake)
    return fake


@asynccontextmanager
async def client_of(settings: Settings, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Клиент приложения, собранного с этими настройками: у каждого свой кэш выпуска."""
    application = create_app(settings)
    application.dependency_overrides[get_session] = lambda: db_session
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://tracker.test") as http_client:
        yield http_client


async def read(client: AsyncClient, secret: str) -> dict[str, object]:
    response = await client.get(
        "/api/v1/installation/release", headers={"Authorization": f"Bearer {secret}"}
    )
    assert response.status_code == 200, response.text
    data: dict[str, object] = response.json()["data"]
    assert sorted(data) == RELEASE_FIELDS
    return data


def production() -> Settings:
    """Установка, которой положено ходить в GitHub."""
    return Settings(environment="production", release_check=True)


# --- Обзорная проверка 1: новее, равен, сбой ----------------------------------------


async def test_a_newer_release_is_reported_with_both_versions(
    db_session: AsyncSession, task_secret: str, github: FakeGitHub
) -> None:
    async with client_of(production(), db_session) as client:
        data = await read(client, task_secret)

    assert data == {
        "version": __version__,
        "latest_version": "99.0.0",
        "latest_url": "https://github.com/azimov777/casefile/releases/tag/v99.0.0",
        "update_available": True,
    }
    assert github.calls == 1


async def test_the_same_release_is_no_update(
    db_session: AsyncSession, task_secret: str, github: FakeGitHub
) -> None:
    github.answer = SAME

    async with client_of(production(), db_session) as client:
        data = await read(client, task_secret)

    assert data["latest_version"] == __version__
    assert data["update_available"] is False


async def test_a_network_failure_is_no_update_and_no_error(
    db_session: AsyncSession, task_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Настоящее чтение выпуска, а под ним — упавший `urlopen`: ответ `200` без признака."""

    def unreachable(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("Temporary failure in name resolution")

    monkeypatch.setattr(releases.urllib.request, "urlopen", unreachable)

    async with client_of(production(), db_session) as client:
        data = await read(client, task_secret)

    assert data == {
        "version": __version__,
        "latest_version": None,
        "latest_url": None,
        "update_available": False,
    }


# --- Обзорная проверка 2: выключено — к GitHub не ходят ---------------------------


async def test_the_switched_off_check_never_asks_github(
    db_session: AsyncSession, task_secret: str, github: FakeGitHub
) -> None:
    settings = Settings(environment="production", release_check=False)

    async with client_of(settings, db_session) as client:
        first = await read(client, task_secret)
        await read(client, task_secret)

    assert github.calls == 0
    assert first["latest_version"] is None
    assert first["update_available"] is False


async def test_a_development_build_never_asks_github(
    db_session: AsyncSession, task_secret: str, github: FakeGitHub
) -> None:
    """Сборка разработки плашки не показывает: её версия не из тега выпуска."""
    settings = Settings(environment="local", release_check=True)

    async with client_of(settings, db_session) as client:
        data = await read(client, task_secret)

    assert github.calls == 0
    assert data["update_available"] is False


def test_the_switch_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TRACKER_RELEASE_CHECK=false` в `.env` выключает проверку; по умолчанию — включена."""
    assert Settings().release_check is True

    monkeypatch.setenv("TRACKER_RELEASE_CHECK", "false")

    assert Settings().release_check is False


# --- Обзорная проверка 3: два запроса в течение часа — один поход -------------------


async def test_two_requests_within_an_hour_ask_github_once(
    db_session: AsyncSession, task_secret: str, github: FakeGitHub
) -> None:
    async with client_of(production(), db_session) as client:
        await read(client, task_secret)
        await read(client, task_secret)

    assert github.calls == 1


async def test_the_cache_expires_after_an_hour_and_a_failure_sooner() -> None:
    """Срок удачи — час, срок сбоя — короче: по часам, а не по сну."""
    now = [0.0]
    fake = FakeGitHub(NEWER)
    watch = ReleaseWatch(enabled=True, fetch=fake, clock=lambda: now[0], version="0.7.0")

    await watch.read()
    now[0] = CHECK_INTERVAL - 1
    await watch.read()
    assert fake.calls == 1

    now[0] = CHECK_INTERVAL
    fake.answer = None
    state = await watch.read()
    assert fake.calls == 2
    assert state.latest is None
    assert state.update_available is False

    now[0] = CHECK_INTERVAL + FAILURE_RETRY - 1
    await watch.read()
    assert fake.calls == 2
    now[0] = CHECK_INTERVAL + FAILURE_RETRY
    fake.answer = NEWER
    assert (await watch.read()).update_available is True
    assert fake.calls == 3


async def test_concurrent_requests_on_an_empty_cache_ask_once() -> None:
    fake = FakeGitHub(NEWER)
    watch = ReleaseWatch(enabled=True, fetch=fake, version="0.7.0")

    await asyncio.gather(*(watch.read() for _ in range(5)))

    assert fake.calls == 1


# --- Разбор ответа GitHub и сравнение ----------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


async def test_the_github_answer_is_read_by_its_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Страница выпуска строится из тега, а не берётся из ответа."""
    seen: list[str] = []

    def answer(request: object, timeout: float) -> _Response:
        seen.append(request.full_url)  # type: ignore[attr-defined]
        body = {"tag_name": "v0.8.0", "html_url": "https://evil.example/"}
        return _Response(json.dumps(body).encode())

    monkeypatch.setattr(releases.urllib.request, "urlopen", answer)

    release = await releases.read_latest_release()

    assert seen == ["https://api.github.com/repos/azimov777/casefile/releases/latest"]
    assert release == Release(
        version="0.8.0", url="https://github.com/azimov777/casefile/releases/tag/v0.8.0"
    )


@pytest.mark.parametrize("body", [{"tag_name": "nightly"}, {"message": "Not Found"}, []])
async def test_an_answer_without_a_version_tag_is_no_release(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    monkeypatch.setattr(
        releases.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(json.dumps(body).encode()),
    )

    assert await releases.read_latest_release() is None


@pytest.mark.parametrize(
    ("latest", "installed", "newer"),
    [
        ("0.8.0", "0.7.0", True),
        ("0.10.0", "0.9.0", True),
        ("1.0.0", "0.99.99", True),
        ("0.7.0", "0.7.0", False),
        ("0.6.9", "0.7.0", False),
        ("0.8.0-rc.1", "0.7.0", False),
        ("0.8.0", "dev", False),
    ],
)
def test_versions_compare_as_numbers(latest: str, installed: str, newer: bool) -> None:
    assert is_newer(Release(version=latest, url=""), installed) is newer


def test_a_tag_with_v_parses_like_a_version() -> None:
    assert parse_version("v0.7.0") == parse_version("0.7.0") == (0, 7, 0)
