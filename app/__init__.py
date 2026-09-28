"""Бэкенд таск-трекера."""

import tomllib
from pathlib import Path

# Версия продукта живёт в одном месте — `pyproject.toml`; здесь она только читается.
# Проект в окружение образов не ставится (код приезжает файлами или томом), поэтому
# `importlib.metadata` версии не знает, а файл лежит рядом с пакетом и в дев-, и в
# прод-образе (`docker/Dockerfile.prod` копирует его в `/app`).
__version__: str = tomllib.loads(
    (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
