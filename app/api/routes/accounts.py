"""Учётные записи людей: управление администратором и смена своего пароля.

`docs/CONCEPT.md`, 5.4. Всё, кроме смены своего пароля, открыто только администратору
(`403 admin_required`); права на задачи флаг не даёт. Роутер переводит HTTP в вызов
сценария и обратно: те же сценарии зовёт команда на сервере (`python -m app.cli
account-...`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, status

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.idempotency import OnceDep
from app.api.schemas.accounts import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    AccountWithPasswordRead,
    PasswordChange,
    PasswordReset,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.services import accounts as service
from app.services.accounts import AccountWithPassword

router = APIRouter(prefix="/accounts", tags=["accounts"])

AccountIdPath = Annotated[uuid.UUID, Path(description="Identifier of the account")]


def _with_password(result: AccountWithPassword) -> AccountWithPasswordRead:
    return AccountWithPasswordRead(
        **AccountRead.model_validate(result.account).model_dump(),
        password=result.password,
    )


@router.get("", summary="List accounts")
async def list_accounts(
    session: SessionDep,
    actor: ActorDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[AccountRead]:
    """Все учётные записи установки, отключённые тоже. Только администратору."""
    page = await service.list_accounts(session, actor=actor, limit=limit, cursor=cursor)
    return CollectionResponse[AccountRead].of(
        [AccountRead.model_validate(account) for account in page.items],
        next_cursor=page.next_cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an account")
async def create_account(
    payload: AccountCreate,
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[AccountWithPasswordRead]:
    """Заводит учётную запись человеку — новому участнику или существующему без неё.

    Только администратору, с набором `main`. Без `password` трекер генерирует пароль сам
    и возвращает его в `password` — единственный раз; писем трекер не шлёт, и пароль
    человеку передаёт администратор. Занятая почта — `409 account_email_taken`; участник-
    агент — `422 account_requires_human`; у человека уже есть учётная запись — `409
    participant_has_account`; короткий пароль — `422 weak_password`.

    Повтор с тем же `Idempotency-Key` отвечает первой учётной записью — с тем же
    сгенерированным паролем, как повтор выпуска токена отвечает тем же секретом.
    """

    async def create() -> DataResponse[AccountWithPasswordRead]:
        created = await service.create_account(
            session,
            actor=actor,
            email=payload.email,
            name=payload.name,
            description=payload.description,
            is_admin=payload.is_admin,
            password=payload.password,
        )
        return DataResponse[AccountWithPasswordRead](data=_with_password(created))

    return await once.run(DataResponse[AccountWithPasswordRead], request=payload, build=create)


@router.get("/{account_id}", summary="Read an account")
async def read_account(
    account_id: AccountIdPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AccountRead]:
    """Карточка учётной записи. Только администратору; свою человек видит в `bootstrap`."""
    account = await service.read_account(session, account_id, actor=actor)
    return DataResponse[AccountRead](data=AccountRead.model_validate(account))


@router.patch("/{account_id}", summary="Update an account")
async def update_account(
    account_id: AccountIdPath,
    payload: AccountUpdate,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AccountRead]:
    """Меняет почту, флаг администратора и отключение. Только администратору.

    Отключение отзывает все токены участника учётной записи; включение их не
    возвращает. Последнего действующего администратора нельзя ни отключить, ни лишить
    флага — `409 last_admin`.
    """
    account = await service.get_account(session, account_id)
    account = await service.update_account(
        session, account, actor=actor, **payload.model_dump(exclude_unset=True)
    )
    return DataResponse[AccountRead](data=AccountRead.model_validate(account))


@router.post("/{account_id}/password-reset", summary="Reset the password of an account")
async def reset_password(
    account_id: AccountIdPath,
    payload: PasswordReset,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AccountWithPasswordRead]:
    """Задаёт новый пароль — вписанный или сгенерированный — и гасит сеансы учётной записи.

    Только администратору; прежний пароль не спрашивается. Сгенерированный приходит в
    `password` один раз.
    """
    account = await service.get_account(session, account_id)
    reset = await service.reset_password(session, account, actor=actor, password=payload.password)
    return DataResponse[AccountWithPasswordRead](data=_with_password(reset))


@router.put("/{account_id}/password", summary="Change the own password")
async def change_password(
    account_id: AccountIdPath,
    payload: PasswordChange,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[AccountRead]:
    """Меняет пароль своей учётной записи — той, за чьим участником стоит токен.

    Прежний пароль обязателен, если он задан: неверный — `422 current_password_mismatch`.
    Чужая учётная запись — `403 permission_denied` с `details.reason: not_own_account`:
    чужой пароль сбрасывает администратор. Остальные сеансы учётной записи гаснут, токен
    этого запроса остаётся живым.
    """
    account = await service.change_own_password(
        session,
        account_id,
        actor=actor,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return DataResponse[AccountRead](data=AccountRead.model_validate(account))
