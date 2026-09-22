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
| `ensure_local_token` | интерфейсу установки | `main` | в файле, который держит установка |
| `ensure_agent_token` | агенту машины, через MCP | `main` | в файле, который держит установка |

Повтор не выпускает ничего ни у одного, но признаки «уже сделано» разные: у первого это
наличие любого токена в базе, у двух других — годный секрет в своём файле, а у ключа
интерфейса ещё и его набор: до решения владельца 2026-09-11 (`UI-104`) ключ выпускался
набором `task`, и такой ключ заменяется (`ensure_local_token`).

Автор всего заведённого — сам трекер (`TRACKER_ACTOR`): участника, который завёл бы
первого участника, в этот момент ещё не существует.

## Учётная запись администратора заводится здесь же

Человеку, которому установка выпускает ключ интерфейса, она заводит и учётную запись
администратора (`docs/CONCEPT.md`, 5.4): почта `<имя>@localhost`, без пароля. На своей
машине этого достаточно — ключ интерфейс получает без входа, и записи подписаны именем
администратора. Заводит её каждый из трёх сценариев, который заводит этого человека или
выдаёт ему ключ (`ensure_admin_account`), и на уже работающей установке тоже: так
учётную запись получает владелец установки, поднятой до учётных записей.

Там же переносится прежний пароль установки: `ensure_local_token` получает хеш
`TRACKER_PASSWORD_HASH` и кладёт его паролем в эту учётную запись, если пароля у неё ещё
нет. Прежний пароль продолжает пускать, а заданный позже перенос не перетирает.
"""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account import Account
from app.db.models.author import created_by_columns
from app.db.models.participant import Participant
from app.db.models.token import Token
from app.db.repositories import AccountRepository, ParticipantRepository, TokenRepository
from app.domain.accounts import local_admin_email
from app.domain.errors import AccountEmailTakenError, ParticipantNotFoundError
from app.domain.participants import ParticipantKind, normalize_participant_name
from app.domain.passwords import PasswordHash
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

#: Набор ключа интерфейса локальной установки. `main`, потому что человек здесь и есть
#: владелец установки и выпускает доступы агентов в интерфейсе (решение владельца
#: 2026-09-11, `UI-104`). Ключ уезжает в браузер, и чужой странице его не отдаёт nginx
#: интерфейса: он отвечает только адресам петли (`UI-107`). Довод целиком —
#: `docs/DEVELOPMENT.md`, «Ключ для локального интерфейса».
LOCAL_TOKEN_SCOPE = TokenScope.MAIN

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
    await ensure_admin_account(session, owner)
    return await issue_token(
        session,
        actor=TRACKER_ACTOR,
        participant=owner,
        scope=TokenScope.MAIN,
        name=token_name,
    )


class LocalTokenOutcome(StrEnum):
    """Что случилось с ключом локальной установки за один вызов `ensure_local_token`.

    Значения покрывают все состояния пары «файл — база»: годный секрет, годный секрет
    другого набора, пустая установка, всё остальное. Исхода «участника нет» здесь нет
    намеренно: это не исход, а отказ, и уходит он исключением.

    `RESCOPED` даёт только ключ интерфейса: набор сверяет лишь он, потому что только его
    набор и менялся. Токен агента (`ensure_agent_token`) выпускается `main` всегда.
    """

    #: Секрет из файла действует: не выпущено ничего.
    KEPT = "kept"
    #: Установка была пуста: выпущен первый токен, владелец заведён, если его не было.
    INITIALIZED = "initialized"
    #: Установка работает, а годного секрета не было: выпущена замена прежнему.
    REISSUED = "reissued"
    #: Секрет из файла действует, но набор у него не тот: выпущена замена, а он отозван.
    RESCOPED = "rescoped"


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
    #: Сколько прежних токенов отозвано этим же действием: одноимённые у того же
    #: участника и, при `RESCOPED`, заменённый токен из файла, как бы он ни назывался.
    revoked: int
    #: Учётная запись человека, которому выдан ключ интерфейса. Пуста у токена агента
    #: (`ensure_agent_token`): агенту учётная запись не нужна.
    account: Account | None = None
    #: Этим вызовом прежний `TRACKER_PASSWORD_HASH` стал паролем учётной записи.
    password_imported: bool = False


async def ensure_local_token(
    session: AsyncSession,
    *,
    known_secret: str | None,
    participant_name: str = DEFAULT_OWNER_NAME,
    token_name: str = DEFAULT_LOCAL_TOKEN_NAME,
    legacy_password_hash: PasswordHash | None = None,
) -> LocalToken:
    """Приводит установку к состоянию «у интерфейса есть действующий ключ набора `main`».

    И к состоянию «у этого человека есть учётная запись администратора»: её сценарий
    заводит, если её нет, а `legacy_password_hash` — прежний `TRACKER_PASSWORD_HASH` —
    кладёт в неё паролем, если пароля у неё ещё нет (раздел модуля).

    `known_secret` — то, что вызывающий нашёл в своей постоянной копии (для команды это
    файл; `None` — копии нет). Про файлы сценарий не знает ничего: он отвечает, что с
    найденным секретом делать, а хранит его вызывающий. Иначе слой сценариев пришлось
    бы учить путям на диске ради одной команды.

    Почему постоянная копия вообще нужна и почему ею не может быть база: в базе лежит
    хеш (`app/domain/tokens.py`), и «показать выданный токен» невозможно ни при каких
    условиях. Значит идемпотентность подъёма строится вокруг файла, а база только
    отвечает, годен ли его секрет.

    Годным секрет считается ровно тогда, когда он найден по хешу, не отозван, за ним
    стоит участник и набор у него `LOCAL_TOKEN_SCOPE`. Набор сверяется потому, что он
    менялся: до решения владельца 2026-09-11 ключ выпускался `task`, и без сверки файл с
    таким ключом держал бы установку на `task` вечно. Имя участника и имя токена не
    сверяются намеренно: файл — собственная копия установки, и лишние условия
    превращали бы «повторный подъём ничего не перевыпускает» в перевыпуск на ровном месте.

    Выпуская замену, сценарий тем же действием отзывает прежние неотозванные токены с
    тем же именем. Без этого потерянный файл оставлял бы на установке действующий
    секрет, которого не знает никто, — и с каждым подъёмом их становилось бы больше.
    Годный ключ другого набора отзывается тоже, как бы он ни назывался и чей бы ни был:
    файл перезаписывается, и его секрет иначе остался бы действующим и никому не известным.

    Отказ один: названного участника нет, а установка не пуста (`participant_not_found`).
    Заводить второго участника на работающей установке команда не станет — опечатка в
    имени иначе тихо превращалась бы в нового человека с полным доступом к установке.
    """
    tokens = TokenRepository(session)

    known = await _kept_token(tokens, known_secret)
    if known is not None and known.scope is LOCAL_TOKEN_SCOPE:
        assert known.participant is not None  # годный ключ из файла всегда именной
        account, imported = await ensure_admin_account(
            session, known.participant, legacy_password_hash
        )
        return LocalToken(
            outcome=LocalTokenOutcome.KEPT,
            token=known,
            secret=None,
            revoked=0,
            account=account,
            password_imported=imported,
        )

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

    # `known` здесь — либо `None`, либо годный ключ другого набора: его и заменяем.
    replaced = await _replace_token(
        session,
        participant,
        token_name=token_name,
        scope=LOCAL_TOKEN_SCOPE,
        empty=empty,
        predecessor=known,
    )
    account, imported = await ensure_admin_account(session, participant, legacy_password_hash)
    return LocalToken(
        outcome=replaced.outcome,
        token=replaced.token,
        secret=replaced.secret,
        revoked=replaced.revoked,
        account=account,
        password_imported=imported,
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
    журнал контейнера. Устроен как `ensure_local_token`: идемпотентен по файлу, замена
    отзывает прежний одноимённый токен, набор тот же — `main`, без которого агент не
    заведёт даже первую очередь. Отличий три.

    - Набор не сверяется: признак годности — `_kept_token` как есть. Этот токен
      выпускался `main` всегда, и расхождения, которое пришлось бы чинить, у него нет.
    - Участник-агент заводится, если его нет, на любой установке. Опечатки в имени
      человека, от которой стережёт `ensure_local_token`, здесь нет: имя называет
      контур, а завести агента этой машины и есть смысл первого запуска.
    - На пустой установке заводится и владелец-человек, без токена, но с учётной
      записью администратора. Установка начинается с человека, и `ensure_local_token`,
      позванный следом, найдёт его, а не откажет, — порядок двух команд перестаёт
      иметь значение.
    """
    tokens = TokenRepository(session)

    kept = await _kept_token(tokens, known_secret)
    if kept is not None:
        return LocalToken(outcome=LocalTokenOutcome.KEPT, token=kept, secret=None, revoked=0)

    empty = not await tokens.any_exists()
    participants = ParticipantRepository(session)

    owner_name = normalize_participant_name(DEFAULT_OWNER_NAME)
    if empty and await participants.get_by_name(owner_name) is None:
        owner = await register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.HUMAN,
            name=DEFAULT_OWNER_NAME,
            description=DEFAULT_OWNER_DESCRIPTION,
        )
        await ensure_admin_account(session, owner)

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


async def ensure_admin_account(
    session: AsyncSession,
    participant: Participant,
    legacy_password_hash: PasswordHash | None = None,
) -> tuple[Account | None, bool]:
    """Учётная запись администратора человека — заведённая или найденная — и был ли перенос.

    Агенту учётная запись не заводится: `(None, False)`. Уже заведённую сценарий не
    трогает, кроме одного: пустой пароль получает прежний хеш установки, если он передан.
    Почта `<имя>@localhost` занята чужой учётной записью — отказ `account_email_taken`, а не
    тихая другая почта: владелец установки должен знать, чем входить.
    """
    if participant.kind is not ParticipantKind.HUMAN:
        return None, False
    accounts = AccountRepository(session)
    account = await accounts.get_by_participant(participant.id)
    if account is None:
        email = local_admin_email(participant.name)
        if await accounts.get_by_email(email) is not None:
            raise AccountEmailTakenError(details={"email": email})
        account = await accounts.add(
            Account(
                participant=participant,
                email=email,
                is_admin=True,
                **created_by_columns(TRACKER_ACTOR.author),
            )
        )
    if legacy_password_hash is None or account.password_hash is not None:
        return account, False
    account.password_hash = legacy_password_hash.render()
    await session.flush()
    return account, True


async def _kept_token(tokens: TokenRepository, known_secret: str | None) -> Token | None:
    """Токен постоянной копии, если он годен: найден по хешу, не отозван, за ним участник.

    Набор здесь не сверяется: его сверяет тот сценарий, у которого набор менялся
    (`ensure_local_token`), а не все, кто держит секрет в файле.
    """
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
    predecessor: Token | None = None,
) -> LocalToken:
    """Отзывает прежние неотозванные токены участника с этим именем и выпускает новый.

    `predecessor` — годный токен из файла, который заменяется из-за набора. Он
    отзывается тем же действием, даже если имя или участник у него другие: иначе на
    установке остался бы действующий секрет, которого после перезаписи файла не знает
    никто. Среди одноимённых он тоже может оказаться — тогда отзывается один раз.
    """
    name = token_name.strip()
    stale = list(await TokenRepository(session).list_live_named(participant.id, name))
    if predecessor is not None and all(token.id != predecessor.id for token in stale):
        stale.append(predecessor)
    for token in stale:
        await revoke_token(session, token.id, actor=TRACKER_ACTOR)

    issued = await issue_token(
        session,
        actor=TRACKER_ACTOR,
        participant=participant,
        scope=scope,
        name=name,
    )
    if predecessor is not None:
        outcome = LocalTokenOutcome.RESCOPED
    elif empty:
        outcome = LocalTokenOutcome.INITIALIZED
    else:
        outcome = LocalTokenOutcome.REISSUED
    return LocalToken(
        outcome=outcome,
        token=issued.token,
        secret=issued.secret,
        revoked=len(stale),
    )
