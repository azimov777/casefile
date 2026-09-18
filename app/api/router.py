"""Корневой роутер версии API.

Сюда подключаются роутеры предметных областей — по одному на область.
Префикс задаётся здесь один раз, отдельные роутеры про версию не знают.

Аутентификация и формы ошибок объявлены на самом роутере, а не на каждом эндпоинте.
Так новый маршрут защищён по умолчанию: чтобы оставить его открытым, это придётся
сделать осознанно, а забыть авторизацию — нельзя. Обратный порядок держался бы на
внимательности семнадцати задач подряд. Вне `/api/v1` остаётся только `/health` для
мониторинга; без токена под `/api/v1` — только вход по паролю, вынесенный в свой роутер
(`session_router` ниже).

Важное ограничение FastAPI 0.141, о которое легко споткнуться: `route_class`,
`dependencies` и `responses` родительского роутера **не** наследуются роутерами,
подключёнными через `include_router`, — кроме зависимостей и ответов, которые FastAPI
переносит явно. Поэтому всё, что обязано действовать на каждый маршрут, объявляется
здесь через поддерживаемые параметры, а не через собственный класс маршрута.
"""

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.api.deps import get_actor, reject_unknown_query_params
from app.api.routes import (
    bootstrap,
    installation,
    journal,
    links,
    participants,
    questions,
    queues,
    remarks,
    session,
    tasks,
    tokens,
)
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
    (`read_queue_api_v1_queues__queue_key__get`). В сгенерированном TypeScript это
    нечитаемо, а главное — меняется при любой правке пути, и фронтенд ломается на
    переезде маршрута, хотя контракт не менялся. Имя функции зависит только от кода.

    Уникальность имён обработчиков FastAPI не гарантирует, поэтому её стережёт тест
    `tests/test_openapi.py`.
    """
    return route.name


# Порядок зависимостей — порядок отказов: сначала «кто ты», потом «что ты прислал».
# Сторож параметров стоит на роутере, а не на маршруте, по той же причине, что и
# аутентификация: маршрут, заведённый завтра, обязан получить правило сам.
api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(get_actor), Depends(reject_unknown_query_params)],
    responses=ERROR_RESPONSES,
)

api_router.include_router(bootstrap.router)
api_router.include_router(installation.router)
api_router.include_router(participants.router)
api_router.include_router(tokens.router)
api_router.include_router(queues.router)
api_router.include_router(tasks.router)
api_router.include_router(links.router)
api_router.include_router(questions.router)
api_router.include_router(remarks.router)
api_router.include_router(journal.router)


# Вход владельца по паролю — единственное под `/api/v1`, что живёт без токена: пароль и
# есть то, чем браузер получает ключ (`docs/CONCEPT.md`, 5.4). Отдельный роутер, а не
# исключение внутри общего: общий требует токен у всего, что в него попало, и открыть
# маршрут можно только вынеся его сюда осознанно. Список таких маршрутов объявлен кодом
# (`app/api/contract.py`, `TOKEN_EXEMPT`), и сплошная проверка сверяет его с этим роутером.
SESSION_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Wrong password or no live session"},
    409: {"model": ErrorResponse, "description": "The installation has no owner password"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    429: {"model": ErrorResponse, "description": "Too many password attempts, retry later"},
    500: {"model": ErrorResponse, "description": "Unexpected error"},
}

session_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(reject_unknown_query_params)],
    responses=SESSION_ERROR_RESPONSES,
)

session_router.include_router(session.router)
