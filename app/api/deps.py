"""Зависимости FastAPI, общие для всех роутеров."""

from typing import Annotated

from fastapi import Depends, Header, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.pagination import MAX_PAGE_SIZE, MIN_PAGE_SIZE
from app.db.session import get_session, session_scope
from app.domain.authors import ACTOR_LABEL_HEADER
from app.services.auth import Actor, authenticate
from app.services.journal import SessionFactory

# `scope="function"` — не украшение, а единственное, что доводит упавший коммит до
# клиента. FastAPI держит два стека завершения зависимостей: обычный закрывается уже
# **после** отправки ответа, и исключение из него превращается в
# `RuntimeError: Caught handled exception, but response already started` — клиент
# получает оборванный ответ вместо оболочки ошибки. Стек с областью `function`
# закрывается до отправки, и коммит, упавший на отложенном ограничении
# (`DEFERRABLE INITIALLY DEFERRED`), успевает стать нормальным `409 conflict`.
# Границу транзакции это не раздваивает: она по-прежнему одна, в `session_scope`.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
"""Сессия БД на время запроса. Тесты подменяют её через `app.dependency_overrides`."""

# `auto_error=False` обязателен: со значением по умолчанию FastAPI сам отвечает
# `403 {"detail": "Not authenticated"}` — мимо нашего конверта ошибки и с неверным
# статусом (по соглашениям отсутствие токена — это 401 `unauthorized`).
# Схема заодно попадает в OpenAPI, и в /docs появляется кнопка Authorize.
bearer_scheme = HTTPBearer(
    scheme_name="ApiToken",
    description="Tracker API token: `Authorization: Bearer trk_...`",
    auto_error=False,
)

CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

# Метка временного агента. Заголовок объявлен зависимостью, а не разбирается по месту:
# так он попадает в OpenAPI **у каждого** маршрута, и клиент видит, что его можно (а с
# общим агентским токеном — нужно) послать куда угодно.
#
# Шаблон в объявлении намеренно **не** задан, хотя место для него есть. Проверку делает
# домен: тот же заголовок приезжает в MCP мимо схем FastAPI, и с `pattern` одна и та же
# кривая метка получала бы в REST общий `validation_error`, а в MCP — предметный
# `invalid_actor_label` с шаблоном в подробностях. Расхождение интерфейсов на одном
# входе проект запрещает отдельным правилом.
ActorLabelHeader = Annotated[
    str | None,
    Header(
        alias=ACTOR_LABEL_HEADER,
        examples=["nightly_agent"],
        description=(
            "Signature of a temporary agent, latin snake_case. Required with a shared "
            "agent token (one issued without a participant), ignored with a participant token"
        ),
    ),
]


async def get_actor(
    session: SessionDep,
    credentials: CredentialsDep,
    label: ActorLabelHeader = None,
) -> Actor:
    """Автор запроса и набор его токена.

    Тонкая обёртка над сценарием `authenticate`: разбор заголовков — дело HTTP-слоя,
    всё остальное общее с MCP и командной строкой.
    """
    if credentials is None:
        raise UnauthorizedError(details={"reason": "missing_token"})
    return await authenticate(session, credentials.credentials, label=label)


ActorDep = Annotated[Actor, Depends(get_actor)]
"""Автор запроса. Зависимость кешируется на запрос, поэтому лишнего похода в БД нет."""


def get_session_factory() -> SessionFactory:
    """Способ открыть сессию для долгоживущего потока ленты.

    Сессия запроса (`SessionDep`) потоку не годится: FastAPI закрывает её, когда
    обработчик вернул ответ, — то есть **до** того, как поток отдал первый кадр. Держать
    одну сессию всё время потока нельзя тем более: соединение из пула, занятое на часы,
    исчерпало бы пул на десятке клиентов.

    Поэтому поток получает не сессию, а способ открыть её на время одной выборки.
    Зависимостью, а не импортом, ровно затем же, зачем и всё остальное здесь: тест
    подменяет её своей транзакцией и проверяет поток на данных, которых нет в общей базе.
    """
    return session_scope


StreamSessionsDep = Annotated[SessionFactory, Depends(get_session_factory)]
"""Способ открыть сессию на время одной выборки потока: сама сессия потоку не годится."""


# Параметры пагинации объявлены здесь, а не в каждом роутере: коллекции во всём API
# листаются одинаково, и три копии одного объявления неизбежно разъехались бы по
# границам и описаниям. Через `Annotated`, а не значением по умолчанию: так требует
# современный стиль FastAPI, и вызов `Query` не оказывается в списке аргументов, где
# он вычисляется один раз на всё приложение.
#
# Границы объявлены и здесь, и в `resolve_limit`, и это не дубль по недосмотру:
# параметр запроса даёт их в OpenAPI и отсекает мусор на входе, а проверка в сценарии
# работает для MCP и командной строки, которые мимо FastAPI не проходят.
LimitQuery = Annotated[int, Query(ge=MIN_PAGE_SIZE, le=MAX_PAGE_SIZE, description="Page size")]
CursorQuery = Annotated[
    str | None, Query(description="Cursor from `meta.next_cursor` of a previous page")
]


# Ключ задачи принимают роутеры задач, дела и связей (задачи 22–24), поэтому объявлен
# здесь, а не по месту: объявленный в каждом роутере отдельно, он приезжал бы в схему с
# разными описаниями, и в сгенерированном клиенте один параметр выглядел бы по-разному.
# Шаблона нет намеренно: форму проверяет домен (`parse_task_key`), одинаково для REST
# и MCP; адресация мягкая — `trk-42` находит `TRK-42`.
TaskKeyPath = Annotated[
    str,
    Path(description="Task key `QUEUE-number`; matching ignores case", examples=["TRK-42"]),
]
