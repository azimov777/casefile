"""Строки таблицы `installation_settings`: прочитать и записать значение.

Репозиторий не коммитит: границу транзакции держит вход в приложение. Запись — один
`INSERT ... ON CONFLICT`: два администратора, пишущие одно имя, не ловят уникальность.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.installation_setting import InstallationSetting
from app.domain.authors import Author


class InstallationSettingRepository:
    """Доступ к таблице `installation_settings`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_value(self, name: str) -> str | None:
        """Сохранённое значение или `None`, если строки нет. Всегда запрос в базу."""
        statement = select(InstallationSetting.value).where(InstallationSetting.name == name)
        return await self._session.scalar(statement)

    async def get_row(self, name: str) -> InstallationSetting | None:
        """Строка целиком (кто и когда менял) или `None`."""
        statement = select(InstallationSetting).where(InstallationSetting.name == name)
        return await self._session.scalar(statement)

    async def list_all(self) -> list[InstallationSetting]:
        statement = select(InstallationSetting).order_by(InstallationSetting.name)
        return list(await self._session.scalars(statement))

    async def upsert(self, name: str, value: str, author: Author) -> InstallationSetting:
        """Кладёт значение под имя и отдаёт строку с новым временем изменения."""
        fields = {
            "value": value,
            "updated_by_kind": author.kind,
            "updated_by_signature": author.signature,
        }
        statement = (
            insert(InstallationSetting)
            .values(name=name, **fields)
            .on_conflict_do_update(
                index_elements=[InstallationSetting.name],
                set_={**fields, "updated_at": func.now()},
            )
            .returning(InstallationSetting)
            .execution_options(populate_existing=True)
        )
        return (await self._session.scalars(statement)).one()
