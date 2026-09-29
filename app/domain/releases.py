"""Выпуски Casefile: номер версии и сравнение «установка отстаёт» (TRK-416).

Выпуск — git-тег `vX.Y.Z` (`.github/workflows/images.yml`), версия установки —
`X.Y.Z` из `pyproject.toml`. Сравниваются числа, а не строки: строкой `0.10.0` меньше
`0.9.0`. Всё, что под `X.Y.Z` не подходит (пре-релиз `v0.8.0-rc.1`, чужой тег), не
разбирается, и обновления по нему нет: лучше промолчать, чем позвать на то, что не
выпуск канала `stable`.
"""

import re
from dataclasses import dataclass

#: Где живут выпуски. Страница выпуска и адрес API строятся от этого имени.
RELEASES_REPOSITORY = "azimov777/casefile"

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse_version(text: str) -> tuple[int, int, int] | None:
    """`v0.7.0` и `0.7.0` — `(0, 7, 0)`; что угодно другое — `None`."""
    match = _VERSION.fullmatch(text.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


@dataclass(frozen=True, slots=True)
class Release:
    """Последний выпуск, как его назвал GitHub."""

    #: Номер без `v`: так версию называет и установка (`app.__version__`).
    version: str
    #: Страница выпуска с заметками к нему.
    url: str


def is_newer(release: Release, installed: str) -> bool:
    """Выпуск новее установленной версии. Неразобранная любая из двух — нет."""
    latest = parse_version(release.version)
    current = parse_version(installed)
    return latest is not None and current is not None and latest > current
