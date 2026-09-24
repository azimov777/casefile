"""`server.json` — карточка Casefile в официальном реестре MCP.

Файл лежит в корне репозитория и подаётся утилитой `mcp-publisher` на каждый тег выпуска
(`.github/workflows/mcp-registry.yml`, TRK-133): версию в нём workflow подставляет из
тега прямо перед публикацией, руками её не правят. Схема, под которую подан Casefile
(«custom installation path» — без `packages`/`remotes`, TRK-83, decision #6), не связана
с кодом приложения, поэтому здесь проверяется только сам файл — против официальной схемы
реестра.

Схема `2025-12-11` вендорится в `tests/data/mcp-server-schema-2025-12-11.json`: файл по
этому адресу датирован и неизменен (следующая версия схемы легла бы под другой датой), а
тест обязан оставаться зелёным без сети (`docs/CONVENTIONS.md`, набор поднимает только
БД). Актуальность самой схемы под датой в имени сверяет `finding` в деле TRK-83 при
следующей подаче в реестр — не этот тест.
"""

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_JSON = PROJECT_ROOT / "server.json"
SCHEMA_FILE = Path(__file__).resolve().parent / "data" / "mcp-server-schema-2025-12-11.json"
SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

#: Версия семантическая либо семантическая с претегом (`1.0.2`, `2.1.0-alpha`) — так же,
#: как её проверяет сам реестр (описание поля `version` в схеме).
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


@pytest.fixture
def server_json() -> dict[str, Any]:
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def registry_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def test_server_json_exists() -> None:
    assert SERVER_JSON.exists(), "server.json нет в корне репозитория (TRK-133)"


def test_server_json_declares_the_vendored_schema_version(server_json: dict[str, Any]) -> None:
    """`$schema` называет ровно ту версию, что вендорится в `tests/data/`.

    Расхождение здесь означает, что кто-то поднял схему в файле, не подвезя новую
    вендорную копию, — и тест ниже проверял бы устаревшие требования, не заметив этого.
    """
    assert server_json["$schema"] == SCHEMA_URL


def test_server_json_matches_the_registry_schema(
    server_json: dict[str, Any], registry_schema: dict[str, Any]
) -> None:
    """Обзорная проверка 1 (TRK-133): файл проходит официальную схему `2025-12-11`."""
    jsonschema.validate(server_json, registry_schema)


def test_server_json_names_the_registry_namespace(server_json: dict[str, Any]) -> None:
    """Имя владеет пространством `io.github.azimov777/*` — вход в реестр только через
    GitHub-подтверждение владения этим репозиторием (TRK-83)."""
    assert server_json["name"] == "io.github.azimov777/casefile"


def test_server_json_points_at_the_project_repository(server_json: dict[str, Any]) -> None:
    repository = server_json["repository"]

    assert repository["url"] == "https://github.com/azimov777/casefile"
    assert repository["source"] == "github"
    assert repository["id"] == "1365843878"


def test_server_json_has_no_packages_or_remotes(server_json: dict[str, Any]) -> None:
    """Self-hosted контур — не пакет и не публичный удалённый адрес (TRK-83, decision #6).

    `packages` описал бы Casefile так, будто его ставят одной командой из npm/PyPI/OCI;
    `remotes` — так, будто у него есть публичный адрес, на который можно просто прийти.
    Ни то ни другое не верно: подъём требует `docker compose -f docker-compose.prod.yml
    up -d` с базой рядом, и об этом установке рассказывает `websiteUrl`, а не эти поля.
    """
    assert "packages" not in server_json
    assert "remotes" not in server_json


def test_server_json_version_is_a_placeholder_the_workflow_overwrites(
    server_json: dict[str, Any],
) -> None:
    """Версия в закоммиченном файле — памятка о последнем выпуске, а не источник истины.

    `.github/workflows/mcp-registry.yml` подставляет версию из тега (`vX.Y.Z` → `X.Y.Z`)
    прямо перед публикацией и не коммитит правку обратно, поэтому тест проверяет только
    форму значения, а не то, что оно совпадает с последним тегом: иначе каждый выпуск
    требовал бы отдельного коммита этого файла, а задача 133 именно это и снимает.
    """
    assert VERSION_PATTERN.match(server_json["version"]), server_json["version"]
