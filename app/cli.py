"""Командная строка приложения.

Нужна для того, чего нельзя сделать через API:

- `init` — завести первого владельца и выпустить ему первый токен. Все эндпоинты
  `/api/v1` требуют токена, поэтому без такой команды свежая установка оставалась бы
  запертой снаружи;
- `issue-token` — выпустить токен существующему актору;
- `openapi` и `errors` — выгрузить поставляемые артефакты контракта: схему для
  генерации клиента и справочник кодов ошибок;
- `demo` — наполнить установку осмысленными данными, чтобы фронтенд разрабатывался не
  на пустой базе;
- `cleanup` — удалить из растущих журналов то, что старше срока хранения. Через API
  такого действия нет и быть не должно: это обслуживание установки, а не сценарий.

Запуск в контуре разработки:

    docker compose run --rm init
    docker compose run --rm schema
    docker compose run --rm demo
    docker compose run --rm cleanup
    docker compose run --rm --entrypoint python api -m app.cli issue-token --actor owner

Команды идут через `session_scope`: транзакцию фиксирует та же граница, что и у
HTTP-запроса, отдельной логики коммита здесь нет.
"""

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import dispose_engine, session_scope
from app.domain.actors import ActorType
from app.services import actors as service
from app.services import demo as demo_service
from app.services import retention as retention_service

DEFAULT_OWNER_KEY = "owner"
DEFAULT_OWNER_NAME = "Owner"


async def _init(args: argparse.Namespace) -> int:
    """Готовит свежую установку к работе: владелец и его первый токен.

    Идемпотентна: повторный запуск не падает и второго владельца не создаёт. Токен при
    этом всё равно выпускается новым — старый секрет восстановить неоткуда, а команда
    нужна в том числе как способ вернуть себе доступ.
    """
    async with session_scope() as session:
        system = await service.get_system_actor(session)
        owner, created = await service.ensure_actor(
            session,
            actor_type=ActorType.HUMAN,
            key=args.key,
            display_name=args.name,
        )
        issued = await service.issue_token(session, owner, initiator=system, name=args.token_name)

        state = "created" if created else "already exists"
        print(f"system actor: {system.key} ({system.display_name})")
        print(f"owner actor:  {owner.key} ({owner.display_name}) - {state}")
        print(f"token name:   {issued.token.name}")
        print()
        print("This token is shown once, store it now:")
        print(f"  {issued.secret}")
        print()
        print("Check it:")
        print(f'  curl -H "Authorization: Bearer {issued.secret}" \\')
        print("       http://localhost:8000/api/v1/actors/me")
    return 0


async def _issue_token(args: argparse.Namespace) -> int:
    """Выпускает токен существующему актору — например, только что заведённому агенту."""
    async with session_scope() as session:
        system = await service.get_system_actor(session)
        actor = await service.get_actor_by_key(session, args.actor)
        issued = await service.issue_token(session, actor, initiator=system, name=args.name)
        print(f"actor: {actor.key} ({actor.display_name})")
        print(f"token: {issued.secret}")
    return 0


async def _openapi(args: argparse.Namespace) -> int:
    """Выгружает схему OpenAPI — поставляемый артефакт, из которого фронтенд берёт типы.

    Собирается тем же кодом, который отдаёт `/openapi.json`, и не требует ни базы, ни
    поднятого сервера: схема — свойство кода, а не работающей установки.
    """
    # Импорт внутри команды, а не в начале модуля: `create_app` тянет за собой роутеры,
    # реестр правил и настройки, а команды `init` и `issue-token` обходятся без них.
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


async def _demo(args: argparse.Namespace) -> int:
    """Наполняет установку демо-данными через обычные сценарии.

    Прямых вставок в базу здесь нет намеренно: на данных, положенных мимо сценариев, не
    проверить ни историю изменений, ни автоматику, ни уведомления — то есть ровно то,
    ради чего демо-контур и нужен.

    Повторный запуск отказывает вместо того, чтобы доложить недостающее: набор — это
    связный граф задач, связей и рангов, и «долить» его нельзя, не заведя механику
    сложнее самого набора. Отказ громкий: молча создать вторую копию половины объектов
    было бы хуже любой ошибки.
    """
    async with session_scope() as session:
        if await demo_service.demo_is_present(session):
            print(
                "demo data is already here: queues "
                f"{demo_service.DEV_QUEUE_KEY} or {demo_service.OPS_QUEUE_KEY} exist.",
                file=sys.stderr,
            )
            print(
                "start over with a fresh database: docker compose down -v && "
                "docker compose up -d && docker compose run --rm migrate",
                file=sys.stderr,
            )
            return 1
        report = await demo_service.seed_demo(session)
    for line in report.lines():
        print(line)
    return 0


async def _cleanup(args: argparse.Namespace) -> int:
    """Удаляет из трёх растущих журналов то, что старше срока хранения.

    Сроки задаются переменными окружения (`TRACKER_RETENTION_*`), размер пачки и
    потолок прохода можно перебить флагами: пачка — часть контракта команды, а не
    внутренняя деталь, и на разной по мощности базе она разная.

    `--dry-run` считает подходящие строки и ничего не удаляет. На установке, где
    чистка запускается впервые, начинать стоит с него: числа покажут, во что обойдётся
    настоящий проход.
    """
    policy = retention_service.policy_from_settings()
    overrides: dict[str, int] = {}
    if args.batch_size is not None:
        overrides["batch_size"] = args.batch_size
    if args.max_batches is not None:
        overrides["max_batches"] = args.max_batches
    if overrides:
        # `replace` проверяет значения тем же `__post_init__`, что и построение из
        # настроек: флаг с нулём или отрицательным числом отвергается, а не выполняется.
        policy = dataclasses.replace(policy, **overrides)

    async with session_scope() as session:
        report = await retention_service.cleanup(session, policy=policy, dry_run=args.dry_run)
    for line in report.lines():
        print(line)
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

    init = commands.add_parser("init", help="Create the owner actor and issue its first token")
    init.add_argument("--key", default=DEFAULT_OWNER_KEY, help="Owner actor key")
    init.add_argument("--name", default=DEFAULT_OWNER_NAME, help="Owner display name")
    init.add_argument("--token-name", default="bootstrap", help="Name for the issued token")
    init.set_defaults(handler=_init)

    issue = commands.add_parser("issue-token", help="Issue an API token for an existing actor")
    issue.add_argument("--actor", required=True, help="Actor key")
    issue.add_argument("--name", default="cli", help="Name for the issued token")
    issue.set_defaults(handler=_issue_token)

    schema = commands.add_parser("openapi", help="Dump the OpenAPI schema")
    schema.add_argument("--output", default=None, help="File to write; stdout when omitted")
    schema.set_defaults(handler=_openapi)

    errors = commands.add_parser("errors", help="Dump the error code reference as Markdown")
    errors.add_argument("--output", default=None, help="File to write; stdout when omitted")
    errors.set_defaults(handler=_errors)

    demo = commands.add_parser("demo", help="Fill the installation with demo data")
    demo.set_defaults(handler=_demo)

    cleanup = commands.add_parser(
        "cleanup",
        help="Delete journal rows older than the configured retention",
    )
    cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be deleted and delete nothing",
    )
    cleanup.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Rows one DELETE removes; overrides TRACKER_RETENTION_BATCH_SIZE",
    )
    cleanup.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Batches per target in this pass; overrides TRACKER_RETENTION_MAX_BATCHES",
    )
    cleanup.set_defaults(handler=_cleanup)

    return parser


async def _run(
    handler: Callable[[argparse.Namespace], Awaitable[int]], args: argparse.Namespace
) -> int:
    """Выполняет команду и гарантированно закрывает пул соединений."""
    try:
        return await handler(args)
    except ValueError as error:
        # Негодная политика чистки приходит сюда: `RetentionPolicy` проверяет свои
        # значения сама, и флаг команды проходит ту же проверку, что и настройка.
        print(f"invalid_argument: {error}", file=sys.stderr)
        return 1
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
