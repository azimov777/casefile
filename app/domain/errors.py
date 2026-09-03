"""Доменные ошибки — все в одном месте.

Соглашения требуют, чтобы доменные коды перечислялись в одном файле, а не заводились
по месту возникновения: когда фронтенду понадобится список кодов, его можно прочитать
целиком, а не собирать по репозиторию. Каждая следующая задача дописывает сюда свои.

Базовые семейства (`not_found`, `conflict`, `validation_error`, ...) живут в
`app/core/errors.py`; здесь только их наследники со своим стабильным кодом.

В списке фундамент (участники, токены, метка временного агента, очереди), задача с
переходами (задача 22) и дело: записи агента, обязательная сводка, вердикты
(задача 23). Связи приезжают сюда своей областью (задача 24).

Исключение из правила одно и оно осознанное: ошибка, описывающая не предметную
область, а механизм (недоступна база, испорчен курсор), живёт рядом с этим механизмом.
"""

from app.core.errors import ConflictError, NotFoundError, UnauthorizedError, ValidationError

# --- Участники ------------------------------------------------------------------


class ParticipantNotFoundError(NotFoundError):
    """Участника с таким именем или идентификатором нет."""

    code = "participant_not_found"
    message = "Participant not found"


class ParticipantNameTakenError(ConflictError):
    """Имя участника уже занято: имена уникальны без учёта регистра."""

    code = "participant_name_taken"
    message = "Participant name is already taken"


class InvalidParticipantNameError(ValidationError):
    """Имя участника не соответствует шаблону."""

    code = "invalid_participant_name"
    message = "Participant name is invalid"


# --- Автор действия -------------------------------------------------------------


class ActorLabelRequiredError(UnauthorizedError):
    """Общий агентский токен пришёл без метки временного агента.

    Токен без участника не называет автора сам: подписью становится заголовок
    `X-Actor-Label`. Без него запрос нельзя приписать никому, поэтому это отказ в
    аутентификации, а не ошибка формы запроса — самого действия трекер даже не
    рассматривает.
    """

    code = "actor_label_required"
    message = "Shared agent token requires the X-Actor-Label header"


class InvalidActorLabelError(ValidationError):
    """Метка временного агента не соответствует шаблону."""

    code = "invalid_actor_label"
    message = "Actor label is invalid"


# --- Токены доступа -------------------------------------------------------------


class TokenNotFoundError(NotFoundError):
    """Токена с таким идентификатором нет."""

    code = "token_not_found"
    message = "Token not found"


# --- Очереди --------------------------------------------------------------------


class QueueNotFoundError(NotFoundError):
    """Очереди с таким ключом нет."""

    code = "queue_not_found"
    message = "Queue not found"


class QueueKeyTakenError(ConflictError):
    """Ключ очереди уже занят: ключи уникальны без учёта регистра."""

    code = "queue_key_taken"
    message = "Queue key is already taken"


class InvalidQueueKeyError(ValidationError):
    """Ключ очереди не соответствует шаблону."""

    code = "invalid_queue_key"
    message = "Queue key is invalid"


# --- Задачи ---------------------------------------------------------------------------


class TaskNotFoundError(NotFoundError):
    """Задачи с таким ключом нет."""

    code = "task_not_found"
    message = "Task not found"


class InvalidTaskKeyError(ValidationError):
    """Ключ задачи не разбирается как `КЛЮЧ-НОМЕР`."""

    code = "invalid_task_key"
    message = "Task key is invalid"


class TaskFieldsInvalidError(ValidationError):
    """Одно или несколько полей задачи не проходят проверку; все замечания в `details.fields`."""

    code = "task_fields_invalid"
    message = "Task fields are invalid"


class TaskVersionConflictError(ConflictError):
    """Версия задачи разошлась: её изменили между чтением и записью.

    Отдельный код, а не общий `conflict`: клиент по нему понимает, что нужно перечитать
    задачу и повторить изменение, а не что запрос был неверным. Тихая перезапись здесь
    хуже отказа — потерянное чужое изменение обнаруживается спустя дни.
    """

    code = "version_conflict"
    message = "Task version is outdated"


class TaskClosedError(ConflictError):
    """Задача в `done` или `cancelled`: поля и связи закрытой задачи не меняются."""

    code = "task_closed"
    message = "Task is closed"


class TaskFieldLockedError(ConflictError):
    """Поле не редактируется в этом статусе: содержание задачи меняется только в `backlog`.

    Это конфликт состояния, а не ошибка формы запроса: тот же запрос пройдёт, когда
    задача вернётся в `backlog`.
    """

    code = "task_field_locked"
    message = "Field cannot be changed in the current status"


class TransitionNotAllowedError(ConflictError):
    """Перехода между этими статусами нет в таблице; допустимые перечислены в `details.allowed`."""

    code = "transition_not_allowed"
    message = "Transition is not allowed"


class TransitionReasonRequiredError(ValidationError):
    """Шаг назад по цепочке статусов и отмена требуют причины `reason`."""

    code = "transition_reason_required"
    message = "Transition requires a reason"


class TaskSectionsIncompleteError(ValidationError):
    """Перед `open` четыре раздела должны быть заполнены, а `checks` — не пуст.

    Незаполненные разделы перечислены в `details.fields` все сразу.
    """

    code = "task_sections_incomplete"
    message = "Task sections are incomplete"


# --- Дело ---------------------------------------------------------------------------


class EntryNotFoundError(NotFoundError):
    """Записи с таким номером в этой задаче нет."""

    code = "entry_not_found"
    message = "Case entry not found"


class EntryFieldsInvalidError(ValidationError):
    """Запись не проходит проверку формы; все замечания сразу — в `details.fields`.

    Один код на все замечания к записи — по той же причине, что и у полей задачи: агент
    исправляет запрос за одну попытку, читая список, а не за пять кругов «исправил
    одно — вылезло другое». Что именно не так, говорит `reason` каждого замечания:
    `required`, `not_allowed`, `service_type`, `out_of_range`, `unknown_participant`,
    `unknown_entry`, `not_a_question`.
    """

    code = "entry_fields_invalid"
    message = "Case entry fields are invalid"


class SummaryRequiredError(ConflictError):
    """Выход из `in_progress` требует сводки, подшитой после последнего входа в него.

    Конфликт состояния, а не ошибка формы запроса: тот же переход пройдёт, как только
    сводка появится. Это единственная защита от вежливого ухода из работы без справки
    для преемника (`CONCEPT.md`, 5.3).
    """

    code = "summary_required"
    message = "Transition out of in_progress requires a summary"


class ChecksNotPassedError(ConflictError):
    """`review → done` требует, чтобы последний вердикт каждой проверки был `passed`.

    Проверки без положительного вердикта перечислены в `details.checks`: и те, по
    которым вердикта нет вовсе, и те, где последний исход — `failed`.
    """

    code = "checks_not_passed"
    message = "Some review checks have no passing verdict"


class ActorNotAddressableError(ValidationError):
    """Временный агент спрашивает свои вопросы, а адресовать его нельзя.

    Возникает только у выдачи вопросов «мне»: у токена без участника адресата нет, и
    пустой список молча соврал бы, что вопросов не пришло.
    """

    code = "actor_not_addressable"
    message = "A temporary agent cannot be an addressee; pass an explicit addressee"
