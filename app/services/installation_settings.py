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
from datetime import datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.repositories.installation_settings import InstallationSettingRepository
from app.domain.authors import Author
from app.domain.errors import InstallationSettingInvalidError
from app.domain.installation_settings import (
    SETTINGS,
    SettingKind,
    SettingSpec,
    SettingValue,
    format_value,
    get_spec,
    parse_value,
)
from app.services.accounts import ensure_admin
from app.services.auth import Actor

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


async def resolve_setting(
    session: AsyncSession, name: str, *, settings: Settings | None = None
) -> ResolvedSetting:
    """Значение настройки с источником: база, затем окружение, затем умолчание кода.

    `settings` — `Settings` приложения, обслуживающего вызов: поле, заданное в нём явно
    (окружением, `.env` или при сборке приложения), заменяет чтение `os.environ`.
    Без него окружение читается напрямую.
    """
    spec = get_spec(name)
    stored = await InstallationSettingRepository(session).get_value(name)
    if stored:
        try:
            return ResolvedSetting(name, parse_value(spec, stored), SettingSource.DATABASE)
        except InstallationSettingInvalidError:
            # Строку мог положить приём архива старой версии или ручной SQL.
            logger.warning("Stored value of setting %s is invalid and is ignored", name)
    if settings is not None and name in settings.model_fields_set:
        return ResolvedSetting(name, getattr(settings, name), SettingSource.ENVIRONMENT)
    from_env = os.environ.get(spec.env_var, "").strip()
    if from_env:
        try:
            return ResolvedSetting(name, parse_value(spec, from_env), SettingSource.ENVIRONMENT)
        except InstallationSettingInvalidError:
            logger.warning("%s is invalid and is ignored: the default is used", spec.env_var)
    return ResolvedSetting(name, spec.default, SettingSource.DEFAULT)


async def get_setting(
    session: AsyncSession, name: str, *, settings: Settings | None = None
) -> SettingValue:
    """Значение настройки по имени: узкий вызов для читателей."""
    return (await resolve_setting(session, name, settings=settings)).value


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


@dataclass(frozen=True, slots=True)
class SettingState:
    """Настройка для экрана: правила, что лежит в базе, что действует и кто менял (TRK-744)."""

    spec: SettingSpec
    stored: str | None
    effective: SettingValue
    source: SettingSource
    default: SettingValue
    default_source: SettingSource
    updated_by: Author | None
    updated_at: datetime | None

    @property
    def kind(self) -> SettingKind:
        return self.spec.kind


def _without_database(spec: SettingSpec) -> tuple[SettingValue, SettingSource]:
    """Значение, которое действует, когда в базе пусто: окружение, иначе умолчание кода."""
    from_env = os.environ.get(spec.env_var, "").strip()
    if from_env:
        try:
            return parse_value(spec, from_env), SettingSource.ENVIRONMENT
        except InstallationSettingInvalidError:
            logger.warning("%s is invalid and is ignored: the default is used", spec.env_var)
    return spec.default, SettingSource.DEFAULT


async def _state_of(session: AsyncSession, spec: SettingSpec) -> SettingState:
    resolved = await resolve_setting(session, spec.name)
    default, default_source = _without_database(spec)
    row = await InstallationSettingRepository(session).get_row(spec.name)
    return SettingState(
        spec=spec,
        stored=(row.value or None) if row is not None else None,
        effective=resolved.value,
        source=resolved.source,
        default=default,
        default_source=default_source,
        updated_by=None if row is None else row.updated_by,
        updated_at=None if row is None else row.updated_at,
    )


async def list_settings(session: AsyncSession, actor: Actor) -> list[SettingState]:
    """Все семь настроек в порядке реестра. Читает любой вошедший: секретов здесь нет."""
    del actor  # вход уже проверен зависимостью `get_actor`; права на чтение не делятся
    return [await _state_of(session, spec) for spec in SETTINGS]


async def update_setting(session: AsyncSession, actor: Actor, name: str, raw: str) -> SettingState:
    """Правка настройки администратором; пустая строка возвращает «брать из окружения».

    Администратор — учётная запись с флагом (`admin_required` иначе, ключу агента тоже).
    Права проверяются раньше имени: не администратор не узнаёт состав реестра по разнице
    отказов.
    """
    await ensure_admin(session, actor, action="installation_setting.update")
    spec = get_spec(name)
    await set_setting(session, actor.author, name, raw)
    return await _state_of(session, spec)
