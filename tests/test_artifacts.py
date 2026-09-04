"""Поставляемые артефакты контракта: схема, справочник ошибок и документ фронтенду.

Артефакт, который отстал от кода, хуже отсутствующего: по нему генерируют клиент и
принимают решения, не перепроверяя. Свежесть `docs/ERRORS.md` стережёт
`tests/test_api_contract.py`; здесь — свежесть `openapi.json` и то, что документ
фронтенду не обещает маршрутов, которых нет.

Почему схема вообще лежит в репозитории. До задачи 29 её намеренно не хранили: вторая
копия отстаёт от первой. Отставание сняли тестом ниже, а взамен фронтенд — отдельный
репозиторий — берёт схему из git и генерирует клиент, не поднимая Docker.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.contract import declared_error_classes, error_catalog
from app.domain.errors import TaskNotFoundError
from app.mcp.errors import describe
from conftest import Connect, refuse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_FILE = PROJECT_ROOT / "openapi.json"
FRONTEND_DOC = PROJECT_ROOT / "docs" / "FRONTEND.md"

#: Как схема выгружается командой `python -m app.cli openapi`. Форматирование —
#: часть сравнения: файл, отличающийся только отступами, всё равно расходится с
#: выгрузкой, и «пересобрать» будет непонятно зачем.
DUMP_KWARGS: dict[str, Any] = {"ensure_ascii": False, "indent": 2}

#: Путь API в тексте документа. Строка обрывается на первом символе, которого в пути
#: быть не может: `?` начинает параметры запроса, а обратная кавычка и пробел —
#: окружающий текст.
API_PATH_PATTERN = re.compile(r"/api/v1[A-Za-z0-9_/{}-]*")


@pytest.fixture
def schema(app: FastAPI) -> dict[str, Any]:
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


# --- Схема OpenAPI -----------------------------------------------------------------


def test_the_committed_schema_matches_the_code(schema: dict[str, Any]) -> None:
    """Обзорная проверка 1: `openapi.json` в репозитории равен выгруженному.

    Пересобрать: `docker compose run --rm schema`. Расхождение означает, что маршрут
    поменялся, а артефакт, из которого фронтенд генерирует клиент, — нет.
    """
    assert OPENAPI_FILE.exists(), (
        "openapi.json нет в репозитории; выгрузить: docker compose run --rm schema"
    )
    committed = OPENAPI_FILE.read_text(encoding="utf-8")

    assert committed == json.dumps(schema, **DUMP_KWARGS) + "\n", (
        "openapi.json устарел, пересобрать: docker compose run --rm schema"
    )


def test_the_first_screen_is_in_the_schema(schema: dict[str, Any]) -> None:
    """`bootstrap` — вход интерфейса, и в схеме он обязан быть первым, что видно."""
    operation = schema["paths"]["/api/v1/bootstrap"]["get"]

    assert operation["operationId"] == "read_bootstrap"
    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert body["$ref"].endswith("/DataResponse_BootstrapRead_")


# --- Документ фронтенду ------------------------------------------------------------


def test_every_path_the_frontend_doc_names_exists(schema: dict[str, Any]) -> None:
    """Обзорная проверка 2: каждый путь из `FRONTEND.md` есть в схеме.

    Документ читают до того, как поднимут бэкенд, и путь из него уезжает прямо в код
    интерфейса. Опечатка или переименованный маршрут стоят разработчику фронтенда
    получаса на `404`, из которых двадцать девять минут уходят на подозрение своей
    авторизации.
    """
    named = set(API_PATH_PATTERN.findall(FRONTEND_DOC.read_text(encoding="utf-8")))
    declared = set(schema["paths"])

    assert named, "документ не называет ни одного пути — регулярное выражение промахнулось"
    assert named <= declared, sorted(named - declared)


# --- Справочник ошибок и слой MCP ---------------------------------------------------


def test_the_mcp_layer_declares_no_error_codes_of_its_own() -> None:
    """Слой MCP не заводит своих кодов — он отдаёт агенту те же, что и REST.

    Проверка нужна именно как проверка, а не как обещание: справочник собирается
    обходом наследников `AppError`, и класс, объявленный в `app/mcp/`, попал бы в него
    молча — вместе с HTTP-статусом, которого у инструмента нет. Ошибка инструмента —
    это перевод доменной ошибки в текст (`app/mcp/errors.py`), и другой она быть
    не должна.
    """
    own = sorted(
        error_class.__name__
        for error_class in declared_error_classes()
        if error_class.__module__.startswith("app.mcp")
    )

    assert not own, f"слой MCP объявил свои классы ошибок: {own}"


def test_the_tool_error_text_starts_with_the_code_from_the_reference() -> None:
    """Агент видит только текст, и первым в нём стоит тот же код, что и в `ERRORS.md`."""
    text = describe(TaskNotFoundError(details={"key": "TRK-1"}))
    code = text.split(":", 1)[0]

    assert code in {entry.code for entry in error_catalog()}
    assert text.startswith("task_not_found: Task not found")
    assert '"key": "TRK-1"' in text


async def test_a_refused_tool_call_names_a_code_from_the_reference(
    mcp_session: Connect, task_secret: str
) -> None:
    """Тот же справочник годится агенту: отказ инструмента приходит его кодом.

    Через настоящий клиент, а не вызовом `describe`: между доменной ошибкой и текстом,
    который увидит модель, лежат обработчик SDK и свёртка результата, и потерять код
    можно ровно там.

    Код ищется **внутри** текста, а не в его начале: SDK приписывает спереди свою
    строку `Error executing tool <имя>: `, и текст `describe` начинается только после
    неё (`docs/notes/mcp.md`).
    """
    catalog = {entry.code: entry.message for entry in error_catalog()}

    async with mcp_session(task_secret) as session:
        text = await refuse(session, "get_task", key="NOPE-1")

    named = [code for code, message in catalog.items() if f"{code}: {message}" in text]
    assert named == ["task_not_found"], text


#: Заголовок таблицы кодов ошибок в `FRONTEND.md`. Проверка отталкивается от него, а не
#: от всех обратных кавычек документа: в тексте есть и имена полей, и значения
#: перечислений, и «код», найденный среди них, был бы ложным срабатыванием.
ERROR_TABLE_HEADER = "| Код | Когда |"


def _codes_named_in_the_frontend_doc() -> set[str]:
    """Коды из таблицы частых ошибок `FRONTEND.md`."""
    lines = FRONTEND_DOC.read_text(encoding="utf-8").splitlines()
    start = lines.index(ERROR_TABLE_HEADER) + 2  # заголовок и строка-разделитель
    codes: set[str] = set()
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        codes.update(re.findall(r"`([a-z][a-z0-9_]*)`", line.split("|")[1]))
    return codes


def test_every_error_code_the_frontend_doc_names_exists() -> None:
    """Код, которого нет, интерфейс будет ждать вечно — и покажет по нему свой текст.

    Ловится только сравнением со справочником: в документе такой код выглядит ровно
    так же, как настоящий, а в ответе не появляется никогда. Так в этом файле дожили до
    задачи 29 `question_not_found` и `question_already_answered`, которых в трекере нет.
    """
    named = _codes_named_in_the_frontend_doc()
    known = {entry.code for entry in error_catalog()}

    assert named, "таблица кодов не разобрана — проверка ничего не стережёт"
    assert named <= known, sorted(named - known)
