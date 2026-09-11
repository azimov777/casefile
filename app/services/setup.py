"""Первичная настройка установки: первый доступ человеку, ключ интерфейсу, токен агенту.

Свежая база заперта снаружи: каждый маршрут `/api/v1` требует токена, а выпустить
первый токен через API нельзя — для этого уже нужен токен. Разомкнуть круг может только
код, работающий с базой напрямую, поэтому сценарии живут здесь, а команды
`python -m app.cli init`, `local-token` и `agent-token` — тонкие обёртки над ними
(их же зовут одноимённые сервисы в Compose).

Сценариев три, и разница между ними — в том, кто хранит секрет.

| Сценарий | Кому доступ | Набор | Где живёт секрет |
|---|---|---|---|
| `initialize_installation` | человеку, руками | `main` | у человека, показан один раз |
| `ensure_local_token` | интерфейсу установки | `task` | в файле, который держит установка |
| `ensure_agent_token` | агенту машины, через MCP | `main` | в файле, который держит установка |

Повтор не выпускает ничего ни у одного, но признаки «уже сделано» разные: у первого это
наличие любого токена в базе, у двух других — годный секрет в своём файле.

Автор всего заведённого — сам трекер (`TRACKER_ACTOR`): участника, который завёл бы
первого участника, в этот момент ещё не существует.
"""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.repositories import ParticipantRepository, TokenRepository
from app.domain.errors import ParticipantNotFoundError
from app.domain.participants import ParticipantKind, normalize_participant_name
from app.domain.tokens import TokenScope, hash_token
from app.services.auth import TRACKER_ACTOR
from app.services.participants import register_participant
from app.services.tokens import IssuedToken, issue_token, revoke_token

DEFAULT_OWNER_NAME = "owner"
DEFAULT_OWNER_DESCRIPTION = "Владелец установки"
DEFAULT_TOKEN_NAME = "bootstrap"

#: Имя токена, который установка выпускает своему интерфейсу. По нему же находится
#: прежний токен, чтобы отозвать его при выпуске замены, — поэтому имя постоянное, а не
#: собранное из времени или случайного хвоста.
DEFAULT_LOCAL_TOKEN_NAME = "local-ui"

#: Участник, которому установка выпускает токен для MCP, и имя этого токена. Имя
#: постоянное по той же причине, что у ключа интерфейса: по нему отзывается прежний.
DEFAULT_AGENT_NAME = "agent"
DEFAULT_AGENT_DESCRIPTION = "Агент этой машины: ходит в MCP токеном, который выдала установка"
DEFAULT_AGENT_TOKEN_NAME = "local-agent"


async def initialize_installation(
    session: AsyncSession,
    *,
    name: str = DEFAULT_OWNER_NAME,
    description: str = DEFAULT_OWNER_DESCRIPTION,
    token_name: str = DEFAULT_TOKEN_NAME,
) -> IssuedToken | None:
    """Заводит участника-человека и выпускает ему токен набора `main`.

    `None` означает «установка уже инициализирована»: в базе есть хотя бы один токен, и
    сценарий не делает ничего. Признак — именно токен, а не участник: участник без
    токена доступа не даёт, и на такой базе установка осталась бы запертой.

    Почему повтор не выпускает новый токен, хотя это было бы удобно: команда идёт в
    Compose рядом с миграциями, и её случайный повторный запуск на работающей установке
    не должен плодить действующие доступы. Способ вернуть себе доступ, потеряв секрет,
    есть отдельный и явный — `python -m app.cli issue-token`.
    """
    if await TokenRepository(session).any_exists():
        return None

    owner = await register_participant(
        session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.HUMAN,
        name=name,
        description=description,
    )
    return await issue_token(
        session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name=token_name,
    )


class LocalTokenOutcome(StrEnum):
    """Что случилось с ключом локальной установки за один вызов `ensure_local_token`.

    Значений три, и они покрывают все состояния пары «файл — база»: годный секрет,
    пустая установка, всё остальное. Четвёртого исхода — «участника нет» — здесь нет
    намеренно: это не исход, а отказ, и уходит он исключением.
    """

    #: Секрет из файла действует: не выпущено ничего.
    KEPT = "kept"
    #: Установка была пуста: выпущен первый токен, владелец заведён, если его не было.
    INITIALIZED = "initialized"
    #: Установка работает, а годного секрета не было: выпущена замена прежнему.
    REISSUED = "reissued"


@dataclass(frozen=True, slots=True)
class LocalToken:
    """Итог сверки файла с установкой.

    `secret` заполнен тогда и только тогда, когда исход не `KEPT`: секрет существует
    один раз, и отдавать его вызывающему, когда выпускать было нечего, значит выдумать
    значение, которого нет. Вызывающему поэтому не нужно разбирать исход, чтобы понять,
    надо ли перезаписывать файл, — достаточно `secret is not None`.
    """

    outcome: LocalTokenOutcome
    token: Token
    secret: str | None
    #: Сколько прежних токенов с тем же именем отозвано этим же действием.
    revoked: int


async def ensure_local_token(
    session: AsyncSession,
    *,
    known_secret: str | None,
    participant_name: str = DEFAULT_OWNER_NAME,
    token_name: str = DEFAULT_LOCAL_TOKEN_NAME,
) -> LocalToken:
    """Приводит установку к состоянию «у интерфейса есть действующий ключ набора `task`».

    `known_secret` — то, что вызывающий нашёл в своей постоянной копии (для команды это
    файл; `None` — копии нет). Про файлы сценарий не знает ничего: он отвечает, что с
    найденным секретом делать, а хранит его вызывающий. Иначе слой сценариев пришлось
    бы учить путям на диске ради одной команды.

    Почему постоянная копия вообще нужна и почему ею не может быть база: в базе лежит
    хеш (`app/domain/tokens.py`), и «показать выданный токен» невозможно ни при каких
    условиях. Значит идемпотентность подъёма строится вокруг файла, а база только
    отвечает, годен ли его секрет.

    Годным секрет считается ровно тогда, когда он найден по хешу, не отозван и за ним
    стоит участник. Ни набор, ни имя участника здесь не сверяются намеренно: файл —
    собственная копия установки, и лишние условия превращали бы «повторный подъём
    ничего не перевыпускает» в перевыпуск на ровном месте.

    Выпуская замену, сценарий тем же действием отзывает прежние неотозванные токены с
    тем же именем. Без этого потерянный файл оставлял бы на установке действующий
    секрет, которого не знает никто, — и с каждым подъёмом их становилось бы больше.

    Отказ один: названного участника нет, а установка не пуста (`participant_not_found`).
    Заводить второго участника на работающей установке команда не станет — опечатка в
    имени иначе тихо превращалась бы в нового человека с полным доступом к задачам.
    """
    tokens = TokenRepository(session)

    kept = await _kept_token(tokens, known_secret)
    if kept is not None:
        return LocalToken(outcome=LocalTokenOutcome.KEPT, token=kept, secret=None, revoked=0)

    # Признак «установка пуста» тот же, что у `initialize_installation`, и по той же
    # причине: участник без токена доступа не даёт. Считается он до выпуска — после
    # него любая установка непуста.
    empty = not await tokens.any_exists()

    participant = await ParticipantRepository(session).get_by_name(
        normalize_participant_name(participant_name)
    )
    if participant is None:
        if not empty:
            raise ParticipantNotFoundError(details={"name": participant_name})
        participant = await register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.HUMAN,
            name=participant_name,
            description=DEFAULT_OWNER_DESCRIPTION,
        )

    return await _replace_token(
        session, participant, token_name=token_name, scope=TokenScope.TASK, empty=empty
    )


async def ensure_agent_token(
    session: AsyncSession,
    *,
    known_secret: str | None,
    participant_name: str = DEFAULT_AGENT_NAME,
    token_name: str = DEFAULT_AGENT_TOKEN_NAME,
) -> LocalToken:
    """Приводит установку к состоянию «у агента этой машины есть действующий токен набора `main`».

    Нужен установке одной командой: агенту, которого человек подключает к MCP, токен
    выдаёт сама установка, как ключ интерфейсу, — а не `init`, печатающий секрет в
    журнал контейнера. Устроен как `ensure_local_token`: идемпотентен по файлу, признак
    годности тот же, замена отзывает прежний одноимённый токен. Отличий три.

    - Набор `main`, а не `task`: без него агент не заведёт даже первую очередь, а людей
      в интерфейсе, которым этот набор мог бы понадобиться, установка не спрашивает.
    - Участник-агент заводится, если его нет, на любой установке. Опечатки в имени
      человека, от которой стережёт `ensure_local_token`, здесь нет: имя называет
      контур, а завести агента этой машины и есть смысл первого запуска.
    - На пустой установке заводится и владелец-человек, без токена. Установка
      начинается с человека, и `ensure_local_token`, позванный следом, найдёт его, а не
      откажет, — порядок двух команд перестаёт иметь значение.
    """
    tokens = TokenRepository(session)

    kept = await _kept_token(tokens, known_secret)
    if kept is not None:
        return LocalToken(outcome=LocalTokenOutcome.KEPT, token=kept, secret=None, revoked=0)

    empty = not await tokens.any_exists()
    participants = ParticipantRepository(session)

    owner_name = normalize_participant_name(DEFAULT_OWNER_NAME)
    if empty and await participants.get_by_name(owner_name) is None:
        await register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.HUMAN,
            name=DEFAULT_OWNER_NAME,
            description=DEFAULT_OWNER_DESCRIPTION,
        )

    agent = await participants.get_by_name(normalize_participant_name(participant_name))
    if agent is None:
        agent = await register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.AGENT,
            name=participant_name,
            description=DEFAULT_AGENT_DESCRIPTION,
        )

    return await _replace_token(
        session, agent, token_name=token_name, scope=TokenScope.MAIN, empty=empty
    )


async def _kept_token(tokens: TokenRepository, known_secret: str | None) -> Token | None:
    """Токен постоянной копии, если он годен: найден по хешу, не отозван, за ним участник."""
    if not known_secret:
        return None
    known = await tokens.get_by_hash(hash_token(known_secret))
    if known is None or known.is_revoked or known.participant is None:
        return None
    return known


async def _replace_token(
    session: AsyncSession,
    participant: Participant,
    *,
    token_name: str,
    scope: TokenScope,
    empty: bool,
) -> LocalToken:
    """Отзывает прежние неотозванные токены участника с этим именем и выпускает новый."""
    name = token_name.strip()
    stale = await TokenRepository(session).list_live_named(participant.id, name)
    for token in stale:
        await revoke_token(session, token.id, actor=TRACKER_ACTOR)

    issued = await issue_token(
        session,
        actor=TRACKER_ACTOR,
        participant=participant,
        scope=scope,
        name=name,
    )
    return LocalToken(
        outcome=LocalTokenOutcome.INITIALIZED if empty else LocalTokenOutcome.REISSUED,
        token=issued.token,
        secret=issued.secret,
        revoked=len(stale),
    )
