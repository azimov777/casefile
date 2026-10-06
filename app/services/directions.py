"""Сценарии по направлениям: завести, прочитать, править, архивировать, восстановить.

Направление устроено как проект, только меньше (`CONCEPT.md`, 3.7): карточка меняется со
служебной записью в его деле — заведение подшивает `created`, правка названия и описания
— `field_changed` на каждое изменённое поле, архив — `archived` и `restored` с
обязательной причиной. Атрибуты и записи агента в деле направления — сценарии проекта
(`app/services/attributes.py`, `app/services/case.py`), владельцем у них тогда
направление.

## Адрес вместо ключа

Направление называют адресом `TRK/promotion` (`app/domain/directions.py`). Адресация
мягкая, как у проекта: регистр не важен, ключ не по шаблону ищется и не находится.
Неизвестный проект в адресе — `project_not_found`, а не `direction_not_found`: так агент
узнаёт, какая половина адреса неверна.

## Заморозка

Изменение направления проверяет и архив его проекта, и его собственный — одной функцией
(`app/services/freeze.py`), архив проекта первым. Поэтому и `archive`, и `restore`
направления в архивном проекте отвечают `project_archived`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.author import created_by_columns
from app.db.models.direction import Direction
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.pagination import Page
from app.db.repositories import DirectionRepository
from app.domain.directions import (
    is_direction_address,
    parse_direction_address,
    require_direction_reason,
    validate_direction_description,
    validate_new_direction_address,
)
from app.domain.errors import (
    DirectionKeyTakenError,
    DirectionNotArchivedError,
    DirectionNotFoundError,
)
from app.domain.tasks import TaskField
from app.services import case as case_service
from app.services import freeze
from app.services import projects as projects_service
from app.services.auth import Actor
from app.services.case import CaseOwner


async def get_direction(session: AsyncSession, address: str) -> Direction:
    """Направление по адресу; неизвестный проект — `project_not_found`, неизвестный ключ в
    нём — `direction_not_found`."""
    parsed = parse_direction_address(address)
    project = await projects_service.get_project(session, parsed.project_key)
    direction = await DirectionRepository(session).get(project.id, parsed.key)
    if direction is None:
        raise DirectionNotFoundError(details={"key": str(parsed)})
    return direction


async def get_owner(session: AsyncSession, key: str) -> CaseOwner:
    """Проект по ключу или направление по адресу — для вызовов, где действие у обоих одно.

    Атрибуты, запись в дело, чтение дела, карточка и архив устроены у направления так же,
    как у проекта (`CONCEPT.md`, 3.7), и инструменты MCP принимают на месте ключа проекта
    и адрес направления. Различает их косая черта: в ключе проекта её не бывает.
    """
    if is_direction_address(key):
        return await get_direction(session, key)
    return await projects_service.get_project(session, key)


async def list_directions(
    session: AsyncSession, project: Project, *, actor: Actor, include_archived: bool = False
) -> list[Direction]:
    """Все направления проекта по ключу; архивные скрыты, пока их не попросили.

    Скрытие — только в списке: по адресу архивное направление читается как обычно.
    """
    return await DirectionRepository(session).list_for_project(
        project.id, include_archived=include_archived
    )


async def list_directions_page(
    session: AsyncSession,
    project: Project,
    *,
    actor: Actor,
    include_archived: bool = False,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Direction]:
    """Направления проекта страницей — для коллекции REST."""
    return await DirectionRepository(session).list_page(
        project.id, include_archived=include_archived, limit=limit, cursor=cursor
    )


async def create_direction(
    session: AsyncSession,
    *,
    actor: Actor,
    address: str,
    title: str,
    description: str = "",
) -> Direction:
    """Заводит направление по адресу `ПРОЕКТ/ключ`; первая запись его дела — `created`.

    Форма адреса и описание проверяются до базы. Дальше — очередь изменений и заморозка
    проекта первым шагом: в архивный проект направление не заводится (`project_archived`),
    и отказ архива называется раньше занятого ключа. Занятость ключа читается под
    очередью, поэтому две одновременные попытки одного ключа не встречаются на уникальном
    индексе: вторая видит первую и получает `direction_key_taken`.
    """
    parsed = validate_new_direction_address(address)
    description = validate_direction_description(description)
    project = await projects_service.get_project(session, parsed.project_key)
    await freeze.lock_unfrozen(session, project=project)

    repository = DirectionRepository(session)
    if await repository.get(project.id, parsed.key) is not None:
        raise DirectionKeyTakenError(details={"key": str(parsed)})
    # Проект — объектом, а не только внешним ключом: адрес собирается из `project.key`, а
    # у только что созданной строки связь сама не подгрузится (`docs/notes/db.md`, «Связь у
    # только что созданной строки задаётся объектом, а не внешним ключом»).
    direction = await repository.add(
        Direction(
            project=project,
            project_id=project.id,
            key=parsed.key,
            title=title.strip(),
            description=description,
            **created_by_columns(actor.author),
        )
    )
    await case_service.record_project_created(session, direction, actor=actor)
    return direction


async def update_direction(
    session: AsyncSession,
    direction: Direction,
    *,
    actor: Actor,
    title: str | None = None,
    description: str | None = None,
) -> Direction:
    """Меняет название и описание; проект и ключ не меняются никогда.

    `None` — «поле не передано». Каждое изменённое поле подшивает `field_changed` с
    прежним и новым значением, все записи одного вызова делят `action_id`; значение,
    равное нынешнему, записи не оставляет.
    """
    await freeze.lock_unfrozen(session, direction=direction)
    # Под очередью перечитать: направление разрешено из адреса до неё, и «было» в записи
    # иначе могло бы оказаться чужим устаревшим снимком.
    await session.refresh(direction)

    changes = {
        TaskField.TITLE: None if title is None else title.strip(),
        TaskField.DESCRIPTION: (
            None if description is None else validate_direction_description(description)
        ),
    }
    action_id = uuid.uuid4()
    for field, after in changes.items():
        before: str = getattr(direction, field.value)
        if after is None or after == before:
            continue
        setattr(direction, field.value, after)
        await case_service.record_project_field_changed(
            session,
            direction,
            actor=actor,
            field=field,
            before=before,
            after=after,
            action_id=action_id,
        )
    await session.flush()
    return direction


async def archive_direction(
    session: AsyncSession, direction: Direction, *, actor: Actor, reason: str | None
) -> Entry:
    """Архивирует направление с причиной; отдаёт подшитую запись `archived`.

    Повторное архивирование архивного отклоняет та же проверка заморозки, что и любое
    другое изменение, — первым шагом, до записи (`direction_archived`; в архивном проекте —
    `project_archived`). `archived_at` — время записи `archived`.
    """
    checked = require_direction_reason(reason, address=direction.address, action="archive")
    await freeze.lock_unfrozen(session, direction=direction)
    entry = await case_service.record_archived(session, direction, actor=actor, reason=checked)
    direction.archived_at = entry.created_at
    await session.flush()
    return entry


async def restore_direction(
    session: AsyncSession, direction: Direction, *, actor: Actor, reason: str | None
) -> Entry:
    """Восстанавливает направление из архива с причиной; отдаёт подшитую `restored`.

    Запись `restored` архив пропускает (`freeze.UNFROZEN_ENTRY_TYPES`), поэтому архив
    проекта проверяется здесь явно: восстановить направление в архивном проекте нельзя
    (`project_archived`). Живое направление восстанавливать нечего —
    `direction_not_archived`.
    """
    checked = require_direction_reason(reason, address=direction.address, action="restore")
    await lock_changes(session)
    await freeze.ensure_unfrozen(session, projects=(direction.project,))
    # Под очередью перечитать: соседняя транзакция могла успеть его восстановить.
    await session.refresh(direction)
    if direction.archived_at is None:
        raise DirectionNotArchivedError(details={"key": direction.address})
    entry = await case_service.record_restored(session, direction, actor=actor, reason=checked)
    direction.archived_at = None
    await session.flush()
    return entry
