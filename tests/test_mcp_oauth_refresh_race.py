"""Два одновременных refresh одним токеном от одного клиента — вход остаётся (TRK-504).

Claude Code сразу после входа обновляет токен дважды подряд одним и тем же refresh
(`TRK-453#13`); прежде второй запрос считался повтором погашенного токена и отзывал всю
цепочку. Повтор в окне `REFRESH_REUSE_WINDOW` получает ещё одну пару в той же цепочке.

Гонку нельзя проверить на фикстуре `mcp_sessions`: она пускает запросы в одну сессию
теста по очереди, под замком, и одновременность превращается в последовательность. Здесь,
как в `test_idempotency_race.py`, у каждого запроса своя сессия на движке прогона с
настоящим коммитом, а `asyncio.Barrier` выпускает оба запроса разом. Оба успевают прочитать
refresh непогашенным (`find_refresh`), и проигравший узнаёт о погашении только на
`claim_refresh`: его `UPDATE … WHERE used_at IS NULL` ждёт блокировки строки, взятой
победителем, и после его коммита меняет ноль строк.

Закоммиченные строки убираются в `finally`: клиенты OAuth (с ними уходят коды и refresh),
токены и участники, которых не было до теста.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.oauth import OAuthClient
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.session import transaction
from app.mcp.runtime import SessionFactory
from test_mcp_oauth import _http, _initialize, _refresh, _server, _sign_in

PARALLEL = 2


@pytest.fixture
async def committing_scope(engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    """Фабрика сессий службы mcp, как в бою: своя сессия и свой коммит на каждый запрос."""
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def ids(model: type[OAuthClient | Token | Participant]) -> set[uuid.UUID]:
        async with sessions() as session:
            return set(await session.scalars(select(model.id)))

    before = {model: await ids(model) for model in (OAuthClient, Token, Participant)}

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        async with sessions() as session, transaction(session):
            yield session

    try:
        yield scope
    finally:
        async with sessions() as session:
            for model, table in (
                (OAuthClient, "oauth_clients"),
                (Token, "tokens"),
                (Participant, "participants"),
            ):
                fresh = set(await session.scalars(select(model.id))) - before[model]
                if fresh:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE id = ANY(:ids)"),
                        {"ids": list(fresh)},
                    )
            await session.commit()


async def test_parallel_refreshes_of_one_token_keep_the_client_signed_in(
    committing_scope: SessionFactory,
) -> None:
    """Проверка 1 TRK-504: оба одновременных refresh — `200`, выданные токены работают."""
    async with _http(_server(committing_scope)) as client:
        client_id, first = await _sign_in(client)
        barrier = asyncio.Barrier(PARALLEL)

        async def refresh() -> tuple[int, dict]:
            await barrier.wait()
            response = await _refresh(client, client_id, first["refresh_token"])
            return response.status_code, response.json()

        answers = await asyncio.gather(*(refresh() for _ in range(PARALLEL)))
        assert [status for status, _ in answers] == [200] * PARALLEL, answers

        pairs = [payload for _, payload in answers]
        works = [await _initialize(client, pair["access_token"]) for pair in pairs]
        # Цепочка жива: любой из выданных refresh обновляет дальше.
        onward = await _refresh(client, client_id, pairs[-1]["refresh_token"])
        old = await _initialize(client, first["access_token"])

    assert [response.status_code for response in works] == [200] * PARALLEL
    assert len({pair["refresh_token"] for pair in pairs}) == PARALLEL
    assert onward.status_code == 200, onward.text
    assert old.status_code == 401
