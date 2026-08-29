"""Подключение к PostgreSQL: движок, фабрика сессий и способы её получить.

Движок создаётся лениво и живёт один на процесс: пул соединений нельзя создавать
на каждый запрос. Тесты движок не трогают — они подменяют зависимость `get_session`.

Граница транзакции описана ровно один раз — в `session_scope`. `get_session` это та же
граница, поданная как зависимость FastAPI. Расходиться двум путям некуда: HTTP-запрос,
воркер outbox и скрипт фиксируют изменения одним и тем же кодом.

Правило простое: вызывающий код завершился без исключения — коммит, вылетело исключение —
откат. Сценарий в `services` может коммитить и сам, если ему нужна промежуточная фиксация,
но обязанности помнить про финальный коммит у него нет.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(url: str | None = None) -> AsyncEngine:
    """Создаёт новый движок. Отдельная функция — чтобы тесты могли поднять свой."""
    settings = get_settings()
    return create_async_engine(
        url or str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )


def asyncpg_dsn(url: str | None = None) -> str:
    """Адрес БД в виде, который понимает сам драйвер, без диалекта SQLAlchemy.

    Нужен там, где соединение открывается мимо движка: слушателю оповещений об
    уведомлениях и тестовой фикстуре, создающей базу. Замена префикса живёт здесь, а
    не по месту, по тому же правилу, что и всё остальное в этом файле: две копии
    разъехались бы, и одна из них однажды перестала бы понимать адрес с параметрами.
    """
    return (url or str(get_settings().database_url)).replace(
        "postgresql+asyncpg://",
        "postgresql://",
    )


def get_engine() -> AsyncEngine:
    """Движок приложения, единый на процесс."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий приложения."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def dispose_engine() -> None:
    """Закрывает пул соединений. Вызывается при остановке приложения."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


class DatabaseUnavailableError(AppError):
    """База не отвечает. Отдельный код, чтобы мониторинг отличал это от прочих пятисоток.

    Живёт рядом с механизмом, а не в `app/domain/errors.py`: предметной области здесь
    нет — есть соединение с базой. По тому же правилу рядом со своим механизмом живут
    ошибки курсора и размера страницы (`app/db/pagination.py`). Читать все коды разом
    от этого не тяжелее: их собирает справочник `app/api/contract.py`.
    """

    code = "database_unavailable"
    status_code = 503
    message = "Database is unavailable"


def integrity_conflict(exc: IntegrityError) -> ConflictError:
    """Нарушение ограничения целостности — это конфликт состояния, а не пятисотка.

    Дубликат ключа, ссылка на удалённую строку, нарушенная проверка — всё это ответ
    базы на состояние данных, и клиенту важно отличить его от сбоя сервера: по `409` он
    перечитает объект и повторит запрос, по `500` — позовёт разработчика.

    Наружу уходит только имя ограничения, а не текст ошибки драйвера: в нём бывают
    значения строк, которым в ответе делать нечего. Имя ограничения задано соглашением
    об именах (`app/db/base.py`), поэтому оно устойчиво и полезно в отладке.
    """
    constraint = _constraint_name(exc)
    details: dict[str, Any] = {"reason": "integrity_violation"}
    if constraint is not None:
        details["constraint"] = constraint
    return ConflictError(message="Database constraint violated", details=details)


#: SQLSTATE `undefined_table`: обращение к таблице, которой в базе нет.
UNDEFINED_TABLE = "42P01"


def schema_is_missing(exc: Exception) -> bool:
    """Ошибка означает «миграции ещё не применены», а не сбой.

    Контур поднимается до миграций — они отдельный шаг, а не часть старта нескольких
    реплик, — и первые секунды таблиц в базе нет вовсе. Для процессов, синхронизирующих
    реестр правил при старте, это ожидаемое состояние: они повторяют попытку и
    дожидаются схемы. Отличать его нужно ровно затем, чтобы не писать полноэкранную
    трассировку на каждый круг: десяток трассировок за минуту — это шум, из-за которого
    настоящую ошибку старта не заметят.

    Признак — SQLSTATE, а не текст сообщения: текст зависит от версии драйвера и локали
    сервера, код `42P01` не зависит ни от чего.

    Проверка узкая намеренно. «Таблицы нет» — единственное состояние, которое при
    штатном порядке запуска случается обязательно. Отсутствующая колонка или тип
    означают, что миграции применены не до конца, а это уже настоящая поломка, и
    трассировка ей полагается.
    """
    return _sqlstate(exc) == UNDEFINED_TABLE


def _sqlstate(exc: Exception) -> str | None:
    """Код ошибки PostgreSQL из исключения драйвера, если драйвер его сообщил.

    Обход цепочки тот же, что у `_constraint_name`, и по той же причине: у asyncpg
    настоящая ошибка лежит в `__cause__` обёртки SQLAlchemy.
    """
    original = getattr(exc, "orig", None)
    for candidate in (original, getattr(original, "__cause__", None)):
        code = getattr(candidate, "sqlstate", None)
        if code:
            return str(code)
    return None


def _constraint_name(exc: IntegrityError) -> str | None:
    """Имя нарушенного ограничения из исключения драйвера, если драйвер его сообщил.

    У asyncpg настоящая ошибка лежит в `__cause__` обёртки SQLAlchemy; у других
    драйверов атрибута может не быть вовсе, поэтому доступ защищённый.
    """
    for candidate in (exc.orig, getattr(exc.orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if name:
            return str(name)
    return None


async def commit(session: AsyncSession) -> None:
    """Фиксирует транзакцию и переводит нарушение ограничения в доменный конфликт.

    Единственное место, где выполняется `commit`. Ошибка целостности здесь особенно
    коварна: отложенные ограничения (`DEFERRABLE INITIALLY DEFERRED`) роняют не запрос,
    а именно коммит, и без перевода клиент получил бы голую пятисотку вместо понятного
    `conflict`.
    """
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise integrity_conflict(exc) from exc


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия с транзакцией: единственное место, где живёт граница фиксации изменений.

    Используется напрямую воркерами outbox, планировщиком автодействий и скриптами;
    HTTP-запросы получают её через `get_session`. Менять поведение транзакции нужно
    здесь — второго такого места в проекте нет.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await commit(session)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: тот же `session_scope`, поданный как зависимость.

    Обработчик отработал без исключения — коммит; вылетело любое исключение, включая
    доменное, — откат. Одна и та же функция сервиса, вызванная из REST, из MCP и из
    воркера, фиксируется одинаково, потому что фиксирует её один и тот же код.

    Момент коммита у HTTP-запроса сдвинут вперёд объявлением зависимости:
    `SessionDep` в `app/api/deps.py` просит область `function`. Без неё FastAPI закрыл
    бы зависимость уже после отправки ответа, и упавший коммит было бы некуда доложить.
    Поведение от этого не меняется — меняется только момент.
    """
    async with session_scope() as session:
        yield session
