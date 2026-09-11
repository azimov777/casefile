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
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Оба контура: имя для сообщения об ошибке и файл. Дев — по умолчанию, прод — по `-f`.
COMPOSE_FILES = {
    "dev": PROJECT_ROOT / "docker-compose.yml",
    "prod": PROJECT_ROOT / "docker-compose.prod.yml",
}

#: Сервисы, которые не поднимают приложение и потому получают окружение мимо общего
#: якоря. `db` — сам PostgreSQL: реквизиты `POSTGRES_*` читает он, а приложение ходит по
#: собранному из них `TRACKER_DATABASE_URL`. `ui` и `updater` есть только у прод-контура,
#: который стал установкой одной строкой (TRK-58): образ интерфейса и обновлятор
#: установки, у каждого своё окружение.
FOREIGN_SERVICES = frozenset({"db", "ui", "updater"})

#: Сервис интерфейса и переменная, которой прод-контур называет ему файл с ключом.
UI_SERVICE = "ui"
UI_TOKEN_FILE = "TRACKER_UI_TOKEN_FILE"

#: Разовый сервис, выпускающий токен агенту этой машины.
AGENT_TOKEN_SERVICE = "agent-token"

#: Якорь с переменными, которые контур задаёт сервисам сам.
APP_ENVIRONMENT = "x-app-environment:"

#: Имя переменной окружения в блоке: `NAME: значение`.
ENV_NAME = re.compile(r"^\s*([A-Z][A-Z0-9_]*):", re.MULTILINE)

#: Сервис MCP: единственный, чей порт двигается снаружи целиком — и публикация, и то,
#: что слушает процесс внутри.
MCP_SERVICE = "mcp"

#: Подстановка порта MCP. Одно выражение на все места, где порт называется.
MCP_PORT = "${TRACKER_MCP_PORT:-8100}"

#: Разовый сервис, выпускающий ключ интерфейса. Его результат — файл, а не вывод.
LOCAL_TOKEN_SERVICE = "local-token"

#: Ключ команды, называющий файл с секретом.
OUTPUT_OPTION = "--output"

#: Рабочий каталог обоих образов: относительный путь команды считается от него.
WORKDIR = "/app"

#: Чем дев-контур возвращает записанный файл хозяину каталога, смонтированного с хоста:
#: он работает от root, узнаёт владельца прямо у каталога и отдаёт файл ему. Прод-контур
#: на хост не пишет ничего — ключи у него живут в именованных томах.
DEV_OWNER_NAMED = ("chown", "$$(stat -c %u:%g /app)")


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
    бы зелёным. Исключения — сервисы, которые приложение не поднимают (`FOREIGN_SERVICES`).
    """
    strayed: list[str] = []
    for contour, path in COMPOSE_FILES.items():
        services = _services(path.read_text(encoding="utf-8"))

        assert len(services) > 3, f"{contour}: сервисы не разобраны — проверка ничего не стережёт"

        for name, body in services.items():
            if name in FOREIGN_SERVICES:
                continue
            described = "\n".join(body)
            if "<<: *app-service" not in described:
                strayed.append(f"{contour}, сервис {name}: не берёт общее описание сервиса")
            for own in ("environment:", "env_file:"):
                if own in described:
                    strayed.append(f"{contour}, сервис {name}: объявляет свой `{own}`")

    assert not strayed, strayed


def test_the_mcp_port_reaches_the_process_and_not_only_the_publication() -> None:
    """Порт MCP объявлен окружением контура, а не оставлен одному `.env`.

    Проброс compose разворачивает из окружения команды, а внутрь контейнера попадает
    только перечисленное в `environment` и в `env_file`. Переменная, оставленная одному
    файлу, двигает публикацию и не двигает сервер: `TRACKER_MCP_PORT=8101 docker compose
    -p tracker-check up -d mcp` публикует 8101, слушает 8100 и висит `unhealthy` — так
    это и нашлось (TRK-3#13, TRK-5).

    Проверяется не значение, а то, что все три места названы одной подстановкой:
    публикация, окружение процесса и проверка здоровья двигаются вместе или не двигаются
    вовсе. Адрес публикации перед ними законен: прод-контур публикует только на петлю.
    """
    for contour, path in COMPOSE_FILES.items():
        text = path.read_text(encoding="utf-8")
        declared = [line.strip() for line in _block(text, APP_ENVIRONMENT)]
        service = _services(text)[MCP_SERVICE]
        health = [line for line in service if "/health" in line]

        assert f"TRACKER_MCP_PORT: {MCP_PORT}" in declared, (
            f"{contour}: порт MCP объявлен только файлом окружения — публикация сдвинется, "
            f"процесс останется прежним"
        )
        assert f'{MCP_PORT}:{MCP_PORT}"' in "\n".join(service), f"{contour}: {service}"
        assert health, f"{contour}: проверка здоровья {MCP_SERVICE} не разобрана"
        assert all(MCP_PORT in line for line in health), health


def _output_paths(body: list[str]) -> list[PurePosixPath]:
    """Файлы, которые команда сервиса называет ключом `--output`, — путями в контейнере.

    Относительный путь считается от рабочего каталога образа: он один у обоих контуров,
    и `--output .secrets/ui-token` означает `/app/.secrets/ui-token` в каждом.
    """
    paths: list[PurePosixPath] = []
    for line in body:
        if OUTPUT_OPTION not in line:
            continue
        output = PurePosixPath(line.split(OUTPUT_OPTION, 1)[1].split()[0])
        paths.append(output if output.is_absolute() else PurePosixPath(WORKDIR) / output)
    return paths


def _under(target: str, root: str) -> bool:
    """Лежит ли точка монтирования внутри каталога `root`."""
    return PurePosixPath(target).is_relative_to(PurePosixPath(root))


def _mounts(lines: list[str]) -> list[tuple[str, str]]:
    """Тома блока `volumes:` парами «источник, точка монтирования в контейнере».

    У анонимного тома источника нет: строка состоит из одной точки монтирования, и
    источник выходит пустым — `- /app/.venv` даёт `("", "/app/.venv")`. Права доступа
    третьей частью (`- ./.secrets:/app/.secrets:ro`) отбрасываются: точка монтирования
    от них не зависит.
    """
    mounts: list[tuple[str, str]] = []
    inside, base = False, 0
    for line in lines:
        stripped = line.strip()
        if stripped == "volumes:":
            inside, base = True, _indent(line)
            continue
        if inside and _indent(line) <= base:
            inside = False
        if inside and stripped.startswith("- "):
            parts = stripped[2:].split(":")
            mounts.append(("", parts[0]) if len(parts) == 1 else (parts[0], parts[1]))
    return mounts


def _from_host(source: str) -> bool:
    """Источник монтирования — путь на хосте, а не том Docker.

    Путь на хосте записан относительным (`./`, `.` — каталог репозитория или установки)
    или абсолютным (`/var/run/docker.sock` у обновлятора); имя тома с точки и косой черты
    не начинается никогда. Анонимный том источника не имеет вовсе.
    """
    return source.startswith((".", "/"))


def _mount_targets(lines: list[str]) -> set[str]:
    """Куда описание монтирует каталоги хоста: точки монтирования у источников с хоста.

    Именованные и анонимные тома отсеиваются: `pgdata:/var/lib/postgresql/data` живёт
    внутри Docker, и файл, попавший туда, хосту не виден.
    """
    return {target for source, target in _mounts(lines) if _from_host(source)}


def test_no_contour_mounts_anything_inside_a_directory_taken_from_the_host() -> None:
    """Внутри каталога, приехавшего с хоста, контур ничего больше не монтирует.

    Чтобы смонтировать что-нибудь в `/app/.venv`, Docker обязан иметь там каталог, и
    недостающий заводит сам — **в источнике монтирования, то есть прямо в репозитории на
    машине хозяина**, а на Linux от root. Хозяин получает каталог, в который не может
    писать, и появляется тот до всякой команды: возврат владельца, которым лечатся
    записанные файлы (`test_the_written_file_ends_up_owned_by_the_one_who_reads_it`),
    здесь не работает — писать туда некому.

    Правило поэтому не про `.venv`, а про вложенность: анонимный том `- /app/.venv`
    прятал окружение хоста и был снят задачей 53, когда замер показал, что прятать нечего
    (`sys.path` его не видит, набор тестов и линтер туда не заходят). Следующий
    `- /app/node_modules` стоил бы того же — и ловится этой проверкой, а не пересмотром
    решения.
    """
    for contour, path in COMPOSE_FILES.items():
        mounts = _mounts(_meaningful_lines(path.read_text(encoding="utf-8")))
        from_host = [target for source, target in mounts if _from_host(source)]

        # Сторожевое условие: без каталогов с хоста проверке не с чем сравнивать, и
        # промах разбора зеленил бы её молча — оба контура такой каталог объявляют:
        # дев-контур — репозиторий, прод-контур — каталог установки у обновлятора.
        assert from_host, f"{contour}: каталогов хоста не разобрано: {mounts}"

        for source, target in mounts:
            nested = [host for host in from_host if host != target and _under(target, host)]
            assert not nested, (
                f"{contour}: том `{source or 'анонимный'}` монтируется в {target} — "
                f"внутрь каталога {nested[0]}, приехавшего из репозитория хозяина. Docker "
                f"заведёт там каталог на машине хозяина, и хозяин не сможет в него писать"
            )


def _written_by(services: dict[str, list[str]], name: str, contour: str) -> PurePosixPath:
    """Единственный файл, который сервис называет ключом `--output`."""
    assert name in services, f"{contour}: сервиса {name} нет — установке нечем выдать ключ"
    written = _output_paths(services[name])
    assert len(written) == 1, f"{contour}: {OUTPUT_OPTION} в {name} не разобран: {written}"
    return written[0]


def test_the_dev_contour_hands_the_keys_to_the_host() -> None:
    """Ключ интерфейса и токен агента дев-контур кладёт в каталог, видимый хосту.

    Результат `local-token` и `agent-token` — файл, а не вывод: секрет команды не
    печатают никогда, и ничем, кроме файла, они не полезны. В разработке оттуда ключ
    берёт `pnpm dev` интерфейса, а токен — тот, кто подключает агента к MCP.

    Стоит пути указать мимо смонтированного каталога, и команда отработает с кодом 0,
    напечатает, что ключ выдан, и унесёт файл вместе с разовым контейнером. Установка при
    этом останется с действующим токеном, которого никто не знает, — то есть молчаливым
    отказом, каких у выдачи ключа быть не должно.
    """
    text = COMPOSE_FILES["dev"].read_text(encoding="utf-8")
    services = _services(text)
    shared = _mount_targets(_block(text, "x-app-service:"))

    for name in (LOCAL_TOKEN_SERVICE, AGENT_TOKEN_SERVICE):
        output = _written_by(services, name, "dev")
        mounted = shared | _mount_targets(services[name])

        # Сторожевой проверки на пустоту здесь нет намеренно: промах разбора даёт пустое
        # множество, а пустое множество валит саму проверку — зеленить ей нечего.
        assert any(str(parent) in mounted for parent in output.parents), (
            f"dev, {name}: {output} лежит вне каталогов хоста {sorted(mounted)} — "
            f"файл ключа не переживёт разовый контейнер, причём молча"
        )


def test_the_prod_contour_hands_the_ui_key_to_the_ui_through_a_named_volume() -> None:
    """Прод-контур держит ключи в именованных томах, и ключ интерфейса доходит до `ui`.

    Хоста у установки одной строкой нет: ни исходников, ни каталога под секреты. Ключ
    `local-token` пишет в именованный том, `ui` монтирует тот же том и получает путь к
    файлу переменной — промах в любом из трёх мест поднимает интерфейс без ключа, то есть
    с экраном входа там, где его быть не должно, и без единой ошибки в журнале.

    Токен агента лежит в своём томе, и `ui` его не монтирует: интерфейсу он не нужен, а
    держать секрет набора `main` там, где его можно не держать, незачем.
    """
    services = _services(COMPOSE_FILES["prod"].read_text(encoding="utf-8"))

    def volume_holding(name: str) -> str:
        output = _written_by(services, name, "prod")
        holders = [
            source
            for source, target in _mounts(services[name])
            if any(parent == PurePosixPath(target) for parent in output.parents)
        ]
        assert len(holders) == 1, f"prod, {name}: {output} не лежит ни в одном томе сервиса"
        assert not _from_host(holders[0]), f"prod, {name}: ключ уходит на хост ({holders[0]})"
        return holders[0]

    ui_key = volume_holding(LOCAL_TOKEN_SERVICE)
    agent_key = volume_holding(AGENT_TOKEN_SERVICE)
    ui_mounts = dict(_mounts(services[UI_SERVICE]))

    assert ui_key in ui_mounts, f"prod: {UI_SERVICE} не монтирует том ключа {ui_key}"
    key_name = _written_by(services, LOCAL_TOKEN_SERVICE, "prod").name
    expected = PurePosixPath(ui_mounts[ui_key]) / key_name
    described = [line.strip() for line in services[UI_SERVICE]]
    assert f"{UI_TOKEN_FILE}: {expected}" in described, (
        f"prod: {UI_SERVICE} ищет ключ не там, куда кладёт {LOCAL_TOKEN_SERVICE} ({expected})"
    )
    assert agent_key != ui_key
    assert agent_key not in ui_mounts, f"prod: токен агента доступен {UI_SERVICE}"


def _services_writing_onto_the_host(text: str) -> dict[str, str]:
    """Сервисы, чей файл из `--output` ложится в каталог, смонтированный с хоста."""
    shared = _mount_targets(_block(text, "x-app-service:"))
    writing: dict[str, str] = {}
    for name, body in _services(text).items():
        mounted = shared | _mount_targets(body)
        for output in _output_paths(body):
            if any(str(parent) in mounted for parent in output.parents):
                writing[name] = "\n".join(body)
                break
    return writing


def test_the_written_file_ends_up_owned_by_the_one_who_reads_it() -> None:
    """Файл, положенный дев-контуром на машину хозяина, достаётся хозяину, а не root.

    Процесс контейнера пишет файл своим uid, и на Linux этот же uid стоит владельцем
    файла на хосте: bind-mount владельца не подменяет. Дев-контур работает от root —
    и хозяин установки получает собственный каталог, из которого не может ни прочитать
    ключ (`cat .secrets/ui-token` из README отвечает отказом), ни удалить его. На macOS
    слой обмена файлами Docker Desktop владельца подменяет, поломки там нет вовсе, и
    зелёный прогон на такой машине про права не говорит ничего (TRK-52#5).

    Root узнаёт хозяина прямо у смонтированного каталога и возвращает файл ему — без
    переменной, чьё умолчание годилось бы не всякой машине: контур обязан подниматься
    одной командой без подготовки. Прод-контуру правило не нужно: на хост он не пишет
    вовсе (`test_the_prod_contour_writes_nothing_onto_the_host`).

    Стережёт проверка тех, кто называет файл ключом `--output`. Кеши инструментов сюда
    не попадают, и они выведены за пределы репозитория совсем: `cache-dir` линтера и
    `cache_dir` набора тестов задают путь мимо смонтированного каталога.
    """
    writing = _services_writing_onto_the_host(COMPOSE_FILES["dev"].read_text(encoding="utf-8"))

    assert writing, "dev: сервисы, пишущие файл на машину хозяина, не разобраны"

    for name, described in writing.items():
        unnamed = [mark for mark in DEV_OWNER_NAMED if mark not in described]

        assert not unnamed, (
            f"dev, сервис {name}: файл ложится на машину хозяина, "
            f"владельца ему никто не назначает ({unnamed}) — на Linux файл "
            f"останется тому, кто писал, недоступным хозяину установки"
        )


def test_the_prod_contour_writes_nothing_onto_the_host() -> None:
    """Установка одной строкой не кладёт на машину пользователя ни одного файла.

    Каталог хоста у неё один — каталог установки, смонтированный обновлятору, — и пишет
    туда только он сам, освежая compose-файл. Разовый сервис с `--output` в каталог хоста
    вернул бы все беды с владельцем файла, от которых прод-контур ушёл на именованные тома
    (`docs/notes/docker.md`, «Права на bind-mount»).
    """
    text = COMPOSE_FILES["prod"].read_text(encoding="utf-8")

    assert _output_paths([line for body in _services(text).values() for line in body]), (
        "prod: ни одного `--output` не разобрано — проверка ничего не стережёт"
    )
    assert _services_writing_onto_the_host(text) == {}
