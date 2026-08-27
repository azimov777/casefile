"""Доменные ошибки — все в одном месте.

Соглашения требуют, чтобы доменные коды перечислялись в одном файле, а не заводились
по месту возникновения: когда фронтенду понадобится список кодов, его можно прочитать
целиком, а не собирать по репозиторию. Каждая следующая задача дописывает сюда свои.

Базовые семейства (`not_found`, `conflict`, `validation_error`, ...) живут в
`app/core/errors.py`; здесь только их наследники со своим стабильным кодом.

Исключение из правила одно и оно осознанное: ошибка, описывающая не предметную
область, а механизм (недоступна база, испорчен курсор), живёт рядом с этим механизмом.
"""

from app.core.errors import ConflictError, NotFoundError, ValidationError

# --- Акторы ---------------------------------------------------------------------


class ActorNotFoundError(NotFoundError):
    """Актора с таким ключом или идентификатором нет."""

    code = "actor_not_found"
    message = "Actor not found"


class ActorKeyTakenError(ConflictError):
    """Ключ актора уже занят: ключ уникален на всю установку."""

    code = "actor_key_taken"
    message = "Actor key is already taken"


class InvalidActorKeyError(ValidationError):
    """Ключ не соответствует шаблону или зарезервирован."""

    code = "invalid_actor_key"
    message = "Actor key is invalid"


class ActorInactiveError(ConflictError):
    """Актор отключён: выпускать ему токены и действовать от его имени нельзя."""

    code = "actor_inactive"
    message = "Actor is inactive"


class SystemActorProtectedError(ConflictError):
    """Системный актор управляется приложением, а не API.

    Его нельзя ни создать, ни отключить, ни выпустить ему токен: автоматика ходит от
    его имени внутри процесса, и внешний токен на него означал бы возможность выдать
    себя за автоматику.
    """

    code = "system_actor_protected"
    message = "System actor is managed by the application"


# --- Токены доступа -------------------------------------------------------------


class ApiTokenNotFoundError(NotFoundError):
    """Токена с таким идентификатором у актора нет."""

    code = "api_token_not_found"
    message = "API token not found"


# --- Очереди --------------------------------------------------------------------


class QueueNotFoundError(NotFoundError):
    """Очереди с таким ключом нет."""

    code = "queue_not_found"
    message = "Queue not found"


class QueueKeyTakenError(ConflictError):
    """Ключ очереди уже занят: он уникален на всю установку и неизменяем после создания."""

    code = "queue_key_taken"
    message = "Queue key is already taken"


class InvalidQueueKeyError(ValidationError):
    """Ключ очереди не соответствует шаблону."""

    code = "invalid_queue_key"
    message = "Queue key is invalid"


class InvalidIssueKeyError(ValidationError):
    """Ключ задачи не разбирается: ожидается `КЛЮЧ-НОМЕР`, например `TRK-123`."""

    code = "invalid_issue_key"
    message = "Issue key is invalid"


class QueueArchivedError(ConflictError):
    """Очередь в архиве: новые задачи в неё не заводятся.

    Настройки архивной очереди править можно — иначе её нельзя было бы привести в
    порядок перед возвратом из архива.
    """

    code = "queue_archived"
    message = "Queue is archived"


class QueueNotEmptyError(ConflictError):
    """В очереди есть задачи: удалять её нельзя, для этого есть архивация."""

    code = "queue_not_empty"
    message = "Queue still has issues"


# --- Задачи ---------------------------------------------------------------------


class IssueNotFoundError(NotFoundError):
    """Задачи с таким ключом нет."""

    code = "issue_not_found"
    message = "Issue not found"


class IssueVersionConflictError(ConflictError):
    """Версия задачи разошлась: её изменили между чтением и записью.

    Отдельный код, а не общий `conflict`: клиент по нему понимает, что нужно перечитать
    задачу и повторить изменение, а не что запрос был неверным. Тихая перезапись здесь
    хуже отказа — потерянное чужое изменение обнаруживается спустя дни.
    """

    code = "version_conflict"
    message = "Issue was changed by someone else"


class IssueReferencedError(ConflictError):
    """На задачу ссылаются кастомные поля других задач: удалять её нельзя.

    Тихое удаление оставило бы в чужих значениях ключ, за которым ничего нет: форма
    показала бы пустое поле, фильтр по нему не нашёл бы ничего, а понять причину было бы
    нельзя. Сначала снимают ссылки, потом удаляют задачу.
    """

    code = "issue_referenced"
    message = "Issue is referenced by other issues"


class InvalidIssueSummaryError(ValidationError):
    """Название задачи пустое, многострочное или слишком длинное."""

    code = "invalid_issue_summary"
    message = "Issue summary is invalid"


class InvalidIssueDescriptionError(ValidationError):
    """Описание задачи длиннее допустимого."""

    code = "invalid_issue_description"
    message = "Issue description is invalid"


class InvalidIssueDeadlineError(ValidationError):
    """Дедлайн пришёл без таймзоны: домысливать её за клиента нельзя."""

    code = "invalid_issue_deadline"
    message = "Issue deadline is invalid"


class InvalidIssueTagsError(ValidationError):
    """Тег задачи многострочный, слишком длинный, либо тегов слишком много."""

    code = "invalid_issue_tags"
    message = "Issue tags are invalid"


# --- Справочники: статусы, типы задач, резолюции ---------------------------------


class InvalidCatalogKeyError(ValidationError):
    """Ключ записи справочника не соответствует шаблону."""

    code = "invalid_catalog_key"
    message = "Catalog key is invalid"


class InvalidCatalogRefError(ValidationError):
    """Ссылка на запись справочника не разбирается: ожидается `key` или `QUEUE.key`."""

    code = "invalid_catalog_ref"
    message = "Catalog reference is invalid"


class CatalogEntryUnavailableError(ValidationError):
    """Запись существует, но в этой очереди недоступна.

    Две причины: запись принадлежит другой очереди (локальная область) либо отключена.
    В обоих случаях назначать её значением по умолчанию или целью переноса нельзя —
    иначе очередь получила бы конфигурацию, которой не может пользоваться.
    """

    code = "catalog_entry_unavailable"
    message = "Catalog entry is not available in this queue"


class StatusNotFoundError(NotFoundError):
    """Статуса с такой ссылкой нет."""

    code = "status_not_found"
    message = "Status not found"


class IssueTypeNotFoundError(NotFoundError):
    """Типа задачи с такой ссылкой нет."""

    code = "issue_type_not_found"
    message = "Issue type not found"


class ResolutionNotFoundError(NotFoundError):
    """Резолюции с такой ссылкой нет."""

    code = "resolution_not_found"
    message = "Resolution not found"


class StatusKeyTakenError(ConflictError):
    """Ключ статуса занят в этой области: глобально либо внутри очереди."""

    code = "status_key_taken"
    message = "Status key is already taken in this scope"


class IssueTypeKeyTakenError(ConflictError):
    """Ключ типа задачи занят в этой области."""

    code = "issue_type_key_taken"
    message = "Issue type key is already taken in this scope"


class ResolutionKeyTakenError(ConflictError):
    """Ключ резолюции занят в этой области."""

    code = "resolution_key_taken"
    message = "Resolution key is already taken in this scope"


class StatusInUseError(ConflictError):
    """Статус используется: в нём стоят задачи или он назначен очереди по умолчанию.

    Удаление такого статуса запрещено намеренно. Тихое удаление оставило бы задачи со
    ссылкой в никуда и сломало доски и расчёт прогресса проектов, а удаление «с
    переносом» одним движением слишком легко сделать не глядя. Перенос задач в другой
    статус — отдельный явный сценарий, после него удаление проходит.
    """

    code = "status_in_use"
    message = "Status is in use"


class IssueTypeInUseError(ConflictError):
    """Тип задачи используется: есть задачи этого типа или он назначен по умолчанию."""

    code = "issue_type_in_use"
    message = "Issue type is in use"


class ResolutionInUseError(ConflictError):
    """Резолюция используется задачами."""

    code = "resolution_in_use"
    message = "Resolution is in use"


class StatusCategoryLockedError(ConflictError):
    """Категорию статуса с задачами менять нельзя.

    Категория — это машинный смысл статуса (`new` / `in_progress` / `done`). Смена её
    на лету переопределяет задним числом, какие задачи считаются закрытыми: прогресс
    проектов, доски и отчёты изменятся, хотя ни одна задача не двигалась.
    """

    code = "status_category_locked"
    message = "Status category cannot be changed while issues use the status"


# --- Реестр полей ---------------------------------------------------------------


class InvalidFieldKeyError(ValidationError):
    """Ключ поля не соответствует шаблону или занят системным полем задачи."""

    code = "invalid_field_key"
    message = "Field key is invalid"


class InvalidFieldRefError(ValidationError):
    """Ссылка на поле не разбирается: ожидается `key` или `QUEUE.key`."""

    code = "invalid_field_ref"
    message = "Field reference is invalid"


class FieldNotFoundError(NotFoundError):
    """Поля с такой ссылкой нет."""

    code = "field_not_found"
    message = "Field not found"


class FieldKeyTakenError(ConflictError):
    """Ключ поля занят в этой области: глобально либо внутри очереди."""

    code = "field_key_taken"
    message = "Field key is already taken in this scope"


class InvalidFieldDefinitionError(ValidationError):
    """Описание поля противоречит само себе.

    Перечисление без вариантов, варианты у не-перечисления, дубли ключей вариантов,
    значение по умолчанию не того типа. Причина — в `details.reason`: код один, потому
    что для клиента это одна ситуация «поле описано неверно, вот что именно».
    """

    code = "invalid_field_definition"
    message = "Field definition is invalid"


class FieldTypeLockedError(ConflictError):
    """У поля есть значения: тип и множественность менять нельзя.

    Смена типа задним числом переопределила бы уже записанное: строка «2026-08-27»
    осталась бы в JSONB, но читалась бы как число, а история изменений — как ссылка на
    актора. Переименование и обязательность менять можно сколько угодно.
    """

    code = "field_type_locked"
    message = "Field type cannot be changed while the field has values"


class FieldInUseError(ConflictError):
    """Поле используется задачами: жёстко удалить его нельзя, только скрыть.

    Скрытое поле остаётся в реестре: значения в задачах никуда не деваются и история
    изменений остаётся читаемой, но новые значения в него не пишутся и в конфигурации
    очереди его больше нет.
    """

    code = "field_in_use"
    message = "Field is in use"


class FieldUnavailableError(ValidationError):
    """Поле существует, но в этой очереди или у этого типа задачи неприменимо."""

    code = "field_unavailable"
    message = "Field is not available here"


class FieldValuesInvalidError(ValidationError):
    """Значения кастомных полей не прошли проверку.

    В `details.fields` лежит **весь** список замечаний, а не первое: фронту нужно
    подсветить всю форму за один ответ, а агенту — исправить запрос за одну попытку.
    Форма записи описана в `app/domain/fields.py` (`FieldIssue`).
    """

    code = "field_values_invalid"
    message = "Custom field values failed validation"
