"""Командная строка приложения.

Нужна для того, чего нельзя сделать через API:

- `init` — первичная инициализация: завести владельца и выпустить ему первый токен
  набора `main`. Все эндпоинты `/api/v1` требуют токена, поэтому без такой команды
  свежая установка оставалась бы запертой снаружи;
- `issue-token` — выпустить токен напрямую. Это способ вернуть себе доступ, потеряв
  секрет: `init` на уже работающей установке ничего не создаёт;
- `local-token` — положить действующий ключ набора `main` в файл, откуда его берёт
  интерфейс локальной установки: человек там и есть её владелец. Ключ добывает сама
  установка, а не человек, поэтому секрет не печатается никогда: команда стоит в
  журнале подъёма контура. Годный ключ другого набора в файле она заменяет;
- `agent-token` — то же для агента этой машины: токен набора `main` в файле, откуда его
  берёт тот, кто подключает агента к MCP (установщик `install.sh`);
- `password-hash` — напечатать хеш пароля владельца для `TRACKER_PASSWORD_HASH`: так
  установку закрывают паролем перед тем, как выставить в сеть (`docs/CONCEPT.md`, 5.4).
  Пароль спрашивается с терминала без эха (или читается строкой из трубы), наружу уходит
  только хеш. Базы команда не касается;
- `demo` — наполнить установку демонстрационными данными: очередь `DEMO`, задачи во всех
  статусах и дела со всеми типами записей. Через API это были бы десятки запросов
  в нужном порядке;
- `openapi` и `errors` — выгрузить поставляемые артефакты контракта: схему для
  генерации клиента и справочник кодов ошибок.

Запуск в контуре разработки:

    docker compose run --rm init
    docker compose run --rm local-token
    docker compose run --rm agent-token
    docker compose run --rm demo
    docker compose run --rm schema
    docker compose run --rm --entrypoint python api -m app.cli issue-token --scope main
    docker compose run --rm --no-deps --entrypoint python api -m app.cli password-hash

Команды идут через `session_scope`: транзакцию фиксирует та же граница, что и у
HTTP-запроса, отдельной логики коммита здесь нет.

## Кто печатает секрет, а кто нет

`init` и `issue-token` печатают: секрет читает человек, и другого способа его получить
нет. `local-token` и `agent-token` не печатают никогда — их вывод уезжает в журнал
подъёма контура, а секрет в журнале это тот же секрет на виду, от которого весь этот
путь и уходит. Секрет попадает **только** в файл `--output`, и права на нём `0600`.
"""

import argparse
import asyncio
import getpass
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import dispose_engine, session_scope
from app.domain.passwords import WeakPasswordError, check_new_password, hash_password
from app.domain.tokens import TokenScope
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from app.services.setup import (
    DEFAULT_AGENT_NAME,
    DEFAULT_AGENT_TOKEN_NAME,
    DEFAULT_LOCAL_TOKEN_NAME,
    DEFAULT_OWNER_DESCRIPTION,
    DEFAULT_OWNER_NAME,
    DEFAULT_TOKEN_NAME,
    LocalToken,
    LocalTokenOutcome,
    ensure_agent_token,
    ensure_local_token,
    initialize_installation,
)

#: Права файла с ключом: читает и пишет только владелец. Файл лежит на машине человека
#: рядом с репозиторием, и `0644` означал бы, что рабочий доступ к трекеру читает любой
#: процесс любого пользователя этой машины.
SECRET_FILE_MODE = 0o600

#: Сценарий, приводящий файл с секретом в согласие с установкой: `ensure_local_token`
#: или `ensure_agent_token`.
type EnsureToken = Callable[..., Awaitable[LocalToken]]


async def _init(args: argparse.Namespace) -> int:
    """Готовит свежую установку к работе: владелец и его первый токен набора `main`.

    Идемпотентна и молчалива на повторе: если в базе уже есть хоть один токен, команда
    ничего не создаёт и говорит об этом. Так её можно держать в Compose рядом с
    миграциями, не боясь, что случайный повторный запуск наплодит действующие доступы.
    """
    async with session_scope() as session:
        issued = await initialize_installation(
            session,
            name=args.name,
            description=args.description,
            token_name=args.token_name,
        )
        if issued is None:
            print("Installation is already initialized: at least one token exists.")
            print("Nothing was created. To get a new token, run:")
            print("  python -m app.cli issue-token --participant <name> --scope main")
            return 0

        participant = issued.token.participant
        assert participant is not None  # выпущен именной токен, участник у него есть
        print(f"participant: {participant.name} ({participant.kind.value})")
        print(f"token name:  {issued.token.name}")
        print(f"token scope: {issued.token.scope.value}")
        print()
        print("This token is shown once, store it now:")
        print(f"  {issued.secret}")
        print()
        print("Check it:")
        print(f'  curl -H "Authorization: Bearer {issued.secret}" \\')
        print("       http://localhost:8000/api/v1/participants")
    return 0


async def _issue_token(args: argparse.Namespace) -> int:
    """Выпускает токен: участнику или общий агентский, если участник не назван.

    Единственный путь к доступу, когда все секреты набора `main` потеряны, — `init` на
    работающей установке уже ничего не выпускает.
    """
    async with session_scope() as session:
        participant = (
            None
            if args.participant is None
            else await participants_service.get_participant(session, args.participant)
        )
        issued = await tokens_service.issue_token(
            session,
            actor=TRACKER_ACTOR,
            participant=participant,
            scope=TokenScope(args.scope),
            name=args.name,
        )
        owner = "shared agent token" if participant is None else participant.name
        print(f"participant: {owner}")
        print(f"scope:       {issued.token.scope.value}")
        print(f"token:       {issued.secret}")
        if participant is None:
            print()
            print("Shared token: every request must carry the X-Actor-Label header.")
    return 0


async def _local_token(args: argparse.Namespace) -> int:
    """Кладёт в файл действующий ключ интерфейса локальной установки.

    Идемпотентна по файлу, а не по базе, и иначе быть не может: в базе лежит хеш, и
    секрет уже выпущенного токена не восстановить. Поэтому файл здесь — единственная
    постоянная копия, и повторный подъём контура видит в нём годный ключ и не трогает
    ничего.

    Файл пишется **до** коммита, внутри границы транзакции. Обратный порядок при упавшей
    записи оставил бы в базе действующий секрет, которого никто не знает; при этом —
    мёртвый секрет в файле, который следующий запуск просто заменит.

    Годный ключ другого набора в файле — не повод молчать: сценарий заменяет его ключом
    набора `main` и отзывает прежний (`ensure_local_token`), и файл переписывается.
    """
    return await _keep_in_file(args, ensure_local_token)


async def _agent_token(args: argparse.Namespace) -> int:
    """Кладёт в файл действующий токен агента этой машины — тем же путём, что ключ интерфейса."""
    return await _keep_in_file(args, ensure_agent_token)


async def _keep_in_file(args: argparse.Namespace, ensure: EnsureToken) -> int:
    """Сверяет файл `--output` с установкой и пишет туда секрет, если выпущен новый."""
    path = Path(args.output)
    async with session_scope() as session:
        result = await ensure(
            session,
            known_secret=_read_secret(path),
            participant_name=args.participant,
            token_name=args.name,
        )
        if result.secret is not None:
            _write_secret(path, result.secret)
        _report_local_token(result, path)
    return 0


def _read_secret(path: Path) -> str | None:
    """Секрет из прежнего файла или `None`, если файла нет.

    Испорченное содержимое читается как обычная строка и `None` не даёт: годность
    решает база, найдя (или не найдя) такой хеш, а не разбор файла здесь. Ошибки доступа
    (каталог вместо файла, нет прав) намеренно не глушатся — это не «файла нет», а
    неверно настроенный контур, и молчать о нём хуже, чем упасть.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or None
    except FileNotFoundError:
        return None


def _write_secret(path: Path, secret: str) -> None:
    """Пишет секрет в файл, доступный только владельцу, без перевода строки в конце.

    Права выставляются при создании, а не после записи: между `open` и `chmod` файл с
    рабочим доступом был бы читаем всей машиной. `chmod` следом всё же нужен — он
    приводит к тем же правам уже существующий файл, которому `os.open` режим не меняет.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SECRET_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)
    os.chmod(path, SECRET_FILE_MODE)


def _report_local_token(result: LocalToken, path: Path) -> None:
    """Печатает, что случилось и куда лёг ключ. Секрета в этом выводе нет никогда."""
    participant = result.token.participant
    assert participant is not None  # выпущен именной токен, участник у него есть
    print(
        {
            LocalTokenOutcome.KEPT: "The installation already has a working local token.",
            LocalTokenOutcome.INITIALIZED: (
                "The installation was empty: the owner is in place and the first token is issued."
            ),
            LocalTokenOutcome.REISSUED: "No working local token was found, a new one is issued.",
            LocalTokenOutcome.RESCOPED: (
                "The local token worked but had another scope: "
                f"a {result.token.scope.value} one replaces it."
            ),
        }[result.outcome]
    )
    if result.revoked:
        print(f"revoked:     {result.revoked} previous token(s)")
    print(f"participant: {participant.name} ({participant.kind.value})")
    print(f"token name:  {result.token.name}")
    print(f"token scope: {result.token.scope.value}")
    print(f"file:        {path} (mode 0600, the secret and nothing else)")
    print()
    print("Check it without printing the secret:")
    print(f'  curl -H "Authorization: Bearer $(cat {path})" \\')
    print("       http://localhost:8000/api/v1/bootstrap")


async def _password_hash(args: argparse.Namespace) -> int:
    """Печатает строку `TRACKER_PASSWORD_HASH=...` для `.env` установки.

    Пароль не попадает ни в аргументы команды (их видно в списке процессов и в истории
    оболочки), ни в вывод: с терминала он читается без эха и дважды, из трубы — первой
    строкой. В стандартный вывод уходит ровно одна строка с хешем, пояснения — в поток
    ошибок, поэтому вывод можно дописать в файл как есть.
    """
    if sys.stdin.isatty():
        password = getpass.getpass("Owner password: ")
        if getpass.getpass("Repeat it: ") != password:
            print("The two passwords differ; nothing was printed.", file=sys.stderr)
            return 1
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    try:
        check_new_password(password)
    except WeakPasswordError as exc:
        print(f"weak_password: {exc}", file=sys.stderr)
        return 1

    print(f"TRACKER_PASSWORD_HASH={hash_password(password).render()}")
    print(
        "Put this line into .env next to docker-compose.prod.yml and run "
        "`docker compose up -d`. The password itself is stored nowhere.",
        file=sys.stderr,
    )
    return 0


async def _demo(args: argparse.Namespace) -> int:
    """Наполняет установку демонстрационными данными.

    Идемпотентна так же, как `init`, и по той же причине: команда стоит в Compose рядом
    с миграциями, и её повторный запуск не должен плодить вторую копию очереди `DEMO`.
    Признак «уже наполнено» — существование самой очереди.
    """
    from app.services.demo import DEMO_QUEUE_KEY, seed_demo

    async with session_scope() as session:
        data = await seed_demo(session)
        if not data.created:
            print(f"Demo data is already there: queue {DEMO_QUEUE_KEY} exists.")
            print("Nothing was created. To start over, drop the database volume:")
            print("  docker compose down -v")
            return 0

        assert data.queue is not None  # `created` — это и есть «очередь заведена»
        print(f"queue: {data.queue.key} ({data.queue.title})")
        for task in data.tasks:
            print(f"  {task.key}  {task.status.value:<12} {task.title}")
        print()
        print("Open the first screen with the token from `init`:")
        print('  curl -H "Authorization: Bearer trk_..." \\')
        print("       http://localhost:8000/api/v1/bootstrap")
    return 0


async def _openapi(args: argparse.Namespace) -> int:
    """Выгружает схему OpenAPI — поставляемый артефакт, из которого фронтенд берёт типы.

    Собирается тем же кодом, который отдаёт `/openapi.json`, и не требует ни базы, ни
    поднятого сервера: схема — свойство кода, а не работающей установки.
    """
    # Импорт внутри команды, а не в начале модуля: `create_app` тянет за собой роутеры
    # и настройки, а команды `init` и `issue-token` обходятся без них.
    from fastapi.openapi.utils import get_openapi

    from app.main import create_app

    app = create_app()
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    _write(args.output, json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    return 0


async def _errors(args: argparse.Namespace) -> int:
    """Выгружает справочник кодов ошибок в Markdown."""
    from app.api.contract import render_error_catalog

    _write(args.output, render_error_catalog())
    return 0


def _write(output: str | None, text: str) -> None:
    """Пишет результат в файл или в стандартный вывод, если файл не назван."""
    if output is None:
        print(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"written: {path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Tracker maintenance")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init",
        help="Register the owner and issue the first main token on an empty installation",
    )
    init.add_argument("--name", default=DEFAULT_OWNER_NAME, help="Owner participant name")
    init.add_argument("--description", default=DEFAULT_OWNER_DESCRIPTION, help="Owner description")
    init.add_argument("--token-name", default=DEFAULT_TOKEN_NAME, help="Name for the issued token")
    init.set_defaults(handler=_init)

    issue = commands.add_parser("issue-token", help="Issue an API token")
    issue.add_argument(
        "--participant",
        default=None,
        help="Participant name; omit to issue a shared agent token",
    )
    issue.add_argument(
        "--scope",
        default=TokenScope.TASK.value,
        choices=[scope.value for scope in TokenScope],
        help="Token scope",
    )
    issue.add_argument("--name", default="cli", help="Name for the issued token")
    issue.set_defaults(handler=_issue_token)

    local = commands.add_parser(
        "local-token",
        help="Keep a working main-scope token in a file for the local UI; never prints it",
    )
    # Путь обязателен: умолчание пути к файлу с рабочим секретом — ровно то неявное
    # поведение, из-за которого секрет однажды оказывается там, где его не искали.
    local.add_argument("--output", required=True, help="File to keep the secret in, mode 0600")
    local.add_argument(
        "--participant",
        default=DEFAULT_OWNER_NAME,
        help="Participant to issue the token to; registered only on an empty installation",
    )
    local.add_argument(
        "--name",
        default=DEFAULT_LOCAL_TOKEN_NAME,
        help="Name for the issued token; a live token with the same name is revoked",
    )
    local.set_defaults(handler=_local_token)

    agent = commands.add_parser(
        "agent-token",
        help="Keep a working main-scope token for this machine's agent in a file; never prints it",
    )
    agent.add_argument("--output", required=True, help="File to keep the secret in, mode 0600")
    agent.add_argument(
        "--participant",
        default=DEFAULT_AGENT_NAME,
        help="Agent participant to issue the token to; registered when missing",
    )
    agent.add_argument(
        "--name",
        default=DEFAULT_AGENT_TOKEN_NAME,
        help="Name for the issued token; a live token with the same name is revoked",
    )
    agent.set_defaults(handler=_agent_token)

    password = commands.add_parser(
        "password-hash",
        help="Print TRACKER_PASSWORD_HASH for the owner password; asks it without echo",
    )
    password.set_defaults(handler=_password_hash)

    demo = commands.add_parser(
        "demo",
        help="Fill the installation with demo data: queue DEMO, tasks in every status",
    )
    demo.set_defaults(handler=_demo)

    schema = commands.add_parser("openapi", help="Dump the OpenAPI schema")
    schema.add_argument("--output", default=None, help="File to write; stdout when omitted")
    schema.set_defaults(handler=_openapi)

    errors = commands.add_parser("errors", help="Dump the error code reference as Markdown")
    errors.add_argument("--output", default=None, help="File to write; stdout when omitted")
    errors.set_defaults(handler=_errors)

    return parser


async def _run(
    handler: Callable[[argparse.Namespace], Awaitable[int]], args: argparse.Namespace
) -> int:
    """Выполняет команду и гарантированно закрывает пул соединений."""
    try:
        return await handler(args)
    except AppError as error:
        # Доменная ошибка в командной строке — это понятное сообщение и код возврата,
        # а не стек вызовов: команду запускают в чужом окружении и читают её вывод.
        print(f"{error.code}: {error.message}", file=sys.stderr)
        if error.details:
            print(f"details: {error.details}", file=sys.stderr)
        return 1
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args.handler, args))


if __name__ == "__main__":
    raise SystemExit(main())
