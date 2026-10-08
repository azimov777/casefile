"""Учётная запись: то, чем человек входит в установку (TRK#72, TRK#190)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel, string_enum
from app.db.models.author import CreatedByMixin
from app.db.models.participant import Participant
from app.domain.accounts import MAX_EMAIL_LENGTH
from app.domain.onboarding import OnboardingHints, OnboardingState, OnboardingStatus


class Account(BaseModel, CreatedByMixin):
    """Почта, хеш пароля, флаг администратора и отключение — у одного участника-человека.

    Отдельная таблица, а не колонки участника, потому что жизнь у них разная: участника
    нельзя ни удалить, ни отключить — его имя стоит подписью в делах, — а учётную запись
    отключают, когда человек уходит из команды (`disabled_at`). Подписи при этом
    остаются: они принадлежат участнику, а не учётной записи. Удаления нет и здесь — по
    той же причине, что у токена: строка объясняет, кто входил раньше.

    `password_hash` пуст у учётной записи, в которую войти паролем нельзя: её завела
    сама установка (`owner@localhost`), и на своей машине ключ интерфейса приходит без
    входа. Пароль ей задаёт администратор или сам человек, когда установка уходит в сеть.
    """

    __tablename__ = "accounts"

    # Один к одному: у человека одна учётная запись, и `UNIQUE` держит это в схеме, а не
    # в проверке сценария, которую обошла бы гонка двух заведений.
    participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # Хранится канонизированной (нижний регистр), как имя участника: уникальность без
    # учёта регистра держит обычное `UNIQUE`. Канонизирует домен (`validate_email`).
    email: Mapped[str] = mapped_column(String(MAX_EMAIL_LENGTH), unique=True, nullable=False)
    # Строка `scrypt:...` (`app/domain/passwords.py`); разбирается при каждой проверке,
    # а не хранится разобранной: формат тот же, что у перенесённого `TRACKER_PASSWORD_HASH`.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    disabled_at: Mapped[datetime | None] = mapped_column(default=None)

    # Состояние знакомства (`TRK-360#17`, `TRK-369`): первая настройка человека на
    # сервере, а не ход работы — поэтому у неё нет записи в деле (TRK#200,
    # 5.1 и 5.4). Три колонки, а не один объект JSONB: `status` отбирает будущий список
    # задач («кому показать экран «Начало»»), и заводить его через путь внутри
    # JSONB-значения было бы менее очевидно, чем колонка. Умолчания здесь — те же, что и
    # в миграции после её `ALTER COLUMN ... SET DEFAULT`: новая учётная запись начинает
    # с `pending` и пустыми подсказками; существовавшая до этого поля получила `skipped`
    # и `hidden_all: true` самой миграцией (`20260928_1200_onboarding_state`).
    onboarding_status: Mapped[OnboardingStatus] = mapped_column(
        string_enum(OnboardingStatus, name="onboarding_status", length=16),
        default=OnboardingStatus.PENDING,
        server_default=text("'pending'"),
        nullable=False,
    )
    onboarding_hidden_all: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    onboarding_hidden: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )

    # Учётную запись читают почти всегда ради участника: подпись, имя, токены.
    participant: Mapped[Participant] = relationship(lazy="joined", innerjoin=True)

    @property
    def is_disabled(self) -> bool:
        return self.disabled_at is not None

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def onboarding(self) -> OnboardingState:
        """Состояние знакомства как один объект — то, что отдаёт `AccountRead.onboarding`."""
        return OnboardingState(
            status=self.onboarding_status,
            hints=OnboardingHints(
                hidden_all=self.onboarding_hidden_all,
                hidden=tuple(self.onboarding_hidden),
            ),
        )
