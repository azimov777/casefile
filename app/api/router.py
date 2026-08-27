"""Корневой роутер версии API.

Сюда подключаются роутеры предметных областей — по одному на задачу из `docs/tasks`.
Префикс задаётся здесь один раз, отдельные роутеры про версию не знают.

Аутентификация объявлена на самом роутере, а не на каждом эндпоинте. Так новый маршрут
защищён по умолчанию: чтобы оставить его открытым, это придётся сделать осознанно, а
забыть авторизацию — нельзя. Вне `/api/v1` остаётся только `/health` для мониторинга.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_actor
from app.api.routes import actors

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(get_current_actor)])

api_router.include_router(actors.router)
