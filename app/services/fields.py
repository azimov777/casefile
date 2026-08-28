"""Сценарии по реестру полей: создание, изменение, применимость, проверка значений.

Область поля (`queue`) сюда приходит уже разрешённым объектом, а не ключом, и типы
задач — тоже. Так этот модуль не зависит от сценариев очередей, и зависимость между
ними остаётся односторонней: очереди знают про поля (конфигурация очереди отдаёт их
списком, а разрешение ссылки `TRK.severity` требует найти очередь), поля про очереди —
нет. Обратная зависимость замкнула бы два модуля в цикл.

Проверка значений живёт здесь, а не в домене, ровно в одной части: существование
актора и задачи, на которых ссылается значение, видно только базе. Всё остальное —
типы, обязательность, множественность, перечисления — проверяет `app/domain/fields.py`,
и проверяется оно без базы.

Транзакцию функции не фиксируют: границу держит вход в приложение.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sentinels import UNSET, is_set
from app.db.models.actor import Actor
from app.db.models.catalog import IssueType
from app.db.models.field import Field
from app.db.models.queue import Queue
from app.db.pagination import Page
from app.db.repositories import ActorRepository, FieldRepository, WorkflowRepository
from app.domain.catalogs import CatalogKind
from app.domain.errors import (
    CatalogEntryUnavailableError,
    FieldInUseError,
    FieldKeyTakenError,
    FieldNotFoundError,
    FieldTypeLockedError,
    FieldValuesInvalidError,
    InvalidFieldDefinitionError,
)
from app.domain.fields import (
    MAX_ENUM_OPTIONS,
    FieldIssue,
    FieldOption,
    FieldSpec,
    FieldValueType,
    format_field_ref,
    referenced_actor_keys,
    referenced_issue_keys,
    validate_field_key,
    validate_values,
)
from app.services import catalogs as catalogs_service
from app.services import issue_usage
from app.services.permissions import ensure_allowed


def field_ref(field: Field) -> str:
    """Ссылка на поле: `severity` для глобального, `TRK.severity` для локального.

    Ключ очереди берётся из самой записи, а не из контекста вызова: контекст можно
    перепутать и отдать поле одной очереди под именем другой, а связь ошибиться не
    может. Связь загружается стратегией `selectin`, поэтому у глобального поля
    (`queue_id IS NULL`) обращения к базе не будет вовсе.
    """
    queue_key = field.queue.key if field.queue_id is not None else None
    return format_field_ref(field.key, queue_key=queue_key)


def field_options(field: Field) -> tuple[FieldOption, ...]:
    """Варианты перечисления из JSONB в доменный вид."""
    return tuple(FieldOption(key=item["key"], name=item["name"]) for item in field.options)


def spec_of(field: Field) -> FieldSpec:
    """Модель поля → описание для валидатора. Единственный мост между ORM и доменом."""
    return FieldSpec(
        ref=field_ref(field),
        value_type=field.value_type,
        is_multiple=field.is_multiple,
        is_required=field.is_required,
        options=field_options(field),
        default=field.default_value,
    )


async def get_field(session: AsyncSession, *, key: str, queue: Queue | None) -> Field:
    """Поле по ключу в указанной области или `field_not_found`.

    Прав не проверяет: точка входа интерфейса — `resolve_field_ref` в
    `app/services/queues.py`, она разбирает ссылку `TRK.severity` и проверяет права.
    """
    normalized = validate_field_key(key)
    field = await FieldRepository(session).get(normalized, None if queue is None else queue.id)
    if field is None:
        raise FieldNotFoundError(
            details={
                "ref": format_field_ref(normalized, queue_key=None if queue is None else queue.key),
            },
        )
    return field


async def list_fields(
    session: AsyncSession,
    *,
    initiator: Actor,
    queue: Queue | None = None,
    issue_type: IssueType | None = None,
    is_hidden: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Field]:
    """Страница реестра.

    Без очереди отдаются только глобальные поля, с очередью — доступные в ней:
    глобальные плюс её собственные. Локальное поле вне своей очереди не показывается
    никогда — его ключ имеет смысл только внутри этой очереди.

    С типом задачи набор сужается до применимых к нему: поле без ограничений
    применимо ко всем типам, поле с ограничениями — только к перечисленным.
    """
    ensure_allowed(initiator, "field.list")
    return await FieldRepository(session).list_page(
        queue_id=None if queue is None else queue.id,
        issue_type_id=None if issue_type is None else issue_type.id,
        is_hidden=is_hidden,
        limit=limit,
        cursor=cursor,
    )


async def applicable_fields(
    session: AsyncSession,
    *,
    queue: Queue | None,
    issue_type: IssueType | None = None,
    include_hidden: bool = False,
) -> list[Field]:
    """Поля, применимые к связке «очередь + тип задачи», в порядке показа.

    Это ответ на вопрос «какие поля есть у задачи такого типа в этой очереди»: им
    пользуются конфигурация очереди, форма создания задачи и валидатор значений.
    Скрытые поля из набора исключены — кроме случая, когда их просят явно: валидатору
    они нужны, чтобы сказать «поле скрыто» вместо «такого поля нет».
    """
    return await FieldRepository(session).list_applicable(
        None if queue is None else queue.id,
        None if issue_type is None else issue_type.id,
        include_hidden=include_hidden,
    )


async def create_field(
    session: AsyncSession,
    *,
    initiator: Actor,
    key: str,
    name: str,
    value_type: FieldValueType,
    queue: Queue | None = None,
    is_multiple: bool = False,
    is_required: bool = False,
    options: list[FieldOption] | None = None,
    default_value: Any = None,
    display_order: int = 0,
    issue_types: list[IssueType] | None = None,
) -> Field:
    """Заводит поле — глобальное или локальное для очереди.

    Тип и множественность выбираются здесь и потом у поля с данными не меняются,
    поэтому описание проверяется целиком уже сейчас: перечисление без вариантов,
    варианты у не-перечисления и значение по умолчанию не того типа отвергаются.
    """
    ensure_allowed(initiator, "field.create")
    normalized = validate_field_key(key)

    repository = FieldRepository(session)
    queue_id = None if queue is None else queue.id
    if await repository.get(normalized, queue_id) is not None:
        raise FieldKeyTakenError(
            details={
                "key": normalized,
                "queue": None if queue is None else queue.key,
            },
        )

    stored_options = _validated_options(value_type, options)
    restrictions = _validated_issue_types(queue, issue_types)
    stored_default = _validated_default(
        ref=format_field_ref(normalized, queue_key=None if queue is None else queue.key),
        value_type=value_type,
        is_multiple=is_multiple,
        options=stored_options,
        default_value=default_value,
    )

    # Связь `queue`, а не `queue_id`: объект должен знать свою очередь сразу, иначе
    # сборка ссылки `TRK.severity` в ответе полезет за ней в базу вне async-контекста.
    field = Field(
        key=normalized,
        name=name.strip(),
        value_type=value_type,
        is_multiple=is_multiple,
        is_required=is_required,
        options=[{"key": option.key, "name": option.name} for option in stored_options],
        default_value=stored_default,
        display_order=display_order,
        queue=queue,
        issue_types=restrictions,
    )
    return await repository.add(field)


async def update_field(
    session: AsyncSession,
    field: Field,
    *,
    initiator: Actor,
    name: str | None = None,
    is_required: bool | None = None,
    is_hidden: bool | None = None,
    value_type: FieldValueType | None = None,
    is_multiple: bool | None = None,
    options: list[FieldOption] | None = None,
    default_value: Any = UNSET,
    display_order: int | None = None,
    issue_types: list[IssueType] | None = None,
) -> Field:
    """Меняет описание поля. `None` означает «поле не передано».

    Ключ поля не меняется никогда: на него ссылаются значения в задачах, фильтры и
    правила автоматики, и переименование ключа тихо порвало бы все эти ссылки. Для
    человека есть отображаемое название, его менять можно сколько угодно.

    Тип и множественность меняются только у поля без значений — иначе уже записанное
    задним числом стало бы значить другое. Обязательность и порядок показа меняются
    всегда: они ничего в хранилище не переопределяют.

    Значение по умолчанию различает три состояния: не передано — не трогаем,
    передано `null` — снимаем, передано значение — проверяем и ставим. Отличить
    первое от второго обязательно: иначе умолчание нельзя было бы убрать.
    """
    ensure_allowed(initiator, "field.update", target=field)

    target_type = value_type if value_type is not None else field.value_type
    target_multiple = is_multiple if is_multiple is not None else field.is_multiple
    if target_type is not field.value_type or target_multiple != field.is_multiple:
        await _ensure_no_values(
            session,
            field,
            requested={"value_type": target_type.value, "is_multiple": target_multiple},
        )

    target_options = (
        _validated_options(target_type, options) if options is not None else field_options(field)
    )
    if options is not None:
        await _ensure_removed_options_are_free(session, field, target_options)

    if issue_types is not None:
        restrictions = _validated_issue_types(field.queue, issue_types)
        await _ensure_workflow_requirements_remain_applicable(
            session,
            field,
            restrictions,
        )
        await FieldRepository(session).set_issue_types(field, restrictions)

    field.value_type = target_type
    field.is_multiple = target_multiple
    # JSONB-колонку нельзя менять на месте: SQLAlchemy не отслеживает мутации внутри
    # значения и UPDATE просто не уйдёт. Присваивается всегда новый список.
    field.options = [{"key": option.key, "name": option.name} for option in target_options]

    if name is not None:
        field.name = name.strip()
    if is_required is not None:
        field.is_required = is_required
    if is_hidden is not None:
        if is_hidden and not field.is_hidden:
            await _ensure_not_workflow_requirement(session, field)
        field.is_hidden = is_hidden
    if display_order is not None:
        field.display_order = display_order

    if is_set(default_value):
        field.default_value = _validated_default(
            ref=field_ref(field),
            value_type=target_type,
            is_multiple=target_multiple,
            options=target_options,
            default_value=default_value,
        )
    elif value_type is not None or is_multiple is not None or options is not None:
        # Тип поменялся — прежнее умолчание могло перестать ему соответствовать.
        # Молча оставить его нельзя: оно попало бы в задачу значением чужого типа.
        field.default_value = _validated_default(
            ref=field_ref(field),
            value_type=target_type,
            is_multiple=target_multiple,
            options=target_options,
            default_value=field.default_value,
        )

    await session.flush()
    return field


async def delete_field(session: AsyncSession, field: Field, *, initiator: Actor) -> None:
    """Удаляет поле, если у него нет значений. Иначе — только скрыть.

    Жёсткое удаление поля со значениями оставило бы в задачах данные без описания, а
    в истории изменений — записи о поле, которого нет: она стала бы нечитаемой.
    Поэтому удаление разрешено только у поля, которым ещё не пользовались, а для
    остальных есть `PATCH` с `is_hidden: true` — поле исчезает из конфигурации, но
    данные и история остаются на месте.
    """
    ensure_allowed(initiator, "field.delete", target=field)
    reference = field_ref(field)
    used_by = await issue_usage.count_issues_with_field(session, reference)
    if used_by:
        raise FieldInUseError(
            details={
                "ref": reference,
                "reason": "issues_exist",
                "issues": used_by,
                "hint": "hide the field instead",
            },
        )
    await _ensure_not_workflow_requirement(session, field)
    await FieldRepository(session).delete(field)


async def _ensure_not_workflow_requirement(
    session: AsyncSession,
    field: Field,
) -> None:
    reference = field_ref(field)
    transitions = await WorkflowRepository(session).count_required_field_usage(reference)
    if transitions:
        raise FieldInUseError(
            details={
                "ref": reference,
                "reason": "workflows_exist",
                "transitions": transitions,
                "hint": "remove the field from workflow transition requirements first",
            }
        )


async def _ensure_workflow_requirements_remain_applicable(
    session: AsyncSession,
    field: Field,
    restrictions: list[IssueType],
) -> None:
    if not restrictions:
        return
    allowed = {issue_type.id for issue_type in restrictions}
    bindings = await WorkflowRepository(session).assignments_requiring_field(field_ref(field))
    incompatible = [
        {
            "queue": binding.workflow.queue.key,
            "issue_type": binding.issue_type.ref,
            "workflow_id": str(binding.workflow_id),
        }
        for binding in bindings
        if binding.issue_type_id not in allowed
    ]
    if incompatible:
        raise FieldInUseError(
            details={
                "ref": field_ref(field),
                "reason": "required_field_not_applicable",
                "assignments": incompatible,
                "hint": "remove the requirement or keep the field applicable",
            }
        )


async def issue_reference_refs(session: AsyncSession) -> list[str]:
    """Ссылки всех полей, которые хранят ссылку на задачу.

    Нужны удалению задачи: чтобы понять, ссылается ли кто-то на неё, надо знать, под
    какими ключами в `values` вообще могут лежать ключи задач. Реестр знает это, а
    таблица задач — нет, поэтому список собирается здесь.
    """
    fields = await FieldRepository(session).list_by_value_type(FieldValueType.ISSUE)
    return [field_ref(field) for field in fields]


async def validate_issue_values(
    session: AsyncSession,
    *,
    queue: Queue,
    issue_type: IssueType,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Проверяет значения кастомных полей задачи и возвращает их в форме хранения.

    Набор считается полным: обязательные поля проверяются по нему целиком. Для
    частичного обновления вызывающий сначала склеивает текущее состояние с
    изменениями (`apply_value_changes` из домена), а потом проверяет результат.

    Все замечания уходят одним ответом, а не по первому: фронту нужно подсветить всю
    форму за раз, агенту — исправить запрос за одну попытку.
    """
    fields = await applicable_fields(
        session, queue=queue, issue_type=issue_type, include_hidden=True
    )
    visible = [field for field in fields if not field.is_hidden]
    specs = [spec_of(field) for field in visible]

    outcome = validate_values(values, specs)
    issues = list(outcome.issues)
    issues = await _explain_unknown_fields(session, issues, queue=queue, issue_type=issue_type)
    issues.extend(await _missing_references(session, outcome.values, specs))

    if issues:
        raise FieldValuesInvalidError(details={"fields": [issue.as_details() for issue in issues]})
    return outcome.values


async def _explain_unknown_fields(
    session: AsyncSession,
    issues: list[FieldIssue],
    *,
    queue: Queue,
    issue_type: IssueType,
) -> list[FieldIssue]:
    """Уточняет «такого поля нет» до «скрыто» или «неприменимо к этому типу».

    Дополнительный запрос идёт только по ветке отказа: в успешном случае неизвестных
    полей нет вовсе. Без уточнения агент, приславший `TRK.severity` в задачу типа
    `task`, получил бы `unknown_field` и пошёл заводить поле, которое уже есть.
    """
    if not any(issue.reason == "unknown_field" for issue in issues):
        return issues

    scope = await applicable_fields(session, queue=queue, include_hidden=True)
    by_ref = {field_ref(field): field for field in scope}

    explained: list[FieldIssue] = []
    for issue in issues:
        field = by_ref.get(issue.field) if issue.reason == "unknown_field" else None
        if field is None:
            explained.append(issue)
        elif field.is_hidden:
            explained.append(
                FieldIssue(
                    field=issue.field,
                    reason="hidden",
                    context={"hint": "the field is hidden and accepts no new values"},
                )
            )
        else:
            explained.append(
                FieldIssue(
                    field=issue.field,
                    reason="not_applicable",
                    context={
                        "issue_type": catalogs_service.format_entry_ref(issue_type),
                        "applies_to": [
                            catalogs_service.format_entry_ref(entry) for entry in field.issue_types
                        ],
                    },
                )
            )
    return explained


async def _missing_references(
    session: AsyncSession,
    values: dict[str, Any],
    specs: list[FieldSpec],
) -> list[FieldIssue]:
    """Ссылки на несуществующих акторов и задачи.

    Единственная часть проверки, которой нужна база: форму ссылки проверил домен,
    существование объекта видно только здесь. Запрос идёт один на все ссылки набора.
    """
    issues: list[FieldIssue] = []

    actor_keys = referenced_actor_keys(values, specs)
    missing_actors = actor_keys - await ActorRepository(session).existing_keys(actor_keys)
    issues.extend(
        _reference_issues(values, specs, FieldValueType.ACTOR, missing_actors, "actor_not_found")
    )

    issue_keys = referenced_issue_keys(values, specs)
    missing_issues = await issue_usage.missing_issue_keys(session, issue_keys)
    issues.extend(
        _reference_issues(values, specs, FieldValueType.ISSUE, missing_issues, "issue_not_found")
    )
    return issues


def _reference_issues(
    values: dict[str, Any],
    specs: list[FieldSpec],
    value_type: FieldValueType,
    missing: set[str],
    reason: str,
) -> list[FieldIssue]:
    if not missing:
        return []
    issues: list[FieldIssue] = []
    for spec in specs:
        if spec.value_type is not value_type or spec.ref not in values:
            continue
        stored = values[spec.ref]
        for value in stored if isinstance(stored, list) else [stored]:
            if value in missing:
                issues.append(FieldIssue(field=spec.ref, reason=reason, context={"value": value}))
    return issues


def _validated_options(
    value_type: FieldValueType,
    options: list[FieldOption] | None,
) -> tuple[FieldOption, ...]:
    """Варианты перечисления: обязательны у `enum` и бессмысленны у остальных типов.

    Молча проглотить варианты у числового поля нельзя: вызывающий получил бы успешный
    ответ и уверенность, что список применён. Через HTTP схема этого не поймает —
    поле одно на все типы, — а сценарий вызывается ещё из MCP и из фоновых процессов.
    """
    if value_type is not FieldValueType.ENUM:
        if options:
            raise InvalidFieldDefinitionError(
                details={
                    "field": "options",
                    "reason": "options_belong_to_enum_only",
                    "type": value_type.value,
                },
            )
        return ()

    if not options:
        raise InvalidFieldDefinitionError(
            details={"field": "options", "reason": "enum_requires_options"},
        )
    if len(options) > MAX_ENUM_OPTIONS:
        raise InvalidFieldDefinitionError(
            details={"field": "options", "reason": "too_many_options", "max": MAX_ENUM_OPTIONS},
        )

    normalized: list[FieldOption] = []
    seen: set[str] = set()
    for option in options:
        key = validate_field_key(option.key)
        if key in seen:
            raise InvalidFieldDefinitionError(
                details={"field": "options", "reason": "duplicate_option_key", "key": key},
            )
        seen.add(key)
        normalized.append(FieldOption(key=key, name=option.name.strip()))
    return tuple(normalized)


def _validated_default(
    *,
    ref: str,
    value_type: FieldValueType,
    is_multiple: bool,
    options: tuple[FieldOption, ...],
    default_value: Any,
) -> Any:
    """Значение по умолчанию проверяется тем же валидатором, что и значение в задаче.

    Иначе умолчание жило бы по своим правилам и однажды положило бы в задачу то, что
    сама задача принять не может: проверка при создании прошла бы, а при сохранении
    задачи — нет, и виноватым выглядело бы поле, заведённое месяц назад.
    """
    if default_value is None:
        return None

    spec = FieldSpec(
        ref=ref,
        value_type=value_type,
        is_multiple=is_multiple,
        options=options,
    )
    outcome = validate_values({ref: default_value}, [spec])
    if outcome.issues:
        raise InvalidFieldDefinitionError(
            details={
                "field": "default_value",
                "reason": "not_valid_for_this_type",
                "errors": [issue.as_details() for issue in outcome.issues],
            },
        )
    return outcome.values.get(ref)


def _validated_issue_types(
    queue: Queue | None,
    issue_types: list[IssueType] | None,
) -> list[IssueType]:
    """Типы задач, которыми ограничено поле. Пустой список — ограничений нет.

    Глобальное поле ограничивается только глобальными типами: локальный тип чужой
    очереди сделал бы глобальное поле применимым ровно в одной очереди, и понять это
    по описанию поля было бы нельзя. Локальное поле ограничивается типами, доступными
    в его очереди, — той же проверкой, что и остальная конфигурация очереди.
    """
    if not issue_types:
        return []

    checked: list[IssueType] = []
    seen: set[str] = set()
    for entry in issue_types:
        if queue is None:
            if entry.queue_id is not None:
                raise CatalogEntryUnavailableError(
                    details={
                        "kind": CatalogKind.ISSUE_TYPE.value,
                        "ref": catalogs_service.format_entry_ref(entry),
                        "reason": "global_field_needs_global_issue_types",
                    },
                )
        else:
            catalogs_service.ensure_available_in_queue(
                entry, kind=CatalogKind.ISSUE_TYPE, queue=queue
            )
        if str(entry.id) not in seen:
            seen.add(str(entry.id))
            checked.append(entry)
    return checked


async def _ensure_no_values(
    session: AsyncSession,
    field: Field,
    *,
    requested: dict[str, Any],
) -> None:
    """Тип и множественность поля с данными менять нельзя."""
    reference = field_ref(field)
    used_by = await issue_usage.count_issues_with_field(session, reference)
    if used_by:
        raise FieldTypeLockedError(
            details={
                "ref": reference,
                "value_type": field.value_type.value,
                "is_multiple": field.is_multiple,
                "requested": requested,
                "issues": used_by,
            },
        )


async def _ensure_removed_options_are_free(
    session: AsyncSession,
    field: Field,
    target: tuple[FieldOption, ...],
) -> None:
    """Вариант перечисления, которым пользуются задачи, из списка убрать нельзя.

    Иначе задачи остались бы со значением, которого нет среди допустимых: форма
    показала бы пустое поле, а фильтр по нему — ничего. Переименовать вариант можно
    сколько угодно: хранится ключ, а не название.
    """
    if field.value_type is not FieldValueType.ENUM:
        return
    reference = field_ref(field)
    remaining = {option.key for option in target}
    for option in field_options(field):
        if option.key in remaining:
            continue
        used_by = await issue_usage.count_issues_with_field_value(session, reference, option.key)
        if used_by:
            raise FieldInUseError(
                details={
                    "ref": reference,
                    "reason": "option_in_use",
                    "option": option.key,
                    "issues": used_by,
                },
            )
