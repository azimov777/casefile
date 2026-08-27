"""Командная строка приложения.

Нужна для того, чего нельзя сделать через API: завести первого владельца и выпустить
ему первый токен. Все эндпоинты `/api/v1` требуют токена, поэтому без такой команды
свежая установка оставалась бы запертой снаружи.

Запуск в контуре разработки:

    docker compose run --rm init
    docker compose run --rm --entrypoint python api -m app.cli issue-token --actor owner

Команды идут через `session_scope`: транзакцию фиксирует та же граница, что и у
HTTP-запроса, отдельной логики коммита здесь нет.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import dispose_engine, session_scope
from app.domain.actors import ActorType
from app.services import actors as service

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
