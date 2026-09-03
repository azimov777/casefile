"""Командная строка приложения.

Нужна для того, чего нельзя сделать через API:

- `init` — первичная инициализация: завести владельца и выпустить ему первый токен
  набора `main`. Все эндпоинты `/api/v1` требуют токена, поэтому без такой команды
  свежая установка оставалась бы запертой снаружи;
- `issue-token` — выпустить токен напрямую. Это способ вернуть себе доступ, потеряв
  секрет: `init` на уже работающей установке ничего не создаёт;
- `openapi` и `errors` — выгрузить поставляемые артефакты контракта: схему для
  генерации клиента и справочник кодов ошибок.

Запуск в контуре разработки:

    docker compose run --rm init
    docker compose run --rm schema
    docker compose run --rm --entrypoint python api -m app.cli issue-token --scope main

Команды идут через `session_scope`: транзакцию фиксирует та же граница, что и у
HTTP-запроса, отдельной логики коммита здесь нет.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import dispose_engine, session_scope
from app.domain.tokens import TokenScope
from app.services import participants as participants_service
from app.services import tokens as tokens_service
from app.services.auth import TRACKER_ACTOR
from app.services.setup import (
    DEFAULT_OWNER_DESCRIPTION,
    DEFAULT_OWNER_NAME,
    DEFAULT_TOKEN_NAME,
    initialize_installation,
)


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
