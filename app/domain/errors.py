"""Доменные ошибки — все в одном месте.

Соглашения требуют, чтобы доменные коды перечислялись в одном файле, а не заводились
по месту возникновения: когда фронтенду понадобится список кодов, его можно прочитать
целиком, а не собирать по репозиторию. Каждая следующая задача дописывает сюда свои.

Базовые семейства (`not_found`, `conflict`, `validation_error`, ...) живут в
`app/core/errors.py`; здесь только их наследники со своим стабильным кодом.

Сейчас в списке фундамент: участники, токены, метка временного агента и очереди.
Задача, дело и связи приезжают сюда вместе со своими областями (задачи 22–24).

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
