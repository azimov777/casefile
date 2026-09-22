"""Выборки и вставки по учётным записям."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.pagination import Page, paginate


class AccountRepository:
    """Доступ к таблице `accounts`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        statement = select(Account).where(Account.id == account_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_by_email(self, email: str) -> Account | None:
        """Поиск по уже канонизированной почте: канонизацию делает домен, не запрос."""
        statement = select(Account).where(Account.email == email)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_by_participant(self, participant_id: uuid.UUID) -> Account | None:
        statement = select(Account).where(Account.participant_id == participant_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def count_active_admins(self) -> int:
        """Сколько действующих (не отключённых) администраторов на установке."""
        statement = select(func.count(Account.id)).where(
            Account.is_admin.is_(True), Account.disabled_at.is_(None)
        )
        return int(await self._session.scalar(statement) or 0)

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Account]:
        return await paginate(self._session, select(Account), Account, limit=limit, cursor=cursor)

    async def add(self, account: Account) -> Account:
        self._session.add(account)
        await self._session.flush()
        return account
