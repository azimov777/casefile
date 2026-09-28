"""Версия продукта одна — в `pyproject.toml`; всё, что её называет, с ней совпадает (TRK-374)."""

import json
import tomllib
from pathlib import Path

from app import __version__
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["project"]["version"]


def test_app_version_is_the_product_version() -> None:
    assert __version__ == _pyproject_version()


def test_api_schema_names_the_product_version() -> None:
    assert create_app().openapi()["info"]["version"] == _pyproject_version()


def test_shipped_openapi_json_names_the_product_version() -> None:
    """Выпуск поднял версию, а `openapi.json` не пересобран — красный тест."""
    shipped = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))

    assert shipped["info"]["version"] == _pyproject_version()


def test_prod_image_carries_pyproject_next_to_the_code() -> None:
    """Версию читают из `pyproject.toml`; без файла в образе приложение не запустится."""
    dockerfile = (ROOT / "docker" / "Dockerfile.prod").read_text(encoding="utf-8")
    runtime = dockerfile.split("AS runtime", 1)[1]

    assert "pyproject.toml" in runtime
