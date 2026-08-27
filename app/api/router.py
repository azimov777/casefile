"""Корневой роутер версии API.

Сюда подключаются роутеры предметных областей — по одному на задачу из `docs/tasks`.
Префикс задаётся здесь один раз, отдельные роутеры про версию не знают.

Аутентификация объявлена на самом роутере, а не на каждом эндпоинте. Так новый маршрут
защищён по умолчанию: чтобы оставить его открытым, это придётся сделать осознанно, а
забыть авторизацию — нельзя. Вне `/api/v1` остаётся только `/health` для мониторинга.
"""

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.api.deps import get_current_actor
from app.api.routes import actors, catalogs, queues
from app.api.schemas.common import ErrorResponse

# Формы ошибок объявлены один раз на весь версионированный API, а не повторены в каждом
# эндпоинте: оболочка ошибки в проекте одна, и в сгенерированном клиенте она обязана быть
# видна у любого маршрута. Коды берутся из таблицы базовых ошибок в соглашениях.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Token is missing, unknown or revoked"},
    403: {"model": ErrorResponse, "description": "Action is not allowed"},
    404: {"model": ErrorResponse, "description": "Object not found"},
    409: {"model": ErrorResponse, "description": "State conflict"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    500: {"model": ErrorResponse, "description": "Unexpected error"},
}


def generate_operation_id(route: APIRoute) -> str:
    """Идентификатор операции для генератора клиента — имя функции-обработчика.

    По умолчанию FastAPI склеивает имя с путём и методом
    (`read_actor_api_v1_actors__actor_key__get`). В сгенерированном TypeScript это
    нечитаемо, а главное — меняется при любой правке пути, и фронтенд ломается на
    переезде маршрута, хотя контракт не менялся. Имя функции зависит только от кода.

    Уникальность имён обработчиков FastAPI не гарантирует, поэтому её стережёт тест
    `tests/test_openapi.py`.
    """
    return route.name


api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(get_current_actor)],
    responses=ERROR_RESPONSES,
)

api_router.include_router(actors.router)
api_router.include_router(queues.router)
api_router.include_router(catalogs.router)
