"""Объявление правила в коде и реестр объявленных правил.

Правило — это функция с декоратором. Всё, что о нём нужно знать движку, объявлено рядом
с телом: ключ, название, форма, типы событий или расписание, схема параметров. Реестр
собирается при импорте модулей правил, а в базе от правила остаётся только состояние.

## Почему схема параметров — модель Pydantic, а не словарь

Схема нужна трижды: проверить параметры при сохранении, отдать их описание в OpenAPI и
дать правилу типизированный доступ к своим настройкам. Ручной словарь делал бы первое,
второе — вполсилы, а третье — никак. `BaseModel` даёт все три из одного объявления,
причём проверка при сохранении и разбор при выполнении — это буквально один и тот же
код, а не два похожих.

Слои от этого не нарушаются: Pydantic — библиотека, а не HTTP-слой, и правила лежат в
`app/automation`, который зависит от `services` наравне с `api` и `mcp`.

## Реестр и таблица — разные вещи, и путать их нельзя

В реестре живут **объявления** (что правило умеет), в таблице `automation_rules` —
**состояние** (включено ли, где, с какими параметрами). Синхронизация заводит строку под
каждое новое объявление и никогда не удаляет строку исчезнувшего правила: вместе с ней
каскадом ушёл бы журнал срабатываний.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from app.domain.automation import (
    RuleKind,
    validate_declaration,
    validate_rule_key,
)
from app.domain.errors import AutomationParamsInvalidError

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from app.automation.context import RuleContext


class NoParams(BaseModel):
    """Схема правила без настроек. Пустая модель, а не `None`.

    С `None` каждому месту, читающему параметры, пришлось бы отдельно обрабатывать
    случай «схемы нет» — а таких мест четыре: проверка при сохранении, разбор при
    выполнении, ответ API и генерация OpenAPI. Пустая модель проходит через все четыре
    тем же путём, что и любая другая.
    """

    model_config = {"extra": "forbid"}


#: Тело правила: получает контекст, возвращает результат работы. Возврат `None`
#: означает «сделал то, что описано действиями в контексте» — отдельного значения для
#: этого случая заводить не пришлось.
type RuleHandler = Callable[["RuleContext"], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Объявление правила: всё, что известно о нём из кода.

    Неизменяемое: объявление меняется только правкой кода и выкладкой. Всё, что должно
    меняться без перезапуска, лежит в строке `AutomationRule`.
    """

    key: str
    name: str
    kind: RuleKind
    handler: RuleHandler
    description: str = ""
    #: Типы событий, на которые реагирует триггер. Пусто у остальных форм.
    events: tuple[str, ...] = ()
    #: Период автодействия. `None` у остальных форм.
    schedule: timedelta | None = None
    #: Отбор задач автодействия строкой языка запросов. Строка, а не разобранный
    #: фильтр: функции языка (`me()`, `today()`) обязаны вычисляться в момент запуска,
    #: и разбор при объявлении зафиксировал бы дату выкладки навсегда.
    query: str | None = None
    params_model: type[BaseModel] = NoParams

    def parse_params(self, raw: dict[str, Any]) -> BaseModel:
        """Разбирает параметры схемой правила. Мусор — `automation_params_invalid`.

        Одна функция и для проверки при сохранении, и для разбора при выполнении: две
        проверки одного набора однажды разошлись бы, и правило запускалось бы с
        параметрами, которых не приняло сохранение.
        """
        try:
            return self.params_model.model_validate(raw)
        except ValidationError as exc:
            raise AutomationParamsInvalidError(
                details={
                    "rule": self.key,
                    "fields": [
                        {
                            "field": ".".join(str(part) for part in error["loc"]) or "__root__",
                            "reason": error["type"],
                            "message": error["msg"],
                        }
                        for error in exc.errors()
                    ],
                },
            ) from exc

    def default_params(self) -> dict[str, Any]:
        """Параметры по умолчанию: то, с чем правило заводится при синхронизации.

        Схема с обязательным полем без значения по умолчанию даёт пустой словарь, а не
        ошибку: правило приезжает выключенным, и требовать настройку в момент, когда
        его ещё никто не видел, значило бы ронять синхронизацию всего реестра.
        """
        try:
            return self.params_model().model_dump(mode="json")
        except ValidationError:
            return {}

    def params_schema(self) -> dict[str, Any]:
        """JSON Schema параметров — уезжает в ответ API и в OpenAPI."""
        return self.params_model.model_json_schema()


class RuleRegistry:
    """Реестр объявленных правил. Ключ уникален на весь процесс."""

    def __init__(self) -> None:
        self._rules: dict[str, RuleDefinition] = {}

    def register(self, definition: RuleDefinition) -> RuleDefinition:
        """Добавляет объявление. Повтор ключа — ошибка, а не молчаливая замена.

        Причина та же, по которой её не допускает реестр подписчиков: подменённое
        правило исчезает из обработки, всё продолжает работать, и обнаруживается это
        как «правило перестало срабатывать» через неделю после того, как две задачи
        выбрали один ключ.
        """
        if definition.key in self._rules:
            raise ValueError(f"Automation rule {definition.key!r} is already registered")
        self._rules[definition.key] = definition
        return definition

    def get(self, key: str) -> RuleDefinition | None:
        return self._rules.get(key)

    def all(self) -> tuple[RuleDefinition, ...]:
        """Объявления в порядке ключа: список правил в API не должен зависеть от импортов."""
        return tuple(self._rules[key] for key in sorted(self._rules))

    def of_kind(self, kind: RuleKind) -> tuple[RuleDefinition, ...]:
        return tuple(item for item in self.all() if item.kind is kind)

    def for_event(self, event_type: str) -> tuple[RuleDefinition, ...]:
        """Триггеры, подписанные на этот тип события."""
        return tuple(
            item
            for item in self.all()
            if item.kind is RuleKind.TRIGGER and event_type in item.events
        )

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._rules))

    def clear(self) -> None:
        """Опустошает реестр. Нужен тестам: реестр глобальный, а тесты — независимые."""
        self._rules.clear()


#: Реестр приложения. Правила регистрируются при импорте своего модуля.
registry = RuleRegistry()


def rule(
    *,
    key: str,
    name: str,
    kind: RuleKind,
    description: str = "",
    events: Iterable[str] = (),
    schedule: timedelta | None = None,
    query: str | None = None,
    params: type[BaseModel] = NoParams,
) -> Callable[[RuleHandler], RuleHandler]:
    """Объявляет правило и кладёт его в реестр.

        @rule(key="notify_stale", name="...", kind=RuleKind.SCHEDULED,
              schedule=timedelta(hours=6), query="status_category: in_progress")
        async def notify_stale(ctx: RuleContext) -> None: ...

    Функция возвращается как есть: правило остаётся обычной корутиной, которую можно
    позвать в тесте напрямую, без движка и без базы.
    """
    normalized_key = validate_rule_key(key)
    event_types = tuple(str(item) for item in events)
    validate_declaration(
        key=normalized_key,
        name=name,
        kind=kind,
        events=event_types,
        schedule=schedule,
        query=query,
    )

    def decorator(handler: RuleHandler) -> RuleHandler:
        registry.register(
            RuleDefinition(
                key=normalized_key,
                name=name,
                kind=kind,
                handler=handler,
                description=description.strip() or (handler.__doc__ or "").strip(),
                events=event_types,
                schedule=schedule,
                query=query,
                params_model=params,
            )
        )
        return handler

    return decorator


#: Модули, объявляющие правила. Импортируются перед первым обращением к реестру —
#: иначе декораторы не выполнятся и реестр останется пустым. Новое правило добавляется
#: строкой сюда; трогать движок, воркер и планировщик при этом не нужно.
RULE_MODULES: tuple[str, ...] = (
    "app.automation.rules.close_children_with_parent",
    "app.automation.rules.nudge_stale_issues",
    "app.automation.rules.prepare_release",
)


def load_rules() -> tuple[str, ...]:
    """Импортирует модули правил и возвращает ключи объявленных.

    Идемпотентна за счёт кеша модулей: повторный вызов ничего не переимпортирует и
    потому ничего не регистрирует второй раз. Поэтому её можно звать из любого места,
    которому понадобился реестр, и не заводить отдельный шаг инициализации, о котором
    надо помнить в каждом из четырёх процессов проекта.
    """
    for module in RULE_MODULES:
        importlib.import_module(module)
    return registry.keys()


@dataclass(frozen=True, slots=True)
class RuleAction:
    """Одно выполненное действие правила: что сделано и с чем.

    Копится в контексте и уезжает в журнал срабатываний. Без этого списка журнал
    отвечает «сработало», но не «что именно сделало» — а это первый вопрос того, кто
    разбирает последствия.
    """

    action: str
    target: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {"action": self.action, "target": self.target, **self.details}
