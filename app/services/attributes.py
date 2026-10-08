"""Сценарии по атрибутам проекта и области: задать значение, снять, прочитать.

Атрибут — справочный факт проекта или области (TRK#84, TRK#57). Нынешнее
значение лежит строкой `project_attributes` или `area_attributes`, история —
служебными записями дела владельца, подшитыми в той же транзакции: `attribute_created`,
`attribute_changed`, `attribute_removed`. Механика у обоих владельцев одна, и сценарии
одни: владелец — `CaseOwner` из `app/services/case.py`.

## Одно действие «задать значение», три исхода

Для агента заведение и изменение — одно действие: есть ли атрибут уже, ему знать не
нужно (`TRK-164#9`). Какую запись подшить, решает сценарий по тому, что нашёл под
очередью изменений: атрибута нет — `attribute_created`, причина необязательна; есть с
другим значением — `attribute_changed`, причина обязательна; есть с тем же значением —
ничего: правки не было, и причины такое «изменение» не требует (как `update_project`).

## Права

Набор `task`, как у записей в дело проекта: атрибуты ведёт рабочий цикл агента, а не
управление установкой (TRK#100).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.area import Area
from app.db.models.attribute import Attribute
from app.db.models.entry import Entry
from app.db.repositories import AttributeRepository
from app.domain.attributes import (
    attribute_lookup_name,
    normalize_attribute_reason,
    require_attribute_reason,
    validate_attribute_name,
    validate_attribute_value,
)
from app.domain.errors import AttributeNotFoundError
from app.services import case as case_service
from app.services import freeze
from app.services.auth import Actor
from app.services.case import CaseOwner, owner_name


@dataclass(frozen=True, slots=True)
class AttributeSet:
    """Итог `set_attribute`: атрибут после вызова и подшитая запись.

    `entry` — `None`, когда присланное значение совпало с нынешним: правки не было, и в
    деле ничего не появилось.
    """

    attribute: Attribute
    entry: Entry | None


async def list_attributes(
    session: AsyncSession, project: CaseOwner, *, actor: Actor
) -> list[Attribute]:
    """Нынешние значения всех атрибутов проекта или области, по имени без учёта
    регистра."""
    return await AttributeRepository(session).list_for(project)


async def _lock_unfrozen(session: AsyncSession, owner: CaseOwner) -> None:
    """Первый шаг сценария атрибута: очередь изменений и заморозка владельца."""
    if isinstance(owner, Area):
        await freeze.lock_unfrozen(session, area=owner)
    else:
        await freeze.lock_unfrozen(session, project=owner)


async def set_attribute(
    session: AsyncSession,
    project: CaseOwner,
    *,
    actor: Actor,
    name: str,
    value: str,
    reason: str | None = None,
) -> AttributeSet:
    """Заводит атрибут или меняет его значение — тип записи выбирает трекер.

    Проверки формы — до очереди изменений: отказ по шаблону имени или длине значения не
    зависит от состояния. Поиск существующего — под очередью: иначе «было» в записи могло
    бы оказаться чужим устаревшим снимком, а два параллельных заведения одного имени
    разошлись бы на уникальном индексе вместо честного «изменено».
    """
    name = validate_attribute_name(name)
    value = validate_attribute_value(value)
    await _lock_unfrozen(session, project)

    repository = AttributeRepository(session)
    attribute = await repository.get_by_name(project, attribute_lookup_name(name))
    if attribute is None:
        attribute = await repository.add(project, name=name, value=value)
        entry = await case_service.record_attribute_created(
            session,
            project,
            actor=actor,
            name=attribute.name,
            after=value,
            reason=normalize_attribute_reason(reason),
        )
        return AttributeSet(attribute=attribute, entry=entry)

    if attribute.value == value:
        return AttributeSet(attribute=attribute, entry=None)

    # Имя в записи — хранимое, а не присланное: `REPO` и `repo` — один атрибут, и история
    # одного атрибута не должна распадаться на два написания.
    checked_reason = require_attribute_reason(reason, name=attribute.name, action="change")
    before = attribute.value
    attribute.value = value
    await session.flush()
    entry = await case_service.record_attribute_changed(
        session,
        project,
        actor=actor,
        name=attribute.name,
        before=before,
        after=value,
        reason=checked_reason,
    )
    return AttributeSet(attribute=attribute, entry=entry)


async def remove_attribute(
    session: AsyncSession,
    project: CaseOwner,
    *,
    actor: Actor,
    name: str,
    reason: str | None,
) -> Entry:
    """Снимает атрибут с обязательной причиной; отдаёт подшитую `attribute_removed`.

    Строка удаляется: всё, что о ней было, уже в деле проекта, а последняя запись
    называет и значение, и причину. Нет атрибута — `attribute_not_found`; причина
    проверяется после поиска, чтобы снятие несуществующего отвечало «нет такого», а не
    «назови причину».
    """
    name = validate_attribute_name(name)
    await _lock_unfrozen(session, project)

    repository = AttributeRepository(session)
    attribute = await repository.get_by_name(project, attribute_lookup_name(name))
    if attribute is None:
        raise AttributeNotFoundError(details={"key": owner_name(project), "name": name})
    checked_reason = require_attribute_reason(reason, name=attribute.name, action="remove")
    stored_name, before = attribute.name, attribute.value
    await repository.remove(attribute)
    return await case_service.record_attribute_removed(
        session,
        project,
        actor=actor,
        name=stored_name,
        before=before,
        reason=checked_reason,
    )
