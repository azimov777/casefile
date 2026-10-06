"""Первичная настройка установки: владелец с учётной записью, ключ интерфейсу, токен агенту.

Свежая база заперта снаружи: каждый маршрут `/api/v1` требует токена, а выпустить
первый токен через API нельзя — для этого уже нужен токен. Разомкнуть круг может только
код, работающий с базой напрямую, поэтому сценарии живут здесь, а команды
`python -m app.cli init`, `local-token` и `agent-token` — тонкие обёртки над ними
(их же зовут одноимённые сервисы в Compose).

Сценариев три, и разница между ними — в том, кто хранит секрет.

| Сценарий | Кому доступ | Где живёт секрет |
|---|---|---|
| `initialize_installation` | никому: владелец и учётная запись | нигде: токена нет |
| `ensure_local_token` | интерфейсу установки | в файле, который держит установка |
| `ensure_agent_token` | агенту машины, через MCP | в файле, который держит установка |

Повтор не выпускает ничего ни у одного, но признаки «уже сделано» разные: у первого это
человек с учётной записью, у двух других — годный секрет в своём файле.

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
from app.domain.tokens import TokenKind, hash_token
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.participants import register_participant
from app.services.tokens import issue_token, revoke_token

DEFAULT_OWNER_NAME = "owner"
DEFAULT_OWNER_DESCRIPTION = "Владелец установки"

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
) -> Account | None:
    """Заводит участника-человека и учётную запись администратора. Токена не выпускает.

    Человек не получает токенов (`TRK-469#25`): он входит в интерфейс — локально без
    ввода ключом `local-ui`, в сети почтой и паролем. `init` поэтому заводит владельца и
    его учётную запись, а секрета не печатает.

    `None` означает «установка уже инициализирована»: в базе есть участник-человек с
    учётной записью, и сценарий не делает ничего. Признак — учётная запись человека, а
    не токен: токена у людей теперь нет, а без человека с учётной записью установку
    не завести в интерфейс. Участник без учётной записи инициализированной установкой не
    считается: ему учётную запись заводит `ensure_admin_account`.
    """
    if await AccountRepository(session).any_human_account():
        return None

    participants = ParticipantRepository(session)
    owner = await participants.get_by_name(normalize_participant_name(name))
    if owner is None:
        owner = await register_participant(
            session,
            actor=TRACKER_ACTOR,
            kind=ParticipantKind.HUMAN,
            name=name,
            description=description,
        )
    account, _ = await ensure_admin_account(session, owner)
    assert account is not None  # участник выше — человек, учётная запись у него есть
    return account


class LocalTokenOutcome(StrEnum):
    """Что случилось с ключом локальной установки за один вызов `ensure_local_token`.

    Значения покрывают все состояния пары «файл — база»: годный секрет, пустая установка, всё
    остальное. Исхода «участника нет» здесь нет намеренно: это не исход, а отказ,
    и уходит он исключением.

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
    #: Сколько прежних токенов отозвано этим же действием: одноимённые у того же
    #: участника.
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
    adopt_connections: bool = False,
) -> LocalToken:
    """Приводит установку к состоянию «у интерфейса есть действующий ключ».

    `adopt_connections` — локальный режим (`settings.login == "local"`): живые
    подключения OAuth и ключи, выданные установкой, переходят на человека этой машины
    (`adopt_local_connections`). Шаг идёт на каждом подъёме и идемпотентен.

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
    стоит участник. Имя участника и имя токена не
    сверяются намеренно: файл — собственная копия установки, и лишние условия
    превращали бы «повторный подъём ничего не перевыпускает» в перевыпуск на ровном месте.

    Выпуская замену, сценарий тем же действием отзывает прежние неотозванные токены с
    тем же именем. Без этого потерянный файл оставлял бы на установке действующий
    секрет, которого не знает никто, — и с каждым подъёмом их становилось бы больше.

    Отказ один: названного участника нет, а установка не пуста (`participant_not_found`).
    Заводить второго участника на работающей установке команда не станет — опечатка в
    имени иначе тихо превращалась бы в нового человека с полным доступом к установке.
    """
    tokens = TokenRepository(session)

    known = await _kept_token(tokens, known_secret)
    if known is not None:
        assert known.participant is not None  # годный ключ из файла всегда именной
        account, imported = await ensure_admin_account(
            session, known.participant, legacy_password_hash
        )
        if adopt_connections:
            await adopt_local_connections(session, known.participant)
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

    replaced = await _replace_token(
        session,
        participant,
        # Ключ интерфейса — вход человека в интерфейс этой машины, как сеанс браузера,
        # а не ключ агента (`TRK-469#25`).
        kind=TokenKind.SESSION,
        token_name=token_name,
        empty=empty,
    )
    account, imported = await ensure_admin_account(session, participant, legacy_password_hash)
    if adopt_connections:
        await adopt_local_connections(session, participant)
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
    issued_by_person: bool = False,
) -> LocalToken:
    """Приводит установку к состоянию «у агента этой машины есть действующий токен».

    Нужен установке одной командой: агенту, которого человек подключает к MCP, токен
    выдаёт сама установка, как ключ интерфейсу, — а не `init`, печатающий секрет в
    журнал контейнера. Устроен как `ensure_local_token`: идемпотентен по файлу, замена
    отзывает прежний одноимённый токен, Отличий два.

    - Участник-агент заводится, если его нет, на любой установке. Опечатки в имени
      человека, от которой стережёт `ensure_local_token`, здесь нет: имя называет
      контур, а завести агента этой машины и есть смысл первого запуска.
    - На пустой установке заводится и владелец-человек, без токена, но с учётной
      записью администратора. Установка начинается с человека, и `ensure_local_token`,
      позванный следом, найдёт его, а не откажет, — порядок двух команд перестаёт
      иметь значение.

    `issued_by_person` — локальный режим: ключ выпускает человек этой машины
    (`find_local_person`), а не трекер; без такого человека выпускает трекер.
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

    issuer = TRACKER_ACTOR
    if issued_by_person:
        person = await find_local_person(session)
        if person is not None:
            issuer = Actor(author=person.author, participant=person)
    return await _replace_token(session, agent, token_name=token_name, empty=empty, issuer=issuer)


async def find_local_person(session: AsyncSession) -> Participant | None:
    """Человек этой машины: участник, за которым живой ключ интерфейса `local-ui`.

    Нужна ещё действующая учётная запись: без неё человек не вправе выпускать токены
    (`app/services/tokens.py`). Нет ключа или записи — `None`, и выпускает трекер.
    """
    holders = await TokenRepository(session).list_live_named_of_kind(
        DEFAULT_LOCAL_TOKEN_NAME, TokenKind.SESSION
    )
    for token in holders:
        person = token.participant
        if person is None or person.kind is not ParticipantKind.HUMAN:
            continue
        account = await AccountRepository(session).get_by_participant(person.id)
        if account is not None and not account.is_disabled:
            return person
    return None


async def adopt_local_connections(session: AsyncSession, person: Participant) -> int:
    """Выданное установкой становится человека машины (локальный режим, TRK-559).

    Живые подключения OAuth и ключи с выпускающим `tracker` получают выпускающим
    `person`: «Доступы» → «Мои» показывает их, и они остаются его, если установку
    переведут в сетевой режим. Отозванные и сеансы не трогаются. Хозяина участников-агентов
    это не меняет. Возвращает число переписанных строк.
    """
    return await TokenRepository(session).reassign_tracker_issued(
        (TokenKind.OAUTH, TokenKind.KEY), person.author
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
    kind: TokenKind = TokenKind.KEY,
    token_name: str,
    empty: bool,
    issuer: Actor = TRACKER_ACTOR,
) -> LocalToken:
    """Отзывает прежние неотозванные токены участника с этим именем и выпускает новый."""
    name = token_name.strip()
    stale = list(await TokenRepository(session).list_live_named(participant.id, name))
    for token in stale:
        await revoke_token(session, token.id, actor=TRACKER_ACTOR)

    issued = await issue_token(
        session,
        actor=issuer,
        participant=participant,
        name=name,
        kind=kind,
    )
    outcome = LocalTokenOutcome.INITIALIZED if empty else LocalTokenOutcome.REISSUED
    return LocalToken(
        outcome=outcome,
        token=issued.token,
        secret=issued.secret,
        revoked=len(stale),
    )
