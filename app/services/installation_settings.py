"""Настройки установки: чтение «база → окружение → умолчание» и запись по реестру.

Слово владельца TRK~31#4. Чтение идёт в базу при каждом обращении и кеша между
вызовами не держит: смена значения действует на следующий вызов в обоих процессах
(`api`, `mcp`), без перезапуска и без пересоздания `Settings`.

Порядок: непустое значение в таблице; иначе переменная окружения, если она задана и
проходит правила реестра (негодная пропускается с предупреждением в журнале, а не роняет
чтение: окружение процесса читается один раз при подъёме, и ошибку там уже видел
`Settings`); иначе умолчание кода. Источник возвращает `resolve_setting`, чтобы экран
мог показать, откуда значение.

Запись проверяет значение по реестру и ничего не пишет при отказе. Пустая строка
возвращает настройку окружению. Читатели существующих параметров переходят на этот вызов
отдельными задачами; REST и экран тоже.
"""

import logging
import os
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.installation_settings import InstallationSettingRepository
from app.domain.authors import Author
from app.domain.errors import InstallationSettingInvalidError
from app.domain.installation_settings import (
    SettingValue,
    format_value,
    get_spec,
    parse_value,
)

logger = logging.getLogger(__name__)


class SettingSource(StrEnum):
    """Откуда взято значение."""

    DATABASE = "database"
    ENVIRONMENT = "environment"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class ResolvedSetting:
    """Значение настройки и откуда оно."""

    name: str
    value: SettingValue
    source: SettingSource


async def resolve_setting(session: AsyncSession, name: str) -> ResolvedSetting:
    """Значение настройки с источником: база, затем окружение, затем умолчание кода."""
    spec = get_spec(name)
    stored = await InstallationSettingRepository(session).get_value(name)
    if stored:
        try:
            return ResolvedSetting(name, parse_value(spec, stored), SettingSource.DATABASE)
        except InstallationSettingInvalidError:
            # Строку мог положить приём архива старой версии или ручной SQL.
            logger.warning("Stored value of setting %s is invalid and is ignored", name)
    from_env = os.environ.get(spec.env_var, "").strip()
    if from_env:
        try:
            return ResolvedSetting(name, parse_value(spec, from_env), SettingSource.ENVIRONMENT)
        except InstallationSettingInvalidError:
            logger.warning("%s is invalid and is ignored: the default is used", spec.env_var)
    return ResolvedSetting(name, spec.default, SettingSource.DEFAULT)


async def get_setting(session: AsyncSession, name: str) -> SettingValue:
    """Значение настройки по имени: узкий вызов для читателей."""
    return (await resolve_setting(session, name)).value


async def set_setting(
    session: AsyncSession, author: Author, name: str, raw: str
) -> ResolvedSetting:
    """Записывает значение, проверив его по реестру; пустая строка — «брать из окружения».

    Неизвестное имя — `installation_setting_not_found`, значение вне правил —
    `installation_setting_invalid`; в обоих случаях таблица не меняется.
    """
    spec = get_spec(name)
    stored = "" if not raw.strip() else format_value(spec, parse_value(spec, raw))
    await InstallationSettingRepository(session).upsert(name, stored, author)
    return await resolve_setting(session, name)
