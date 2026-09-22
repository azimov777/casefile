"""Сценарии по учётным записям: заведение, отключение, почта, флаг, пароли.

Один сценарий — одна функция, и зовут её REST (`app/api/routes/accounts.py`) и командная
строка (`python -m app.cli account-...`). MCP учётных записей не знает вовсе: агенты
ходят токенами, и управлять людьми им незачем (`docs/CONCEPT.md`, 5.2 и 5.4).

## Кто вправе

Управление людьми открыто администратору — учётной записи с флагом `is_admin`, не
отключённой, — и больше никому: флаг не даёт прав на задачи, а прав на людей не даёт
набор токена (`ensure_admin`). Сверх флага нужен набор `main`: заводя человека,
сценарий регистрирует участника, а это действие набора `main` (3.1).

Второй, кто вправе, — сам трекер (`TRACKER_ACTOR`): так действует команда на сервере.
Её запускает тот, у кого есть доступ к контейнерам установки, то есть к базе напрямую, —
спрашивать у него флаг значило бы запереть установку, у которой администратор потерял
пароль.

## Что отзывается вместе с чем

- Отключение отзывает **все** неотозванные свои токены человека — и выданные ему, и
  выпущенные им своим агентам (`TokenRepository.list_live_owned_by`, решение
  `TRK-114#13`): человек ушёл, и ни одна вкладка, ни один его ключ и ни один его агент
  не должны работать. Включение их не возвращает.
- Сброс пароля администратором и смена своего пароля отзывают **сеансы** — токены со
  сроком (`app/services/login.py`): это «выйти везде». Своя смена оставляет живым токен,
  которым её сделали: человек не должен вылететь из вкладки, где только что сменил пароль.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.db.models.account import Account
from app.db.models.author import created_by_columns
from app.db.models.participant import Participant
from app.db.pagination import Page
from app.db.repositories import AccountRepository, ParticipantRepository, TokenRepository
from app.domain.accounts import generate_password, validate_email
from app.domain.errors import (
    AccountEmailTakenError,
    AccountNotFoundError,
    AccountRequiresHumanError,
    AdminRequiredError,
    CurrentPasswordMismatchError,
    LastAdminError,
    ParticipantHasAccountError,
)
from app.domain.participants import ParticipantKind, normalize_participant_name
from app.domain.passwords import PasswordHash, check_new_password, hash_password, verify_password
from app.domain.tokens import TokenScope
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.participants import register_participant
from app.services.permissions import ensure_scope


@dataclass(frozen=True, slots=True)
class AccountWithPassword:
    """Учётная запись и пароль, который трекер сгенерировал для неё сам.

    `password` пуст, если пароль вписал администратор: показывать ему его же пароль
    незачем. Сгенерированный существует только здесь и в ответе — в базе хеш.
    """

    account: Account
    password: str | None


async def ensure_admin(session: AsyncSession, actor: Actor, *, action: str) -> None:
    """Пропускает администратора и сам трекер, остальным отказывает `admin_required`.

    Набор `main` проверяется первым: токен набора `task` не открывает управления
    установкой никому, и отказ про набор честнее, чем про флаг.
    """
    ensure_scope(actor, TokenScope.MAIN, action=action)
    if not await is_admin(session, actor):
        raise AdminRequiredError(details={"action": action})


async def is_admin(session: AsyncSession, actor: Actor) -> bool:
    """Администратор ли тот, кто зовёт: действующая учётная запись с флагом — или сам трекер.

    Набор не проверяет: это вопрос, а не отказ. Им пользуются и `ensure_admin`, и токены
    (`app/services/tokens.py`), где администратор видит и отзывает все токены, а не свои.
    """
    if actor == TRACKER_ACTOR:
        return True
    account = await active_account_of(session, actor)
    return account is not None and account.is_admin


async def active_account_of(session: AsyncSession, actor: Actor) -> Account | None:
    """Действующая (не отключённая) учётная запись того, кто зовёт, если она есть."""
    account = await account_of(session, actor.participant)
    return None if account is None or account.is_disabled else account


async def account_of(session: AsyncSession, participant: Participant | None) -> Account | None:
    """Учётная запись участника, если она есть. Прав не проверяет: это «кто я»."""
    if participant is None:
        return None
    return await AccountRepository(session).get_by_participant(participant.id)


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> Account:
    """Учётная запись по идентификатору или `account_not_found`. Прав не проверяет."""
    account = await AccountRepository(session).get_by_id(account_id)
    if account is None:
        raise AccountNotFoundError(details={"account_id": str(account_id)})
    return account


async def get_account_by_email(session: AsyncSession, email: str) -> Account:
    """Учётная запись по почте или `account_not_found`: так её называет команда на сервере."""
    account = await AccountRepository(session).get_by_email(validate_email(email))
    if account is None:
        raise AccountNotFoundError(details={"email": email})
    return account


async def read_account(session: AsyncSession, account_id: uuid.UUID, *, actor: Actor) -> Account:
    """Карточка учётной записи для администратора."""
    await ensure_admin(session, actor, action="account.read")
    return await get_account(session, account_id)


async def list_accounts(
    session: AsyncSession,
    *,
    actor: Actor,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Account]:
    """Все учётные записи установки, отключённые тоже: список людей для администратора."""
    await ensure_admin(session, actor, action="account.list")
    return await AccountRepository(session).list_page(limit=limit, cursor=cursor)


async def create_account(
    session: AsyncSession,
    *,
    actor: Actor,
    email: str,
    name: str,
    description: str = "",
    is_admin: bool = False,
    password: str | None = None,
) -> AccountWithPassword:
    """Заводит учётную запись: вместе с новым участником или человеку, у которого её нет.

    Участник с этим именем уже есть — учётная запись достаётся ему, если он человек и
    учётной записи у него ещё нет: так входить начинают люди, заведённые до учётных
    записей. Нет — заводится новый участник-человек с этим именем и описанием.

    Пароль не передан — трекер генерирует его сам и возвращает один раз.
    """
    await ensure_admin(session, actor, action="account.create")
    canonical_email = await _free_email(session, email)
    if password is not None:
        check_new_password(password)

    participant = await ParticipantRepository(session).get_by_name(normalize_participant_name(name))
    if participant is None:
        participant = await register_participant(
            session,
            actor=actor,
            kind=ParticipantKind.HUMAN,
            name=name,
            description=description,
        )
    else:
        if participant.kind is not ParticipantKind.HUMAN:
            raise AccountRequiresHumanError(
                details={"name": participant.name, "kind": participant.kind.value}
            )
        if await AccountRepository(session).get_by_participant(participant.id) is not None:
            raise ParticipantHasAccountError(details={"name": participant.name})

    generated = generate_password() if password is None else None
    account = await AccountRepository(session).add(
        Account(
            participant=participant,
            email=canonical_email,
            password_hash=await _hash(password if password is not None else generated),
            is_admin=is_admin,
            **created_by_columns(actor.author),
        )
    )
    return AccountWithPassword(account=account, password=generated)


async def update_account(
    session: AsyncSession,
    account: Account,
    *,
    actor: Actor,
    email: str | None = None,
    is_admin: bool | None = None,
    disabled: bool | None = None,
) -> Account:
    """Меняет почту, флаг администратора и отключение; непереданное не трогает.

    Последнего действующего администратора лишить флага или отключить нельзя
    (`last_admin`): заводить людей стало бы некому. Отключение отзывает все токены
    участника; повторное отключение — не ошибка и срок отключения не сдвигает.
    """
    await ensure_admin(session, actor, action="account.update")

    if email is not None:
        canonical = validate_email(email)
        if canonical != account.email:
            account.email = await _free_email(session, canonical)

    losing_admin = (is_admin is False or disabled is True) and (
        account.is_admin and not account.is_disabled
    )
    if losing_admin and await AccountRepository(session).count_active_admins() <= 1:
        raise LastAdminError(details={"account_id": str(account.id), "email": account.email})

    if is_admin is not None:
        account.is_admin = is_admin
    if disabled is True and not account.is_disabled:
        account.disabled_at = datetime.now(UTC)
        await _revoke_everything(session, account)
    elif disabled is False:
        account.disabled_at = None
    await session.flush()
    return account


async def reset_password(
    session: AsyncSession,
    account: Account,
    *,
    actor: Actor,
    password: str | None = None,
) -> AccountWithPassword:
    """Задаёт учётной записи новый пароль — вписанный или сгенерированный — и гасит её сеансы.

    Прежний пароль не спрашивается: сброс и нужен тому, кто его забыл. Писем нет —
    новый пароль администратор передаёт человеку сам.
    """
    await ensure_admin(session, actor, action="account.reset_password")
    if password is not None:
        check_new_password(password)
    generated = generate_password() if password is None else None
    account.password_hash = await _hash(password if password is not None else generated)
    await _revoke_sessions(session, account)
    await session.flush()
    return AccountWithPassword(account=account, password=generated)


async def change_own_password(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    actor: Actor,
    current_password: str | None,
    new_password: str,
) -> Account:
    """Меняет пароль своей учётной записи, зная прежний; остальные свои сеансы гасит.

    Своей — той, за чьим участником стоит токен запроса: чужой пароль меняет только
    администратор сбросом (`reset_password`), а не этим сценарием, и отказ здесь —
    `permission_denied` с `details.reason: not_own_account`.

    Прежний не нужен только учётной записи без пароля — той, что завела себе установка:
    сверять не с чем, а её владелец уже вошёл токеном этой учётной записи.
    """
    ensure_scope(actor, TokenScope.TASK, action="account.change_password")
    account = await account_of(session, actor.participant)
    if account is None or account.id != account_id:
        raise PermissionDeniedError(
            message="Only the account behind the token can change its own password",
            details={"action": "account.change_password", "reason": "not_own_account"},
        )
    if account.password_hash is not None:
        stored = PasswordHash.parse(account.password_hash)
        matches = current_password is not None and await asyncio.to_thread(
            verify_password, current_password, stored
        )
        if not matches:
            raise CurrentPasswordMismatchError()
    check_new_password(new_password)
    account.password_hash = await _hash(new_password)
    await _revoke_sessions(session, account, keep=actor.token_id)
    await session.flush()
    return account


async def _free_email(session: AsyncSession, email: str) -> str:
    """Канонический вид почты, если она свободна, или отказ `account_email_taken`."""
    canonical = validate_email(email)
    if await AccountRepository(session).get_by_email(canonical) is not None:
        raise AccountEmailTakenError(details={"email": canonical})
    return canonical


async def _hash(password: str | None) -> str:
    """Хеш пароля строкой. scrypt держит процессор десятые доли секунды — в потоке."""
    assert password is not None  # сгенерированный или вписанный — пустым он не бывает
    return (await asyncio.to_thread(hash_password, password)).render()


async def _revoke_sessions(
    session: AsyncSession, account: Account, *, keep: uuid.UUID | None = None
) -> None:
    """Отзывает сеансы браузера учётной записи, кроме `keep`."""
    moment = datetime.now(UTC)
    tokens = await TokenRepository(session).list_live_sessions_of(account.participant_id, keep=keep)
    for token in tokens:
        token.revoked_at = moment


async def _revoke_everything(session: AsyncSession, account: Account) -> None:
    """Отзывает все свои токены человека: выданные ему и выпущенные им своим агентам."""
    moment = datetime.now(UTC)
    for token in await TokenRepository(session).list_live_owned_by(account.participant):
        token.revoked_at = moment
