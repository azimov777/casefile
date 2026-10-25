"""Настройка установки: имя, значение, кто и когда изменил.

Слово владельца TRK~31#4. Строка — только значение, которое задал человек: умолчание
окружения и кода в таблицу не копируется. Пустое значение означает «брать из
окружения», строка при этом остаётся, чтобы было видно, кто и когда вернул умолчание.

Имя — одно из реестра (`app/domain/installation_settings.py`); база держит только
уникальность. Правила значений (тип, пределы) проверяет домен: они меняются вместе с
кодом, а ограничение в базе потребовало бы миграции на каждое. Тип значения — текст в
каноническом виде (`true`, `168`, `PT2592000S`), как его пишет `format_value`.

Таблицы нет в архиве установки (`EXCLUDED_TABLES`): это настройка машины, а не данные
трекера, и значения, выбранные для одной установки, чужой не навязываются.
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel, string_enum
from app.domain.authors import Author, AuthorKind


class InstallationSetting(BaseModel):
    """Значение одной настройки установки. Время изменения — `updated_at` базовой модели."""

    __tablename__ = "installation_settings"

    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_by_kind: Mapped[AuthorKind] = mapped_column(
        string_enum(AuthorKind, name="setting_updated_by_kind", length=16), nullable=False
    )
    updated_by_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @property
    def updated_by(self) -> Author:
        return Author(kind=self.updated_by_kind, signature=self.updated_by_signature)
