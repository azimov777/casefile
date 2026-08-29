"""Внешний вид события и отбор для живого потока.

Чистый Python: ни ORM, ни HTTP. Здесь две вещи, и обе общие для каналов наружу.

## Одна форма события на вебхук и на SSE

`build_event_view` собирает то, что видит внешний получатель: идентификаторы, ключи
объектов, текст и подробности. Вебхук добавляет к ней идентификатор доставки и больше
ничего. Две сборки одной и той же формы разъехались бы полями в первый же месяц, и
фронтенд с внешним подписчиком стали бы понимать одно событие по-разному.

Снимка задачи целиком в ней нет намеренно. Наружу уходит то, по чему получатель
принимает решение и может сходить в API за остальным: объём полезной нагрузки на чужой
стороне — это объём утечки, а для фронтенда — объём, который он всё равно перезапросит
свежим.

## Отбор потока идёт по аудитории, а не по строкам события

`StreamFilter` спрашивает `EventAudience` — ту же, что считает домен уведомлений по
нагрузке. Сравнивать `object_key` со строкой было бы короче и неверно: у комментария он
`TRK-7:<uuid>`, у связи — пара ключей, и фильтр «по задаче TRK-7» терял бы половину
событий этой задачи.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.notifications import EventAudience, describe

#: Потолок числа типов в фильтре потока. Ограничение не от жадности: список едет в
#: строке запроса, и без потолка туда уедет весь словарь событий, удвоив длину адреса.
MAX_FILTER_EVENT_TYPES = 50


def build_event_view(
    *,
    event_id: str | None,
    event_type: str,
    object_type: str,
    object_key: str,
    actor_key: str,
    occurred_at: datetime,
    payload: Mapping[str, Any],
    audience: EventAudience,
) -> dict[str, Any]:
    """Событие в том виде, в каком его видит внешний получатель.

    `summary` и `details` собирает домен уведомлений (`describe`) — тот же текст, что
    приходит в инбокс. Это не экономия, а требование: одно событие обязано читаться
    одинаково в ленте агента, в вебхуке и в потоке фронтенда.
    """
    summary = describe(event_type, payload)
    return {
        "event": {
            "id": event_id,
            "type": event_type,
            "actor": actor_key,
            "occurred_at": occurred_at.isoformat(),
        },
        "object": {"type": object_type, "key": object_key},
        "issue": audience.issue_key,
        "queue": audience.queue_key,
        "projects": sorted(audience.project_keys),
        "summary": summary.body,
        "details": summary.details,
    }


@dataclass(frozen=True, slots=True)
class StreamFilter:
    """Чем сужен поток: очередь, проект, задача, набор типов.

    Условия складываются по «и»: поток с очередью и типом отдаёт события этой очереди
    этого типа. Пустой фильтр отдаёт всё — поток без сужения это нормальный случай, а
    не забытая настройка.
    """

    queue: str | None = None
    project: str | None = None
    issue: str | None = None
    event_types: frozenset[str] = frozenset()

    @property
    def is_empty(self) -> bool:
        """Ничем не сужен. Нужно потоку только для строки в логе."""
        return not (self.queue or self.project or self.issue or self.event_types)

    def accepts(self, event_type: str, audience: EventAudience) -> bool:
        """Подходит ли событие под сужение потока."""
        if self.event_types and event_type not in self.event_types:
            return False
        if self.queue is not None and audience.queue_key != self.queue:
            return False
        if self.project is not None and self.project not in audience.project_keys:
            return False
        return not (self.issue is not None and audience.issue_key != self.issue)


def parse_event_types(values: Iterable[str] | None) -> frozenset[str]:
    """Набор типов из строки запроса: пустой означает «все».

    Неизвестные типы здесь **не** отвергаются, в отличие от подписки. Разница в цене
    ошибки: подписка живёт годами и опечатка в ней означает канал, который молча ничего
    не доставляет, а поток открывается на минуты и его пустоту видно сразу. Зато
    фронтенд может фильтровать по типу, которого сервер ещё не знает, и не падать на
    выкатке разных версий.
    """
    return frozenset(item.strip() for item in values or () if item.strip())


def parse_last_event_id(value: str | None) -> uuid.UUID | None:
    """Разбирает `Last-Event-ID`. Мусор — это `None`, а не исключение.

    Разбор отделён от проверки существования события намеренно: «строка не похожа на
    идентификатор» и «такого события нет» — разные состояния, и сценарий отвечает на них
    одинаково лишь потому, что так решил, а не потому, что не мог их различить.
    """
    if not value:
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None
