"""Базовые исключения приложения.

Доменные и сервисные слои бросают наследников `AppError` и ничего не знают про HTTP.
Превращение исключения в ответ живёт в `app/api/errors.py` — это единственное место,
где код ошибки встречается с транспортом.

Правило для наследников: у каждого свой стабильный `code` в snake_case — он часть
контракта с фронтендом и с MCP-клиентами, менять его нельзя так же, как имя поля в API.
Тексты сообщений — на английском: это технический контракт, а не интерфейс для человека,
переводом занимается тот, кто показывает ошибку пользователю.
"""

from typing import Any


class AppError(Exception):
    """Ошибка приложения, у которой есть стабильный код и HTTP-статус.

    Наследники переопределяют атрибуты класса; конструктор нужен там, где сообщение
    или подробности зависят от конкретного случая.
    """

    code: str = "internal_error"
    status_code: int = 500
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.details: dict[str, Any] = details or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class NotFoundError(AppError):
    """Запрошенного объекта не существует."""

    code = "not_found"
    status_code = 404
    message = "Object not found"


class ConflictError(AppError):
    """Состояние объекта не позволяет выполнить операцию: дубликат ключа, гонка версий."""

    code = "conflict"
    status_code = 409
    message = "State conflict"


class ValidationError(AppError):
    """Входные данные синтаксически корректны, но нарушают правило предметной области."""

    code = "validation_error"
    status_code = 422
    message = "Validation failed"


class PermissionDeniedError(AppError):
    """Действие запрещено. В v1 ролей нет, но точка отказа существует с самого начала."""

    code = "permission_denied"
    status_code = 403
    message = "Action is not allowed"
