"""Сведения об установке: то, что одинаково для любого, кто спрашивает.

Новой сущности здесь нет, и базы тоже: это представление над настройками процесса.
Роутер только переводит HTTP в вызов сценария и обратно.
"""

from fastapi import APIRouter

from app.api.deps import ActorDep, SettingsDep
from app.api.schemas.common import DataResponse
from app.api.schemas.installation import InstallationRead
from app.services import installation as service

router = APIRouter(prefix="/installation", tags=["installation"])


@router.get("", summary="Read the installation")
async def read_installation(
    actor: ActorDep, settings: SettingsDep
) -> DataResponse[InstallationRead]:
    """Публичный адрес MCP, из которого интерфейс собирает конфигурацию клиента агента.

    Открыт любому набору, в том числе `task`: секрета здесь нет, а экрану подключения
    агента нужен именно ключ, который у интерфейса уже есть. Ответ одинаков для любого
    токена и меняется только с настройкой установки (`TRACKER_MCP_PUBLIC_URL`), поэтому
    клиент вправе держать его всю жизнь вкладки.

    В первый экран (`GET /api/v1/bootstrap`) адрес не входит: он нужен одному экрану, а
    не первому кадру (`docs/CONCEPT.md`, 5.1).
    """
    state = service.read_installation(actor=actor, settings=settings)
    return DataResponse[InstallationRead](data=InstallationRead(mcp_url=state.mcp_url))
