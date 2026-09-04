"""Первый экран одним запросом.

Интерфейс человека начинается с трёх вопросов: кто я, какие есть очереди и сколько
вопросов ждут моего ответа. По отдельности всё это уже отдают `GET /participants/{name}`,
`GET /queues` и `GET /questions`, но три запроса ради первой отрисовки — это три круга
задержки и три состояния загрузки в интерфейсе, который ещё ничего не показал.

Сценарий ничего не считает сам: он складывает результаты трёх существующих сценариев.
Своей логики здесь нет намеренно — иначе счётчик первого экрана начал бы жить отдельно
от «входящей» и однажды показал бы другое число на тех же данных.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.pagination import MAX_PAGE_SIZE
from app.services import case as case_service
from app.services import queues as queues_service
from app.services.auth import Actor


@dataclass(frozen=True, slots=True)
class Bootstrap:
    """Состояние установки глазами того, кто только что открыл интерфейс."""

    #: Участник за токеном. Пуст у общего агентского токена: за ним стоит временный
    #: агент, которого в реестре нет.
    participant: Participant | None
    queues: list[Queue]
    #: Открытые вопросы, адресованные `participant`. Ноль при пустом участнике — это
    #: факт, а не умолчание: адресовать временного агента нельзя (`CONCEPT.md`, 3.6),
    #: поэтому вопросов ему не приходит и прийти не может.
    open_questions: int


async def read_bootstrap(session: AsyncSession, *, actor: Actor) -> Bootstrap:
    """Текущий участник, очереди установки и число открытых вопросов к нему.

    Очереди читаются одной страницей с общим потолком размера: очередь — единственный
    уровень группировки, и установка, у которой их больше двух сотен, первым экраном
    всё равно не описывается. Такой установке нужен `GET /api/v1/queues` с курсором;
    поле `queues_total` здесь не заводится, потому что объём первого экрана закрыт
    (`docs/tasks`, задача 29): текущий участник, очереди, число вопросов.
    """
    page = await queues_service.list_queues(session, actor=actor, limit=MAX_PAGE_SIZE)
    open_questions = (
        0
        if actor.participant is None
        else await case_service.count_open_questions(session, participant=actor.participant)
    )
    return Bootstrap(
        participant=actor.participant,
        queues=page.items,
        open_questions=open_questions,
    )
