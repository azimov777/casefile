"""Сценарии по областям: завести, прочитать, править, архивировать, восстановить.

Область устроена как проект, только меньше (`CONCEPT.md`, 3.7): карточка меняется со
служебной записью в её деле — заведение подшивает `created`, правка названия и описания
— `field_changed` на каждое изменённое поле, архив — `archived` и `restored` с
обязательной причиной. Атрибуты и записи агента в деле области — сценарии проекта
(`app/services/attributes.py`, `app/services/case.py`), владельцем у них тогда
область.

## Адрес вместо ключа

Область называют адресом `TRK/promotion` (`app/domain/areas.py`). Адресация
мягкая, как у проекта: регистр не важен, ключ не по шаблону ищется и не находится.
Неизвестный проект в адресе — `project_not_found`, а не `area_not_found`: так агент
узнаёт, какая половина адреса неверна.

## Заморозка

Изменение области проверяет и архив её проекта, и её собственный — одной функцией
(`app/services/freeze.py`), архив проекта первым. Поэтому и `archive`, и `restore`
области в архивном проекте отвечают `project_archived`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import lock_changes
from app.db.models.area import Area
from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.pagination import Page
from app.db.repositories import AreaRepository
from app.domain.areas import (
    is_area_address,
    parse_area_address,
    require_area_reason,
    validate_area_description,
    validate_new_area_address,
)
from app.domain.errors import (
    AreaKeyTakenError,
    AreaNotArchivedError,
    AreaNotFoundError,
)
from app.domain.tasks import TaskField
from app.services import case as case_service
from app.services import freeze
from app.services import projects as projects_service
from app.services.auth import Actor
from app.services.case import CaseOwner


async def get_area(session: AsyncSession, address: str) -> Area:
    """Область по адресу; неизвестный проект — `project_not_found`, неизвестный ключ в
    нём — `area_not_found`."""
    parsed = parse_area_address(address)
    project = await projects_service.get_project(session, parsed.project_key)
    area = await AreaRepository(session).get(project.id, parsed.key)
    if area is None:
        raise AreaNotFoundError(details={"key": str(parsed)})
    return area


async def get_owner(session: AsyncSession, key: str) -> CaseOwner:
    """Проект по ключу или область по адресу — для вызовов, где действие у обоих одно.

    Атрибуты, запись в дело, чтение дела, карточка и архив устроены у области так же,
    как у проекта (`CONCEPT.md`, 3.7), и инструменты MCP принимают на месте ключа проекта
    и адрес области. Различает их косая черта: в ключе проекта её не бывает.
    """
    if is_area_address(key):
        return await get_area(session, key)
    return await projects_service.get_project(session, key)


async def list_areas(
    session: AsyncSession, project: Project, *, actor: Actor, include_archived: bool = False
) -> list[Area]:
    """Все области проекта по ключу; архивные скрыты, пока их не попросили.

    Скрытие — только в списке: по адресу архивная область читается как обычно.
    """
    return await AreaRepository(session).list_for_project(
        project.id, include_archived=include_archived
    )


async def list_areas_page(
    session: AsyncSession,
    project: Project,
    *,
    actor: Actor,
    include_archived: bool = False,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Area]:
    """Области проекта страницей — для коллекции REST."""
    return await AreaRepository(session).list_page(
        project.id, include_archived=include_archived, limit=limit, cursor=cursor
    )


async def create_area(
    session: AsyncSession,
    *,
    actor: Actor,
    address: str,
    title: str,
    description: str = "",
) -> Area:
    """Заводит область по адресу `ПРОЕКТ/ключ`; первая запись её дела — `created`.

    Форма адреса и описание проверяются до базы. Дальше — очередь изменений и заморозка
    проекта первым шагом: в архивный проект область не заводится (`project_archived`),
    и отказ архива называется раньше занятого ключа. Занятость ключа читается под
    очередью, поэтому две одновременные попытки одного ключа не встречаются на уникальном
    индексе: вторая видит первую и получает `area_key_taken`.
    """
    parsed = validate_new_area_address(address)
    description = validate_area_description(description)
    project = await projects_service.get_project(session, parsed.project_key)
    await freeze.lock_unfrozen(session, project=project)

    repository = AreaRepository(session)
    if await repository.get(project.id, parsed.key) is not None:
        raise AreaKeyTakenError(details={"key": str(parsed)})
    # Проект — объектом, а не только внешним ключом: адрес собирается из `project.key`, а
    # у только что созданной строки связь сама не подгрузится (`docs/notes/db.md`, «Связь у
    # только что созданной строки задаётся объектом, а не внешним ключом»).
    area = await repository.add(
        Area(
            project=project,
            project_id=project.id,
            key=parsed.key,
            title=title.strip(),
            description=description,
            **created_by_columns(actor.author),
        )
    )
    await case_service.record_project_created(session, area, actor=actor)
    return area


async def update_area(
    session: AsyncSession,
    area: Area,
    *,
    actor: Actor,
    title: str | None = None,
    description: str | None = None,
) -> Area:
    """Меняет название и описание; проект и ключ не меняются никогда.

    `None` — «поле не передано». Каждое изменённое поле подшивает `field_changed` с
    прежним и новым значением, все записи одного вызова делят `action_id`; значение,
    равное нынешнему, записи не оставляет.
    """
    await freeze.lock_unfrozen(session, area=area)
    # Под очередью перечитать: область разрешена из адреса до неё, и «было» в записи
    # иначе могло бы оказаться чужим устаревшим снимком.
    await session.refresh(area)

    changes = {
        TaskField.TITLE: None if title is None else title.strip(),
        TaskField.DESCRIPTION: (
            None if description is None else validate_area_description(description)
        ),
    }
    action_id = uuid.uuid4()
    for field, after in changes.items():
        before: str = getattr(area, field.value)
        if after is None or after == before:
            continue
        setattr(area, field.value, after)
        await case_service.record_project_field_changed(
            session,
            area,
            actor=actor,
            field=field,
            before=before,
            after=after,
            action_id=action_id,
        )
    await session.flush()
    return area


async def archive_area(
    session: AsyncSession, area: Area, *, actor: Actor, reason: str | None
) -> Entry:
    """Архивирует область с причиной; отдаёт подшитую запись `archived`.

    Повторное архивирование архивной отклоняет та же проверка заморозки, что и любое
    другое изменение, — первым шагом, до записи (`area_archived`; в архивном проекте —
    `project_archived`). `archived_at` — время записи `archived`.
    """
    checked = require_area_reason(reason, address=area.address, action="archive")
    await freeze.lock_unfrozen(session, area=area)
    entry = await case_service.record_archived(session, area, actor=actor, reason=checked)
    area.archived_at = entry.created_at
    await session.flush()
    return entry


async def restore_area(
    session: AsyncSession, area: Area, *, actor: Actor, reason: str | None
) -> Entry:
    """Восстанавливает область из архива с причиной; отдаёт подшитую `restored`.

    Запись `restored` архив пропускает (`freeze.UNFROZEN_ENTRY_TYPES`), поэтому архив
    проекта проверяется здесь явно: восстановить область в архивном проекте нельзя
    (`project_archived`). Живая область восстанавливать нечего —
    `area_not_archived`.
    """
    checked = require_area_reason(reason, address=area.address, action="restore")
    await lock_changes(session)
    await freeze.ensure_unfrozen(session, projects=(area.project,))
    # Под очередью перечитать: соседняя транзакция могла успеть его восстановить.
    await session.refresh(area)
    if area.archived_at is None:
        raise AreaNotArchivedError(details={"key": area.address})
    entry = await case_service.record_restored(session, area, actor=actor, reason=checked)
    area.archived_at = None
    await session.flush()
    return entry
