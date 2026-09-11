"""Сведения об установке: то, что одинаково для любого запросившего.

Первый экран (`app/services/bootstrap.py`) отвечает на «кто я» и зависит от токена.
Здесь — обратное: факты самой установки, которые не зависят от того, кто спрашивает, и
меняются только с её настройкой. Сегодня такой факт один — публичный адрес MCP, из
которого интерфейс собирает конфигурацию клиента агента. В `bootstrap` он не положен
намеренно: он нужен одному экрану, а не первому кадру (`docs/CONCEPT.md`, 5.1; TRK-65#9).

Базы сценарию не нужно: адрес — свойство настроек процесса, а не данных.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.tokens import TokenScope
from app.services.auth import Actor
from app.services.permissions import ensure_scope


@dataclass(frozen=True, slots=True)
class Installation:
    """Факты установки глазами клиента, который к ней подключается."""

    #: Адрес MCP целиком — схема, хост, порт и путь, — по которому к нему подключается
    #: клиент агента. Задан владельцем (`TRACKER_MCP_PUBLIC_URL`) или выведен из порта и
    #: пути процесса для локальной установки (`Settings.effective_mcp_public_url`).
    mcp_url: str


def read_installation(*, actor: Actor, settings: Settings) -> Installation:
    """Сведения об установке. Открыты любому набору: секрета в них нет.

    Настройки приходят аргументом, а не берутся из `get_settings()`: отвечать обязано
    то приложение, которое обслуживает запрос, — с теми же настройками, с которыми оно
    собрано (`app/main.py`, `create_app`).
    """
    ensure_scope(actor, TokenScope.TASK, action="installation.read")
    return Installation(mcp_url=settings.effective_mcp_public_url)
