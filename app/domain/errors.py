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
