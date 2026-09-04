"""Контуры запуска: до приложения в обоих доезжает одно и то же окружение.

Соглашения требуют от дев- и прод-контура «один и тот же набор переменных окружения»
(`docs/CONVENTIONS.md`, раздел «Запуск»). До задачи 34 требование не выполнялось молча:
прод-образ `.env` не содержит (`.dockerignore`), тома с исходниками у него нет, и до
приложения доходило только то, что `docker-compose.prod.yml` перечислял сам. Владелец
прод-установки правил `.env` по инструкции README и не получал ничего.

Сверка идёт по самим compose-файлам, а не по списку имён, записанному здесь: список в
коде теста расходится с контуром так же тихо, как разошлись контуры между собой.

Полного разбора YAML в файле нет намеренно — зависимость ради одного теста в проект не
тянется. Разбор держится на том, что compose-файлы написаны руками с обычным отступом,
а промах разбора ловят сторожевые проверки: пустой блок валит тест, а не зеленит его.
"""

import re
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Оба контура: имя для сообщения об ошибке и файл. Дев — по умолчанию, прод — по `-f`.
COMPOSE_FILES = {
    "dev": PROJECT_ROOT / "docker-compose.yml",
    "prod": PROJECT_ROOT / "docker-compose.prod.yml",
}

#: Сервис базы данных. Он единственный получает окружение мимо общего якоря: реквизиты
#: `POSTGRES_*` поднимают сам PostgreSQL, а приложение их не читает — оно ходит по
#: собранному из них `TRACKER_DATABASE_URL`.
DATABASE_SERVICE = "db"

#: Якорь с переменными, которые контур задаёт сервисам сам.
APP_ENVIRONMENT = "x-app-environment:"

#: Имя переменной окружения в блоке: `NAME: значение`.
ENV_NAME = re.compile(r"^\s*([A-Z][A-Z0-9_]*):", re.MULTILINE)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _meaningful_lines(text: str) -> list[str]:
    """Строки файла без пустых и без комментариев: их отступ ни о чём не говорит."""
    lines = (line for line in text.splitlines() if line.strip())
    return [line for line in lines if not line.lstrip().startswith("#")]


def _block(text: str, header: str) -> list[str]:
    """Строки, вложенные в строку `header`: всё под ней с бо́льшим отступом.

    Ключ обязан встречаться в файле ровно один раз — иначе непонятно, какой из блоков
    сравнивается с соседним контуром, и проверка начинает стеречь не то место.
    """
    lines = _meaningful_lines(text)
    starts = [number for number, line in enumerate(lines) if line.strip().startswith(header)]

    assert len(starts) == 1, f"ключ `{header}` встречается {len(starts)} раз вместо одного"

    start = starts[0]
    base = _indent(lines[start])
    body: list[str] = []
    for line in lines[start + 1 :]:
        if _indent(line) <= base:
            break
        body.append(line)
    return body


def _application_variables(text: str) -> set[str]:
    """Имена переменных, которые контур задаёт сервисам приложения сам."""
    return set(ENV_NAME.findall("\n".join(_block(text, APP_ENVIRONMENT))))


def _env_file_declaration(text: str) -> tuple[str, ...]:
    """Объявление `env_file`: какой файл подключается и обязателен ли он."""
    return tuple(line.strip() for line in _block(text, "env_file:"))


def _by_contour[T](extract: Callable[[str], T]) -> dict[str, T]:
    """Разбор обоих файлов рядом: дев и прод сравниваются прямо, без промежуточных имён."""
    return {
        contour: extract(path.read_text(encoding="utf-8"))
        for contour, path in COMPOSE_FILES.items()
    }


def _services(text: str) -> dict[str, list[str]]:
    """Сервисы контура: имя и строки его описания."""
    services: dict[str, list[str]] = {}
    name = ""
    for line in _block(text, "services:"):
        if _indent(line) == 2 and line.rstrip().endswith(":"):
            name = line.strip().rstrip(":")
            services[name] = []
        else:
            services[name].append(line)
    return services


def test_both_contours_name_the_same_variables_themselves() -> None:
    """Набор переменных, который контур задаёт сервисам сам, одинаков в обоих.

    Именно эти переменные побеждают `.env` (в Compose `environment` приоритетнее
    `env_file`), поэтому лишняя строка в одном контуре — это настройка, которую владелец
    другого правит в файле и не может изменить, не понимая почему.
    """
    named = _by_contour(_application_variables)

    assert named["dev"], "блок переменных дев-контура не разобран — проверка ничего не стережёт"
    assert named["dev"] == named["prod"], sorted(named["dev"] ^ named["prod"])


def test_both_contours_read_the_same_env_file() -> None:
    """`.env` подключается объявленно и одинаково: тот же файл, та же необязательность.

    Дев-контур когда-то читал файл случайно — репозиторий смонтирован томом целиком, и
    pydantic-settings находил его как `/app/.env`. Прод-образ файла не содержит, и
    объявления не было ни у одного контура.
    """
    declared = _by_contour(_env_file_declaration)

    assert any(".env" in line for line in declared["dev"]), declared["dev"]
    assert declared["dev"] == declared["prod"], declared


def test_every_application_service_takes_the_shared_environment() -> None:
    """Окружение приложения объявлено в контуре один раз — общим якорём.

    Без этого две проверки выше стерегут пустое место: сервис со своим `environment:`
    получил бы переменную, которой нет у соседнего контура, а сравнение якорей осталось
    бы зелёным. Исключение одно — `db`: он поднимает PostgreSQL, а не приложение.
    """
    strayed: list[str] = []
    for contour, path in COMPOSE_FILES.items():
        services = _services(path.read_text(encoding="utf-8"))

        assert len(services) > 3, f"{contour}: сервисы не разобраны — проверка ничего не стережёт"

        for name, body in services.items():
            if name == DATABASE_SERVICE:
                continue
            described = "\n".join(body)
            if "<<: *app-service" not in described:
                strayed.append(f"{contour}, сервис {name}: не берёт общее описание сервиса")
            for own in ("environment:", "env_file:"):
                if own in described:
                    strayed.append(f"{contour}, сервис {name}: объявляет свой `{own}`")

    assert not strayed, strayed
