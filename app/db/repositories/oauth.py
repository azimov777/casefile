"""Выборки и вставки по клиентам OAuth, кодам и refresh-токенам."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.oauth import OAuthClient, OAuthCode, OAuthRefreshToken


class OAuthRepository:
    """Доступ к таблицам `oauth_clients`, `oauth_codes`, `oauth_refresh_tokens`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_client(self, client_id: str) -> OAuthClient | None:
        statement = select(OAuthClient).where(OAuthClient.client_id == client_id)
        return (await self._session.scalars(statement)).one_or_none()

    async def get_code(self, code_hash: str) -> OAuthCode | None:
        statement = select(OAuthCode).where(OAuthCode.code_hash == code_hash)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def claim_code(self, code_id: uuid.UUID, moment: datetime) -> bool:
        """Гасит код, если он ещё не погашен. Истина — погасил этот вызов.

        Одним `UPDATE … WHERE used_at IS NULL`, а не чтением и записью: два обмена одного
        кода сходятся на строке, и второй увидит ноль изменённых строк.
        """
        statement = (
            update(OAuthCode)
            .where(OAuthCode.id == code_id, OAuthCode.used_at.is_(None))
            .values(used_at=moment)
            .returning(OAuthCode.id)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def delete_codes_expired_before(self, moment: datetime) -> None:
        """Попутная уборка давно истёкших кодов: они не нужны даже для поимки повтора."""
        await self._session.execute(delete(OAuthCode).where(OAuthCode.expires_at < moment))

    async def get_refresh(self, token_hash: str) -> OAuthRefreshToken | None:
        statement = select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == token_hash)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def claim_refresh(self, refresh_id: uuid.UUID, moment: datetime) -> bool:
        """Гасит refresh-токен, если он ещё не погашен; устроен как `claim_code`."""
        statement = (
            update(OAuthRefreshToken)
            .where(OAuthRefreshToken.id == refresh_id, OAuthRefreshToken.used_at.is_(None))
            .values(used_at=moment)
            .returning(OAuthRefreshToken.id)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def list_family(self, family_id: uuid.UUID) -> Sequence[OAuthRefreshToken]:
        """Все refresh-токены цепочки ротаций — чтобы отозвать её целиком."""
        statement = select(OAuthRefreshToken).where(OAuthRefreshToken.family_id == family_id)
        return (await self._session.scalars(statement)).unique().all()

    async def add[T: (OAuthClient, OAuthCode, OAuthRefreshToken)](self, row: T) -> T:
        self._session.add(row)
        await self._session.flush()
        return row
