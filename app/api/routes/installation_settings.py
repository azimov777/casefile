"""Настройки установки: читает любой вошедший, правит администратор (TRK-744).

Слово владельца TRK~31#4. Роутер переводит HTTP в вызов сценария и обратно. Ключ агента
правки не получает: у участника-агента нет учётной записи с флагом (`403 admin_required`).
Изменение ничего не запускает само: следующее обращение читателя увидит новое значение.
"""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import ActorDep, SessionDep
from app.api.schemas.authors import AuthorRead
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.installation_settings import (
    InstallationSettingRead,
    InstallationSettingUpdate,
)
from app.domain.installation_settings import format_value
from app.services import installation_settings as service
from app.services.installation_settings import SettingState

router = APIRouter(prefix="/settings", tags=["settings"])

SettingNamePath = Annotated[
    str, Path(description="Setting name from the registry", examples=["mcp_page_size"])
]


def _read(state: SettingState) -> InstallationSettingRead:
    spec = state.spec
    return InstallationSettingRead(
        name=spec.name,
        env_var=spec.env_var,
        kind=spec.kind,
        value=state.stored,
        effective_value=format_value(spec, state.effective),
        source=state.source,
        default_value=format_value(spec, state.default),
        default_source=state.default_source,
        minimum=spec.minimum,
        maximum=spec.maximum,
        updated_by=None
        if state.updated_by is None
        else AuthorRead.model_validate(state.updated_by),
        updated_at=state.updated_at,
    )


@router.get("", summary="List installation settings")
async def list_settings(
    session: SessionDep, actor: ActorDep
) -> CollectionResponse[InstallationSettingRead]:
    """Семь настроек установки в порядке реестра: правила, значение, источник, кто менял.

    Открыто любому вошедшему: секретов здесь нет, а экран показывает всем, что действует.
    Без страниц и без `meta.total`: набор ограничен реестром.
    """
    states = await service.list_settings(session, actor)
    return CollectionResponse[InstallationSettingRead].of(
        [_read(state) for state in states], next_cursor=None
    )


@router.patch("/{name}", summary="Change an installation setting")
async def update_setting(
    name: SettingNamePath,
    payload: InstallationSettingUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[InstallationSettingRead]:
    """Задаёт значение настройки; пустое значение возвращает её окружению или умолчанию.

    Только администратору (`403 admin_required`), ключу агента тоже. Имя вне реестра —
    `404 installation_setting_not_found`, значение вне типа или пределов —
    `422 installation_setting_invalid` с причиной в `details.reason`; при отказе ничего не
    меняется. Ответ — настройка целиком, как в списке.
    """
    value = payload.value
    raw = "" if value is None else format_raw(value)
    state = await service.update_setting(session, actor, name, raw)
    return DataResponse[InstallationSettingRead](data=_read(state))


def format_raw(value: str | int | bool) -> str:
    """Присланное значение — строкой для разбора реестром: логическое в `true`/`false`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
