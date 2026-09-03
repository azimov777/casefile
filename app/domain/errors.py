"""Доменные ошибки — все в одном месте.

Соглашения требуют, чтобы доменные коды перечислялись в одном файле, а не заводились
по месту возникновения: когда фронтенду понадобится список кодов, его можно прочитать
целиком, а не собирать по репозиторию. Каждая следующая задача дописывает сюда свои.

Базовые семейства (`not_found`, `conflict`, `validation_error`, ...) живут в
`app/core/errors.py`; здесь только их наследники со своим стабильным кодом.

Сейчас в списке одни акторы и токены: остальной домен переписывается заново задачами
21-29, и коды вернутся сюда вместе со своими областями.

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

    Его нельзя ни создать, ни отключить, ни выпустить ему токен: служебные записи
    делаются от его имени внутри процесса, и внешний токен на него означал бы
    возможность выдать себя за сам трекер.
    """

    code = "system_actor_protected"
    message = "System actor is managed by the application"


# --- Токены доступа -------------------------------------------------------------


class ApiTokenNotFoundError(NotFoundError):
    """Токена с таким идентификатором у актора нет."""

    code = "api_token_not_found"
    message = "API token not found"
