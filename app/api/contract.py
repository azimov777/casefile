"""Контракт публичного API, выраженный кодом, а не только текстом соглашений.

Здесь живут две вещи, которые до задачи 17 существовали только как проза в
`docs/CONVENTIONS.md` и потому расходились с реальностью молча:

- **список исключений из единой оболочки ответа**. Сплошная проверка
  (`tests/test_api_contract.py`) исключает маршруты по нему, а не по молчаливому
  пропуску: новое исключение нельзя завести, не назвав причину рядом с кодом;
- **справочник кодов ошибок**. Классы исключений намеренно живут в трёх местах —
  предметные в `app/domain/errors.py`, механизменные рядом со своим механизмом
  (`app/db/pagination.py`, `app/db/session.py`), базовые семейства в
  `app/core/errors.py`. Читать их врозь фронтенду незачем, поэтому справочник собирает
  их в один список; `docs/ERRORS.md` — его же выгрузка, которую делает
  `python -m app.cli errors`.

Модуль принадлежит слою `api`, потому что и то и другое — свойства **публичного
контракта**, а не предметной области: за пределами HTTP ни оболочка ответа, ни
HTTP-статус ошибки смысла не имеют. Слою это позволяет импортировать всё, что ниже, —
без этого справочник не мог бы дотянуться до ошибок, объявленных в `db`.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass

# Импорт ради загрузки: справочник собирается обходом наследников `AppError`, а класс
# попадает в список наследников только после того, как его модуль импортирован. Без
# этих трёх строк справочник был бы неполным молча — то есть ровно тем, от чего он
# заводится. Полноту сторожит `tests/test_api_contract.py`: он обходит весь пакет `app`
# и требует, чтобы ни один класс ошибки не оказался вне справочника.
from app.api import errors as api_errors
from app.core.errors import AppError
from app.db import pagination as _pagination  # noqa: F401
from app.db import session as _session  # noqa: F401
from app.domain import errors as _domain_errors  # noqa: F401

#: Коды ответа, у которых тела нет по определению, — первое исключение из оболочки.
BODYLESS_STATUS_CODES = frozenset({"204"})

#: Маршруты, чей успешный ответ не завёрнут в `data`. Ключ — метод и путь, значение —
#: причина. Список закрытый: соглашения называют ровно эти исключения, и добавление
#: третьего сюда обязано сопровождаться правкой `docs/CONVENTIONS.md`.
ENVELOPE_EXEMPT: dict[tuple[str, str], str] = {
    ("GET", "/health"): (
        "Health check for Docker and monitoring. It lives outside /api/v1 and is not "
        "part of the frontend contract, so it answers with a flat body"
    ),
    ("GET", "/api/v1/events/stream"): (
        'Server-sent events. Wrapping an SSE frame into {"data": ...} stops it from '
        "being SSE, so the envelope is impossible here rather than skipped. The frame "
        "payload is still typed (StreamEventRead), and the same schema is served with "
        "the usual envelope by GET /api/v1/events"
    ),
}


@dataclass(frozen=True, slots=True)
class ErrorCode:
    """Одна строка справочника ошибок."""

    code: str
    #: HTTP-статус ответа. `None` — у запасного кода, который может прийти с любым.
    status_code: int | None
    message: str
    summary: str
    origin: str

    @property
    def is_transport(self) -> bool:
        """Код приходит от транспорта, а не из кода приложения.

        У таких кодов нет своего класса исключения: их выдаёт обработчик
        `StarletteHTTPException`, когда маршрута нет или метод не поддержан.
        """
        return self.origin == _TRANSPORT_ORIGIN


_TRANSPORT_ORIGIN = "app/api/errors.py"

# Коды, у которых нет класса исключения: приложение их не бросает — их порождает
# роутер, не разобравший тело или не нашедший метода. Описания заданы здесь вручную
# по той же причине. Коды, которые транспорт делит с классом (`not_found`,
# `unauthorized`, `conflict`, ...), сюда не входят: справочник называет каждый код
# один раз, а объяснение обеих его причин живёт в строке документации класса.
_TRANSPORT_CODES: dict[str, str] = {
    "bad_request": "Запрос синтаксически неверен: тело не разбирается как JSON.",
    "method_not_allowed": "Маршрут есть, но этого метода у него нет.",
    "http_error": (
        "Запасной код для статуса, которого нет в таблице соглашений. Появление такого "
        "ответа означает пропущенную ветку, а не рабочее состояние."
    ),
}


def error_catalog() -> tuple[ErrorCode, ...]:
    """Все коды ошибок контракта одним списком, по алфавиту.

    Собирается обходом наследников `AppError`, а не перечислением руками: список,
    который надо пополнять вручную, отстаёт от кода с первого же нового исключения, и
    отстаёт незаметно.
    """
    entries = [_entry(error_class) for error_class in _error_classes()]
    entries.extend(
        ErrorCode(
            code=code,
            status_code=status_code,
            message=api_errors.HTTP_MESSAGES[status_code],
            summary=_TRANSPORT_CODES[code],
            origin=_TRANSPORT_ORIGIN,
        )
        for status_code, code in sorted(api_errors.HTTP_STATUS_CODES.items())
        if code in _TRANSPORT_CODES
    )
    entries.append(
        ErrorCode(
            code="http_error",
            status_code=None,
            message="Request error",
            summary=_TRANSPORT_CODES["http_error"],
            origin=_TRANSPORT_ORIGIN,
        )
    )
    return tuple(sorted(entries, key=lambda entry: entry.code))


def declared_error_classes() -> set[type[AppError]]:
    """Все классы ошибок, объявленные в пакете `app`, найденные обходом модулей.

    Нужна одному тесту — тому, что стережёт полноту справочника. Обход пакета там, а не
    в самом справочнике, намеренно: импортировать весь `app` ради списка кодов значит
    поднимать вместе с ним и настройки, и модели, и реестр правил, а справочник читают в
    том числе из командной строки на непромигрированной базе.
    """
    import app

    for module in pkgutil.walk_packages(app.__path__, "app."):
        if module.name.startswith("app.db.migrations"):
            # Ревизии Alembic исполняются отдельным процессом и ошибок контракта не
            # объявляют; импортировать их ради обхода — значит тянуть в тест `env.py`.
            continue
        importlib.import_module(module.name)
    return set(_error_classes())


def _error_classes() -> list[type[AppError]]:
    """Наследники `AppError` вместе с ним самим, без повторов.

    Только объявленные в пакете `app`. Отбор по модулю обязателен: обход наследников
    видит **любой** класс, объявленный где угодно в процессе, — в том числе в тестовом
    модуле, который заводит своего наследника ради проверки перевода ошибки в ответ.
    Без отбора справочник менялся бы от того, какие модули успел импортировать процесс:
    прогон одного файла и прогон всего набора давали бы разные списки кодов, и один из
    них был бы неверным.
    """
    found: dict[str, type[AppError]] = {}

    def walk(error_class: type[AppError]) -> None:
        module = error_class.__module__
        if module == "app" or module.startswith("app."):
            found[f"{module}.{error_class.__qualname__}"] = error_class
        # Обход продолжается и через отсеянный класс: наследоваться от чужого
        # исключения приложению никто не запрещал.
        for child in error_class.__subclasses__():
            walk(child)

    walk(AppError)
    return list(found.values())


def _entry(error_class: type[AppError]) -> ErrorCode:
    return ErrorCode(
        code=error_class.code,
        status_code=error_class.status_code,
        message=error_class.message,
        summary=_summary(error_class),
        origin=error_class.__module__.replace(".", "/") + ".py",
    )


def _summary(error_class: type[AppError]) -> str:
    """Первый абзац строки документации класса — описание «когда это возникает».

    Первый абзац, а не вся строка: у половины ошибок за ним следует объяснение принятого
    решения, полезное читателю кода и лишнее в справочнике.
    """
    doc = (error_class.__doc__ or "").strip()
    paragraph = doc.split("\n\n", 1)[0]
    return " ".join(paragraph.split())


#: Шапка сгенерированного справочника. Отдельной константой, чтобы текст, объясняющий
#: происхождение файла, лежал рядом с кодом, который его порождает.
_ERRORS_HEADER = """# Справочник кодов ошибок

<!--
Файл создаётся командой, править руками нельзя:

    docker compose run --rm schema

Источник — классы исключений в коде (`app/api/contract.py`, `error_catalog`).
Расхождение файла с кодом ловит `tests/test_api_contract.py`.
-->

Любая ошибка приходит одной оболочкой, независимо от эндпоинта:

```json
{"error": {"code": "issue_not_found",
           "message": "Issue TRK-123 not found",
           "details": {}}}
```

Решения клиент принимает по `code`: он стабилен и меняется только вместе с версией API.
`message` — техническая фраза для разработчика и лога, показывать её пользователю не
нужно; текст интерфейса фронтенд выбирает сам по коду. `details` — структурированные
подробности: какое поле, какое правило, какие значения допустимы.

Коды перечислены по HTTP-статусу, внутри статуса — по алфавиту."""

_STATUS_TITLES = {
    400: "400 — запрос не разобран",
    401: "401 — не аутентифицирован",
    403: "403 — запрещено",
    404: "404 — не найдено",
    405: "405 — метод не поддержан",
    409: "409 — конфликт состояния",
    422: "422 — не прошло проверку",
    429: "429 — слишком часто",
    500: "500 — внутренняя ошибка",
    503: "503 — сервис недоступен",
}


def render_error_catalog() -> str:
    """Справочник в виде Markdown — содержимое `docs/ERRORS.md`.

    Рендер живёт рядом со справочником, а не в команде: так текст файла и данные, из
    которых он собран, нельзя разнести по разным правкам и получить документ, который
    выглядит свежим и врёт.
    """
    catalog = error_catalog()
    lines = [_ERRORS_HEADER, ""]
    fallback = [entry for entry in catalog if entry.status_code is None]
    for status_code in sorted({entry.status_code for entry in catalog} - {None}):
        assert status_code is not None
        lines.append(f"## {_STATUS_TITLES.get(status_code, str(status_code))}")
        lines.append("")
        lines.append("| Код | Сообщение | Когда возникает |")
        lines.append("|---|---|---|")
        for entry in catalog:
            if entry.status_code != status_code:
                continue
            lines.append(f"| `{entry.code}` | {entry.message} | {entry.summary} |")
        lines.append("")
    if fallback:
        lines.append("## Любой статус")
        lines.append("")
        lines.append("| Код | Сообщение | Когда возникает |")
        lines.append("|---|---|---|")
        lines.extend(
            f"| `{entry.code}` | {entry.message} | {entry.summary} |" for entry in fallback
        )
        lines.append("")
    return "\n".join(lines)
