"""Записи знания дела проекта и дела области — решения и заметки: статус, который
считается при чтении.

Решение — запись `decision` дела проекта (TRK#88) или дела области, заметка —
запись `finding` того же дела. Замена у них одна в обоих делах (решение TRK#57, раздел 5):
новая запись называет прежнюю того же типа в `supersedes`, и прежняя перестаёт
действовать. Отдельной сущности и хранимого статуса нет: запись действует, пока ни одна
более поздняя запись того же типа и того же дела не назвала её в `supersedes`. Так же, при
чтении, считается признак `blocked` у задачи — из связей, а не из колонки (TRK#158).
Выбор владельца — `TRK-554#6` (развилка 1а) для решений, TRK#48 — для заметок,
TRK#57 — для дела области.

Проверка человеком (TRK-755) устроена так же: запись `decision_review` в деле называет
решение и исход — `confirmed`, `rejected` или `removed`. `rejected` и `removed` выводят
решение из силы без преемника, `confirmed` и подпись человека делают его проверенным
(`review_state`). Всё это считается при чтении из записей, хранимого статуса нет.

Здесь только правило: из номеров, типов, `supersedes` и проверок получить статус,
преемника и `review_state` каждой записи.
Какие записи прочитать и как ответить на ссылку задачи, решает `app/services/decisions.py` —
домен в базу не ходит.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.case import EntryType


class DecisionStatus(StrEnum):
    """Действует ли запись знания — решение или заметка дела проекта или области.

    Хранимым значением не бывает: только при чтении. Имя осталось от решений, первых
    записей с заменой; у заметки два значения — `in_force` и `superseded` (TRK#48).
    Решение, кроме них, бывает `rejected` и `removed` — человек отклонил его или удалил
    (TRK-755): оба выводят решение из силы, преемника у них нет.
    """

    IN_FORCE = "in_force"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    REMOVED = "removed"


class ReviewOutcome(StrEnum):
    """Исход проверки решения человеком: поле `outcome` записи `decision_review`.

    `rejected` — «не согласен», `removed` — «устарело»; для действия они одно и то же:
    решение больше не действует, запись остаётся в деле (слово владельца, TRK-755).
    """

    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    REMOVED = "removed"


#: Исходы, которые выводят решение из силы.
WITHDRAWING_OUTCOMES: frozenset[ReviewOutcome] = frozenset(
    {ReviewOutcome.REJECTED, ReviewOutcome.REMOVED}
)


class ReviewState(StrEnum):
    """Видел ли решение человек: `confirmed` — да, `unconfirmed` — нет.

    Считается при чтении у решения дела проекта или области; у заметки состояния нет.
    """

    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True, slots=True)
class Review:
    """Проверка решения: номер записи `decision_review`, номер решения и исход."""

    no: int
    decision: int
    outcome: ReviewOutcome


def review_of_payload(no: int, payload: Mapping[str, Any]) -> Review | None:
    """Проверка из записи `decision_review`; `None` — нагрузка не по форме (такой записи
    сценарий не подшивает, и чтение её пропускает, а не падает)."""
    decision = payload.get("decision")
    try:
        outcome = ReviewOutcome(payload.get("outcome"))
    except ValueError:
        return None
    if not isinstance(decision, int) or isinstance(decision, bool):
        return None
    return Review(no=no, decision=decision, outcome=outcome)


def withdrawals(
    reviews: Iterable[Review], decision_nos: Collection[int]
) -> dict[int, ReviewOutcome]:
    """Решения, выведенные из силы человеком: номер → `rejected` или `removed`.

    Проверка действует на более раннее решение дела (`decision_nos` — номера решений, а
    не заметок). Из силы выводит первая такая проверка: проверить можно только действующее
    решение, а вторая в данных — обход проверки.
    """
    found: dict[int, ReviewOutcome] = {}
    for review in sorted(reviews, key=lambda item: item.no):
        if (
            review.outcome in WITHDRAWING_OUTCOMES
            and review.decision < review.no
            and review.decision in decision_nos
        ):
            found.setdefault(review.decision, review.outcome)
    return found


def confirmations(reviews: Iterable[Review], decision_nos: Collection[int]) -> dict[int, int]:
    """Подтверждённые решения: номер решения → номер первой записи подтверждения."""
    found: dict[int, int] = {}
    for review in sorted(reviews, key=lambda item: item.no):
        if (
            review.outcome is ReviewOutcome.CONFIRMED
            and review.decision < review.no
            and review.decision in decision_nos
        ):
            found.setdefault(review.decision, review.no)
    return found


def successors(entries: Iterable[tuple[int, EntryType, Sequence[int]]]) -> dict[int, int]:
    """Преемник каждой заменённой записи: номер записи → номер той, что её заменила.

    На вход — тройки «номер записи, её тип, номера, которые она заменяет» одного дела.
    Заменяет только более поздняя запись того же типа: решение — решение, заметка —
    заметку. Другое отклоняет проверка замены (`entry_fields_invalid`), и номер чужого
    типа в данных — обход проверки, а не замена.

    Заменить можно только действующую запись (`decision_not_in_force`,
    `finding_not_in_force`), поэтому у записи не больше одного преемника. Если в данных
    их всё же два — это обход проверки, а не рабочее состояние, — побеждает более раннее:
    оно заменило запись первым, а второе ссылалось на уже заменённую.
    """
    ordered = sorted(entries, key=lambda triple: triple[0])
    type_of = {no: entry_type for no, entry_type, _ in ordered}
    found: dict[int, int] = {}
    for no, entry_type, replaced in ordered:
        for old in replaced:
            if old < no and type_of.get(old) is entry_type:
                found.setdefault(old, no)
    return found


def status_of(
    no: int,
    successor_of: Mapping[int, int],
    withdrawn: Mapping[int, ReviewOutcome] | None = None,
) -> DecisionStatus:
    """Статус записи по уже собранным картам преемников и снятий человеком.

    Заменённое остаётся заменённым, даже если человек отклонил его преемника: преемник
    отклонён позже, а прежнее решение им уже было выведено из силы.
    """
    if no in successor_of:
        return DecisionStatus.SUPERSEDED
    outcome = None if withdrawn is None else withdrawn.get(no)
    if outcome is ReviewOutcome.REJECTED:
        return DecisionStatus.REJECTED
    if outcome is ReviewOutcome.REMOVED:
        return DecisionStatus.REMOVED
    return DecisionStatus.IN_FORCE


def review_state_of(
    no: int, confirmed_by: Mapping[int, int], human_decisions: Collection[int]
) -> tuple[ReviewState, int | None]:
    """Состояние проверки решения и номер записи подтверждения.

    `confirmed`, если есть запись `confirmed` или решение подписал человек (его слово
    и есть подтверждение, записи проверки у такого решения нет — номер `None`).
    Иначе `unconfirmed`: так читаются все решения, подшитые агентами.
    """
    entry = confirmed_by.get(no)
    if entry is not None:
        return ReviewState.CONFIRMED, entry
    if no in human_decisions:
        return ReviewState.CONFIRMED, None
    return ReviewState.UNCONFIRMED, None
