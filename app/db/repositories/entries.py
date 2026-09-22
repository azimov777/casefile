"""Вставки и выборки по записям дела.

Методов правки и удаления здесь нет и не будет: записи неизменяемы
(`CONCEPT.md`, 3.4). Ошибочная запись исправляется следующей записью.

## Вопрос открыт, пока на него нет ответа

Отдельной колонки «отвечено» нет: она была бы вторым местом, где живёт правда, и
разошлась бы с делом в первый же откат транзакции. Открытость считается запросом —
«нет записи `answer` с этим `question_no` в той же задаче», — и опирается на частичный
GIN-индекс по нагрузке вопросов (миграция `case entry lookups`).

Замечание устроено так же: открыто, пока в задаче нет `resolution` с его номером
(`_unresolved`). Одна форма на два правила — не совпадение, а требование: две разные
механики «открытости» разошлись бы в первом же крайнем случае.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, case, distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.entry import Entry
from app.db.models.task import Task
from app.db.pagination import (
    Page,
    decode_sort_cursor,
    encode_sort_cursor,
    resolve_limit,
)
from app.domain.authors import Author
from app.domain.case import (
    AGENT_ENTRY_TYPES,
    FIRST_ENTRY_NUMBER,
    OUTCOME_WITH_CONTINUATION,
    AnswerFacts,
    AssigneeChangedFacts,
    EntryFacts,
    EntryHeading,
    EntryType,
    FieldChangedFacts,
    LinkFacts,
    NoFacts,
    QuestionFacts,
    RemarkOutcome,
    ResolutionFacts,
    SectionChangedFacts,
    StatusChangedFacts,
    VerdictFacts,
    VerdictOutcome,
)
from app.domain.links import LinkKind
from app.domain.tasks import CLOSED_STATUSES, TaskField, TaskStatus


class EntryRepository:
    """Доступ к таблице `entries`: добавить и прочитать."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allocate_no(self, task_id: uuid.UUID) -> int:
        """Следующий номер записи в задаче — без дыр и без гонок.

        Сначала блокируется строка задачи (`SELECT ... FOR UPDATE`), потом считается
        `max(no) + 1`. Блокировка держится до конца транзакции, поэтому две
        параллельные записи в одну задачу получают разные номера: вторая ждёт коммита
        первой и уже видит её строку. Откатившаяся транзакция ничего не вставила и
        номер не теряет — в отличие от счётчика на задаче, который оставил бы дыру.

        Цена — сериализация записей **в одну задачу** до конца транзакции. Для дела это
        и есть нужное свойство: страницы подшиваются по одной.

        Берётся **после** очереди изменений (`app/db/locks.py`, `lock_changes`), а не
        до неё: обратный порядок двух блокировок даёт взаимную блокировку.
        """
        lock = select(Task.id).where(Task.id == task_id).with_for_update()
        if await self._session.scalar(lock) is None:
            # Строка исчезнуть не может — задачи не удаляются, — но молчаливый `None`
            # превратился бы в запись без задачи.
            raise RuntimeError(f"Task {task_id} disappeared while allocating an entry number")
        highest = select(func.coalesce(func.max(Entry.no), FIRST_ENTRY_NUMBER - 1)).where(
            Entry.task_id == task_id
        )
        return int(await self._session.scalar(highest)) + 1

    async def add(self, entry: Entry) -> Entry:
        """Отправляет INSERT. Номер `no` вызывающий берёт у `allocate_no` заранее.

        Две функции, а не одна с побочным эффектом: номер — часть содержимого записи,
        и его выдача не должна прятаться внутри «добавить».
        """
        self._session.add(entry)
        await self._session.flush()
        return entry

    # --- Чтение записей задачи -------------------------------------------------------

    async def get_by_no(self, task_id: uuid.UUID, no: int) -> Entry | None:
        """Одна запись по её номеру внутри задачи — адрес из ссылки `TRK-42#12`."""
        statement = select(Entry).where(Entry.task_id == task_id, Entry.no == no)
        return (await self._session.scalars(statement)).one_or_none()

    async def existing_nos(self, task_id: uuid.UUID, nos: Sequence[int]) -> set[int]:
        """Какие из перечисленных номеров в задаче есть. Одним запросом на весь список.

        Проверка ссылок записи идёт по этому методу: список `refs` короткий, но запрос
        на каждую ссылку превратил бы подшивку записи в десяток обращений к базе.
        """
        if not nos:
            return set()
        statement = select(Entry.no).where(Entry.task_id == task_id, Entry.no.in_(set(nos)))
        return set(await self._session.scalars(statement))

    async def list_page(
        self,
        task_id: uuid.UUID,
        *,
        nos: Sequence[int] | None = None,
        types: Sequence[EntryType] | None = None,
        after_no: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Entry]:
        """Страница записей задачи в порядке `no`, с телами и нагрузкой.

        Порядок — номер в задаче, а не `(created_at, id)` общей пагинации: записи одной
        транзакции получают одно `created_at`, и только `no` даёт тот порядок, в котором
        их подшивали. Курсор — общий `encode_sort_cursor` из модуля пагинации: свой
        разбор курсора здесь запрещён правилом «одна реализация пагинации».

        `after_no` и `cursor` — не дубль: первый задаёт клиент («что случилось после
        последней сводки»), второй продолжает страницу и приезжает из `meta`. Действуют
        оба сразу, побеждает больший.
        """
        size = resolve_limit(limit)
        statement = self._filtered(
            select(Entry).where(Entry.task_id == task_id),
            nos=nos,
            types=types,
        )
        boundary = after_no
        if cursor is not None:
            (cursor_no,), _ = decode_sort_cursor(cursor, arity=1)
            boundary = max(boundary, cursor_no) if boundary is not None else cursor_no
        if boundary is not None:
            statement = statement.where(Entry.no > boundary)
        statement = statement.order_by(Entry.no).limit(size + 1)
        rows = list(await self._session.scalars(statement))
        if len(rows) <= size:
            return Page(items=rows, next_cursor=None)
        page = rows[:size]
        last = page[-1]
        return Page(items=page, next_cursor=encode_sort_cursor([last.no], last.id))

    @staticmethod
    def _filtered(
        statement: Select[Any],
        *,
        nos: Sequence[int] | None,
        types: Sequence[EntryType] | None,
    ) -> Select[Any]:
        """Фильтры выборки записей. Пустой список — это «ничего», а не «всё».

        Разница существенная: `types=[]` после отбора клиентом нулевого набора типов
        обязан дать пустую страницу, а не всё дело. Поэтому проверяется `is None`.
        """
        if nos is not None:
            statement = statement.where(Entry.no.in_(list(nos)))
        if types is not None:
            statement = statement.where(Entry.type.in_(list(types)))
        return statement

    async def headings(self, task_id: uuid.UUID) -> list[EntryHeading]:
        """Опись дела: заголовки всех записей задачи, без тел и без нагрузки целиком.

        Выбираются только нужные колонки: тела записей бывают длинными, а опись
        входит в каждый пакет преемника и обязана оставаться дешёвой. Факты записи
        вырезаются из нагрузки прямо в запросе — см. `_facts_json`.
        """
        statement = (
            select(
                Entry.no,
                Entry.type,
                Entry.created_by_kind,
                Entry.created_by_signature,
                Entry.created_at,
                Entry.title,
                Entry.action_id,
                _facts_json().label("facts"),
            )
            .where(Entry.task_id == task_id)
            .order_by(Entry.no)
        )
        rows: list[Any] = list(await self._session.execute(statement))
        return [
            EntryHeading(
                no=row.no,
                type=row.type,
                author=Author(kind=row.created_by_kind, signature=row.created_by_signature),
                created_at=row.created_at,
                title=row.title,
                facts=_read_facts(row.type, row.facts),
                action_id=row.action_id,
            )
            for row in rows
        ]

    # --- Факты для проверок перехода -------------------------------------------------

    async def last_entry_into_status(self, task_id: uuid.UUID, status: TaskStatus) -> int | None:
        """Номер последней записи о переходе **в** этот статус.

        От неё считаются оба правила с нижней границей: и «сводка после последнего
        входа в `in_progress`», и «вердикты после последнего входа в `in_progress`».
        Задача, взятая повторно, старой справкой и старыми вердиктами не закрывается.
        """
        statement = select(func.max(Entry.no)).where(
            Entry.task_id == task_id,
            Entry.type == EntryType.STATUS_CHANGED,
            Entry.payload["to"].astext == status.value,
        )
        return await self._session.scalar(statement)

    async def has_entry_after(
        self,
        task_id: uuid.UUID,
        type: EntryType,
        *,
        after_no: int,
    ) -> bool:
        """Есть ли в задаче запись такого типа с номером больше указанного."""
        exists = (
            select(1)
            .where(Entry.task_id == task_id, Entry.type == type, Entry.no > after_no)
            .exists()
        )
        return bool(await self._session.scalar(select(exists)))

    async def last_verdict_outcomes(
        self,
        task_id: uuid.UUID,
        *,
        after_no: int,
    ) -> dict[int, VerdictOutcome]:
        """Исход последнего вердикта по каждой проверке — среди подшитых после `after_no`.

        Нижняя граница обязательна и не имеет значения по умолчанию: вердикт
        засчитывается только в том заходе, в котором подшит (`CONCEPT.md`, 3.3).
        Граница со значением по умолчанию однажды осталась бы непереданной, и метод
        молча вернул бы вердикты за всю жизнь задачи — ровно то поведение, от которого
        правило уходит.

        `DISTINCT ON` по номеру проверки с сортировкой по убыванию `no`: база сама
        оставляет по одной, самой свежей строке на проверку. Считать в Python значило бы
        вычитывать все вердикты задачи ради последних. Порядок — тот же `no`, что и у
        границы: внутри задачи он и есть порядок подшивки (номера выдаются под
        блокировкой строки задачи), и вторая мера времени здесь только сбивала бы.
        """
        check_no = Entry.payload["check_no"].as_integer()
        outcome = Entry.payload["outcome"].astext
        statement = (
            select(check_no.label("check_no"), outcome.label("outcome"))
            .where(
                Entry.task_id == task_id,
                Entry.type == EntryType.VERDICT,
                Entry.no > after_no,
            )
            .distinct(check_no)
            .order_by(check_no, Entry.no.desc())
        )
        rows: list[Any] = list(await self._session.execute(statement))
        return {row.check_no: VerdictOutcome(row.outcome) for row in rows}

    # --- Пакет преемника -------------------------------------------------------------

    async def last_summary(self, task_id: uuid.UUID) -> Entry | None:
        """Последняя сводка задачи. Последняя главнее предыдущих (`CONCEPT.md`, 3.4)."""
        return (await self._session.scalars(latest_summary(task_id, Entry))).first()

    async def open_questions(self, task_id: uuid.UUID) -> list[Entry]:
        """Вопросы задачи без ответа, в порядке подшивки.

        Один запрос отдаёт и список для пакета преемника, и оба счётчика признаков:
        второй запрос ради `open_questions` считал бы то же самое ещё раз.
        """
        statement = _unanswered(
            select(Entry).where(Entry.task_id == task_id, _IS_QUESTION)
        ).order_by(Entry.no)
        return list(await self._session.scalars(statement))

    async def open_remarks(self, task_id: uuid.UUID) -> list[Entry]:
        """Замечания задачи без резолюции, в порядке подшивки.

        Тот же приём, что у открытых вопросов: один запрос отдаёт и список для пакета
        преемника, и признак `open_remarks` — его значение это длина списка.
        """
        statement = _unresolved(select(Entry).where(Entry.task_id == task_id, _IS_REMARK)).order_by(
            Entry.no
        )
        return list(await self._session.scalars(statement))

    # --- Вопросы поперёк задач -------------------------------------------------------

    async def questions_page(
        self,
        *,
        addressee: str | None = None,
        queue_id: uuid.UUID | None = None,
        blocking: bool | None = None,
        open_only: bool = True,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[tuple[Entry, str]]:
        """Вопросы всех задач с фильтрами — «входящая» участника.

        Порядок — сквозной `seq` по возрастанию: дольше всех ждёт ответа самый старый
        вопрос, и он обязан быть первым. `seq` монотонен и уникален, поэтому страницы
        не теряют и не задваивают записи при подшивке новых.

        Отдаёт пары «запись, ключ задачи»: у записи связи с задачей нет, только
        `task_id`, а читающему вопрос нужен адрес, по которому идти за делом.
        """
        size = resolve_limit(limit)
        statement = select(Entry, Task.key).join(Task, Task.id == Entry.task_id).where(_IS_QUESTION)
        if addressee is not None:
            statement = statement.where(addressed_to(addressee))
        if queue_id is not None:
            statement = statement.where(Task.queue_id == queue_id)
        if blocking is not None:
            statement = statement.where(blocking_is(blocking))
        if open_only:
            statement = _unanswered(statement)
        if cursor is not None:
            (after_seq,), _ = decode_sort_cursor(cursor, arity=1)
            statement = statement.where(Entry.seq > after_seq)
        statement = statement.order_by(Entry.seq).limit(size + 1)
        rows = [(entry, key) for entry, key in await self._session.execute(statement)]
        if len(rows) <= size:
            return Page(items=rows, next_cursor=None)
        page = rows[:size]
        last_entry = page[-1][0]
        return Page(items=page, next_cursor=encode_sort_cursor([last_entry.seq], last_entry.id))

    async def remarks_page(
        self,
        *,
        author: str | None = None,
        queue_id: uuid.UUID | None = None,
        open_only: bool = True,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[tuple[Entry, str]]:
        """Замечания всех задач с фильтрами — «входящая» замечаний.

        Устроена как `questions_page` и намеренно: та же сортировка по сквозному `seq`,
        тот же курсор, те же пары «запись, ключ задачи». Разница ровно одна — отбор идёт
        по автору записи, а не по адресату в нагрузке: у замечания адресата нет
        (`CONCEPT.md`, 3.4).
        """
        size = resolve_limit(limit)
        statement = select(Entry, Task.key).join(Task, Task.id == Entry.task_id).where(_IS_REMARK)
        if author is not None:
            statement = statement.where(authored_by(author))
        if queue_id is not None:
            statement = statement.where(Task.queue_id == queue_id)
        if open_only:
            statement = _unresolved(statement)
        if cursor is not None:
            (after_seq,), _ = decode_sort_cursor(cursor, arity=1)
            statement = statement.where(Entry.seq > after_seq)
        statement = statement.order_by(Entry.seq).limit(size + 1)
        rows = [(entry, key) for entry, key in await self._session.execute(statement)]
        if len(rows) <= size:
            return Page(items=rows, next_cursor=None)
        page = rows[:size]
        last_entry = page[-1][0]
        return Page(items=page, next_cursor=encode_sort_cursor([last_entry.seq], last_entry.id))

    async def count_questions(
        self,
        *,
        addressee: str,
        blocking: bool | None = None,
        open_only: bool = True,
    ) -> int:
        """Сколько вопросов адресовано участнику — число без самих записей.

        Отдельно от `questions_page`, а не «посчитать длину страницы»: страница
        ограничена размером, и первый экран показывал бы не число вопросов, а размер
        страницы. Условия те же самые и берутся из тех же функций — иначе «входящая» и
        счётчик на первом экране однажды разошлись бы на одних и тех же данных.
        """
        statement = (
            select(func.count()).select_from(Entry).where(_IS_QUESTION, addressed_to(addressee))
        )
        if blocking is not None:
            statement = statement.where(blocking_is(blocking))
        if open_only:
            statement = _unanswered(statement)
        return await self._session.scalar(statement) or 0

    # --- Лента журнала ---------------------------------------------------------------

    async def journal_page(
        self,
        *,
        after: int,
        task_ids: Sequence[uuid.UUID] | None = None,
        queue_id: uuid.UUID | None = None,
        types: Sequence[EntryType] | None = None,
        limit: int | None = None,
    ) -> Page[tuple[Entry, str]]:
        """Хвост журнала: записи со сквозным номером больше `after`, по возрастанию.

        Отдельной таблицы событий нет — лента это та же таблица записей
        (`CONCEPT.md`, 4.1), поэтому и метод живёт здесь, а не в своём репозитории.

        Отдаёт пары «запись, ключ задачи»: у записи связи с задачей нет, только
        `task_id`, а кадром ленты нечего адресовать без ключа. Соединение с задачами
        нужно и для фильтра по очереди — у записи её нет.

        `task_ids` сужает хвост набором задач, а не одной: сессия ведёт несколько дел и
        ждёт новостей по ним одним вызовом. `None` — «все задачи»; пустой набор сюда не
        приезжает (`app/domain/journal.py`, `resolve_task_keys`).

        Ложится на уникальный индекс по `seq`: чтение всегда идёт с конца, а фильтры
        сужают уже прочитанный хвост.
        """
        size = resolve_limit(limit)
        statement = (
            select(Entry, Task.key).join(Task, Task.id == Entry.task_id).where(Entry.seq > after)
        )
        if task_ids is not None:
            statement = statement.where(Entry.task_id.in_(list(task_ids)))
        if queue_id is not None:
            statement = statement.where(Task.queue_id == queue_id)
        if types is not None:
            # Пустой список — это «ничего», а не «всё»: клиент, отобравший нулевой набор
            # типов, обязан получить пустую ленту, а не всю. Поэтому `is None`.
            statement = statement.where(Entry.type.in_(list(types)))
        statement = statement.order_by(Entry.seq).limit(size + 1)
        rows = [(entry, key) for entry, key in await self._session.execute(statement)]
        if len(rows) <= size:
            return Page(items=rows, next_cursor=None)
        page = rows[:size]
        last_entry = page[-1][0]
        return Page(items=page, next_cursor=encode_sort_cursor([last_entry.seq], last_entry.id))

    async def latest_seq(self) -> int:
        """Номер последней подшитой записи; `0` на пустой установке.

        С него начинает поток, открытый без `Last-Event-ID`: клиент просит «что будет
        дальше», а не историю установки. Ноль как «журнал пуст» безопасен — `seq`
        выдаётся с единицы.
        """
        return int(await self._session.scalar(select(func.coalesce(func.max(Entry.seq), 0))) or 0)


#: Признак записи-вопроса. Отдельной константой, потому что участвует и в выборке
#: открытых вопросов задачи, и во «входящей» участника: две копии условия разъехались бы.
_IS_QUESTION = Entry.type == EntryType.QUESTION
_IS_REMARK = Entry.type == EntryType.REMARK
_IS_RESOLUTION = Entry.type == EntryType.RESOLUTION


def addressed_to(value: str) -> ColumnElement[bool]:
    """Вопрос адресован названному участнику.

    Проверка вхождения в массив JSONB: `payload -> 'addressees' @> '["name"]'`. Ложится
    на частичный GIN-индекс по нагрузке вопросов, поэтому и «входящая», и счётчик
    первого экрана читают один индекс, а не два разных условия.
    """
    return Entry.payload["addressees"].contains([value])


def authored_by(signature: str) -> ColumnElement[bool]:
    """Запись подписана этой строкой — «мои замечания» в SQL.

    Сравнивается только подпись, без рода: имя участника и метка временного агента живут
    в одном пространстве имён и обе канонизируются в нижний регистр
    (`app/domain/authors.py`). Отбор по паре «род и подпись» пришлось бы объяснять
    клиенту, ничего не уточнив: двух авторов с одной подписью и разным родом в установке
    не бывает.
    """
    return Entry.created_by_signature == signature


def blocking_is(value: bool) -> ColumnElement[bool]:
    """Помечен ли вопрос как блокирующий — то же определение, что и в карточке.

    Питоновский двойник этого условия — `app/domain/case.py`, `is_blocking_question`:
    карточка считает признак из уже прочитанных записей, поиск — запросом. Разойдясь,
    они начнут отвечать по-разному на один вопрос, поэтому обе формы названы явно и
    сверяются тестом на одних и тех же данных.

    У записи не-вопроса ключа `blocking` в нагрузке нет, и `as_boolean()` даёт NULL:
    сравнение с ним ложно, то есть такая запись не попадёт ни в блокирующие, ни в
    неблокирующие. Условие поэтому всегда идёт вместе с `_IS_QUESTION`.
    """
    return Entry.payload["blocking"].as_boolean() == value


def open_remark_count(task_id: Any) -> Select[tuple[int]]:
    """Запрос «сколько у задачи замечаний без резолюции», годный и как подзапрос.

    Одно определение открытого замечания на весь проект: тот же `_unresolved`, что и у
    `open_remarks`, из которого карточка считает свой признак (`app/services/case.py`,
    `features`). `task_id` принимает и готовый идентификатор, и колонку внешнего запроса
    (`Task.id`) — тогда подзапрос считается для каждой строки выдачи списка.
    """
    return _unresolved(
        select(func.count()).select_from(Entry).where(Entry.task_id == task_id, _IS_REMARK)
    )


def remarks_in_work_count(task_id: Any) -> Select[tuple[int]]:
    """Сколько замечаний принято в работу, а названная задача ещё не закрыта.

    Поле отбора `remarks_in_work` (`CONCEPT.md`, 4.4) и единственное условие поиска,
    которое смотрит на **чужую** задачу: ключ продолжения лежит в нагрузке резолюции, и
    соединение идёт по нему. Признаком карточки этот счёт намеренно не стал — он
    меняется, когда закрывается другая задача, без единой записи в этом деле.

    Считаются замечания, а не резолюции: `distinct` по `remark_no` — иначе второй разбор
    того же замечания удвоил бы счёт, ничего не изменив по сути.
    """
    continuation = aliased(Task)
    return (
        select(func.count(distinct(Entry.payload["remark_no"].as_integer())))
        .select_from(Entry)
        .join(continuation, continuation.key == Entry.payload["task"].astext)
        .where(
            Entry.task_id == task_id,
            _IS_RESOLUTION,
            Entry.payload["outcome"].astext == OUTCOME_WITH_CONTINUATION.value,
            continuation.status.not_in(CLOSED_STATUSES),
        )
    )


def continuation_of() -> ColumnElement[Any]:
    """Ключ задачи-продолжения из нагрузки резолюции — то же поле, что читает домен.

    Питоновский двойник — `app/domain/case.py`, `continuation_key`: карточка и опись
    берут ключ у прочитанной записи, отбор ищет его соединением.
    """
    return Entry.payload["task"].astext


def latest_summary(task_id: Any, *entities: Any) -> Select[Any]:
    """Последняя сводка задачи одной строкой — одно определение на карточку и на список.

    Последняя главнее предыдущих (`CONCEPT.md`, 3.4), и «последняя» здесь означает
    старшую по номеру внутри задачи, а не по времени: номера выдаются под блокировкой
    строки задачи и внутри дела и есть порядок подшивки. `max(created_at)` был бы вторым
    определением того же признака и разошёлся бы с карточкой на записях одной секунды.

    `task_id` объявлен как `Any` по той же причине, что у `open_blockers_of`: принимается
    и готовый идентификатор (карточка читает саму запись), и колонка внешнего запроса
    (`Task.id`) — тогда это подзапрос по каждой строке выдачи списка.
    """
    return (
        select(*entities)
        .where(Entry.task_id == task_id, Entry.type == EntryType.SUMMARY)
        .order_by(Entry.no.desc())
        .limit(1)
    )


def last_summary_at(task_id: Any) -> Select[tuple[datetime]]:
    """Время последней сводки — признак `last_summary_at` (`CONCEPT.md`, 4.3) в SQL.

    Питоновский двойник — `app/services/case.py`, `features`: карточка берёт время у уже
    прочитанной записи, список считает его подзапросом. Обе формы построены на одном
    запросе `latest_summary`, и это единственное, что удерживает их от расхождения.
    """
    return latest_summary(task_id, Entry.created_at)


def last_entry_at(task_id: Any) -> Select[tuple[datetime]]:
    """Время последней записи агента или человека — признак `last_entry_at` в SQL.

    Служебные типы не учитываются намеренно (`CONCEPT.md`, 4.3): `link_added`
    подшивается в оба дела, когда связь ставят с другой стороны, и задача, которой
    месяц никто не касался, выглядела бы живой от чужого действия.

    Порядок по `no`, а не по `created_at`: номер в задаче монотонен, у него есть
    уникальный индекс `(task_id, no)`, и обход с конца останавливается на первой
    учтённой записи — а последняя запись в деле чаще всего именно учтённая.

    `task_id` принимает и готовый идентификатор, и колонку внешнего запроса
    (`Task.id`) — тогда это подзапрос по каждой строке выдачи списка.
    """
    return (
        select(Entry.created_at)
        .where(Entry.task_id == task_id, Entry.type.in_(AGENT_ENTRY_TYPES))
        .order_by(Entry.no.desc())
        .limit(1)
    )


def open_question_count(task_id: Any, *, blocking: bool | None = None) -> Select[tuple[int]]:
    """Запрос «сколько у задачи вопросов без ответа», годный и как подзапрос.

    Одно определение открытого вопроса на весь проект: те же `_IS_QUESTION` и
    `_unanswered`, что и у `open_questions`, из которого карточка считает свои счётчики
    (`app/services/case.py`, `features`). Поиску нужны те же значения массово, поэтому
    здесь именно запрос, а не список: `task_id` принимает и готовый идентификатор, и
    колонку внешнего запроса (`Task.id`) — тогда подзапрос считается для каждой строки
    выдачи.

    Возвращается `Select`, а не результат: скоррелировать и превратить в скалярный
    подзапрос обязан вызывающий, потому что только он знает, во что этот счёт
    сравнивается.
    """
    statement = (
        select(func.count()).select_from(Entry).where(Entry.task_id == task_id, _IS_QUESTION)
    )
    if blocking is not None:
        statement = statement.where(blocking_is(blocking))
    return _unanswered(statement)


def _unresolved(statement: Select[Any]) -> Select[Any]:
    """Оставляет замечания, по которым в той же задаче нет ни одной `resolution`.

    Дословно то же правило, что и у вопроса с ответом: первый разбор закрывает замечание
    любым исходом, остальные дополняют (`CONCEPT.md`, 3.4). Оттого и форма та же —
    `NOT EXISTS`, а не подсчёт.
    """
    resolution = aliased(Entry)
    return statement.where(
        ~select(1)
        .where(
            resolution.task_id == Entry.task_id,
            resolution.type == EntryType.RESOLUTION,
            resolution.payload["remark_no"].as_integer() == Entry.no,
        )
        .exists()
    )


def _unanswered(statement: Select[Any]) -> Select[Any]:
    """Оставляет вопросы, на которые в той же задаче нет ни одной записи `answer`.

    Ответов может быть несколько; открытым вопрос перестаёт быть после первого
    (`CONCEPT.md`, 3.4), поэтому здесь `NOT EXISTS`, а не подсчёт.
    """
    answer = aliased(Entry)
    return statement.where(
        ~select(1)
        .where(
            answer.task_id == Entry.task_id,
            answer.type == EntryType.ANSWER,
            answer.payload["question_no"].as_integer() == Entry.no,
        )
        .exists()
    )


# --- Факты записи для описи ----------------------------------------------------------


def _facts_json() -> ColumnElement[Any]:
    """Ограниченные по длине факты записи, вырезанные из нагрузки прямо в запросе.

    Вырезать надо здесь, а не после выборки: `payload` записи `section_changed` держит
    прежнее и новое значение раздела **целиком**, и выбрать его, чтобы тут же выбросить,
    значит тянуть из базы ровно то, ради отсутствия чего опись существует.

    Каждая ветвь берёт только то, что ограничено контрактом: значения перечислений,
    ключи, имена полей и участников, номера, признаки да/нет. Причина перехода сюда не
    попадает — она свободный текст, и в описи от неё остаётся лишь «была или нет».
    """
    payload = Entry.payload
    return case(
        (
            Entry.type == EntryType.STATUS_CHANGED,
            func.jsonb_build_object(
                "from_status",
                payload["from"],
                "to_status",
                payload["to"],
                "has_reason",
                payload["reason"].astext.is_not(None),
            ),
        ),
        (
            # `check_no` есть только у точечной правки проверки; у правки списка целиком
            # его в нагрузке нет, и в фактах он окажется пустым. Различать их надо именно
            # здесь: «переписали третью проверку» и «переписали весь список» задевают
            # разные вердикты (`app/domain/case.py`, `mark_outdated_verdicts`).
            Entry.type == EntryType.SECTION_CHANGED,
            func.jsonb_build_object("field", payload["field"], "check_no", payload["check_no"]),
        ),
        # Правка обвязки — только имя поля: проверки в обвязку не входят, и точечной
        # правки у неё не бывает.
        (
            Entry.type == EntryType.FIELD_CHANGED,
            func.jsonb_build_object("field", payload["field"]),
        ),
        (
            Entry.type == EntryType.ASSIGNEE_CHANGED,
            func.jsonb_build_object(
                "assignee_from", payload["before"], "assignee_to", payload["after"]
            ),
        ),
        (
            Entry.type.in_((EntryType.LINK_ADDED, EntryType.LINK_REMOVED)),
            func.jsonb_build_object("link_kind", payload["kind"], "other_key", payload["other"]),
        ),
        (
            Entry.type == EntryType.QUESTION,
            func.jsonb_build_object(
                "addressees", payload["addressees"], "blocking", payload["blocking"]
            ),
        ),
        (
            Entry.type == EntryType.ANSWER,
            func.jsonb_build_object("question_no", payload["question_no"]),
        ),
        (
            Entry.type == EntryType.VERDICT,
            func.jsonb_build_object("check_no", payload["check_no"], "outcome", payload["outcome"]),
        ),
        # Исход резолюции уезжает под тем же именем, что и исход вердикта: перечисления
        # у них разные, но разметка по `type` развела их по разным формам фактов, и одно
        # имя больше не может слиться с чужим набором значений.
        (
            Entry.type == EntryType.RESOLUTION,
            func.jsonb_build_object(
                "remark_no",
                payload["remark_no"],
                "outcome",
                payload["outcome"],
                "continuation_key",
                payload["task"],
            ),
        ),
        # Записи агента и человека: их заголовок пишет автор, и называть строку нечем,
        # кроме него самого.
        else_=text("'{}'::jsonb"),
    )


def _read_facts(entry_type: EntryType, raw: Any) -> EntryFacts:
    """Разбирает вырезанное в форму фактов этого типа записи.

    Форму выбирает тип, а не содержимое: чужого ключа в `raw` быть не может — набор
    задан выражением выше, а не тем, что кто-то положил в нагрузку. Тип, у которого
    ветви в выражении нет, попадает в `NoFacts`, и это не молчаливое «ничего не нашли»,
    а объявленная форма: тот же ответ даёт словарь `FACTS_BY_ENTRY_TYPE`, сплошность
    которого по `EntryType` стережёт тест.
    """
    values: Mapping[str, Any] = raw if isinstance(raw, dict) else {}
    match entry_type:
        case EntryType.STATUS_CHANGED:
            return StatusChangedFacts(
                from_status=_as_enum(TaskStatus, values.get("from_status")),
                to_status=_as_enum(TaskStatus, values.get("to_status")),
                has_reason=values.get("has_reason"),
            )
        case EntryType.SECTION_CHANGED:
            return SectionChangedFacts(
                field=_as_enum(TaskField, values.get("field")),
                check_no=values.get("check_no"),
            )
        case EntryType.FIELD_CHANGED:
            return FieldChangedFacts(field=_as_enum(TaskField, values.get("field")))
        case EntryType.ASSIGNEE_CHANGED:
            return AssigneeChangedFacts(
                assignee_from=values.get("assignee_from"),
                assignee_to=values.get("assignee_to"),
            )
        case EntryType.LINK_ADDED | EntryType.LINK_REMOVED:
            return LinkFacts(
                type=entry_type,
                link_kind=_as_enum(LinkKind, values.get("link_kind")),
                other_key=values.get("other_key"),
            )
        case EntryType.QUESTION:
            addressees = values.get("addressees")
            return QuestionFacts(
                addressees=None if addressees is None else tuple(str(n) for n in addressees),
                blocking=values.get("blocking"),
            )
        case EntryType.ANSWER:
            return AnswerFacts(question_no=values.get("question_no"))
        case EntryType.VERDICT:
            return VerdictFacts(
                check_no=values.get("check_no"),
                outcome=_as_enum(VerdictOutcome, values.get("outcome")),
            )
        case EntryType.RESOLUTION:
            return ResolutionFacts(
                remark_no=values.get("remark_no"),
                outcome=_as_enum(RemarkOutcome, values.get("outcome")),
                continuation_key=values.get("continuation_key"),
            )
        case _:
            return NoFacts(type=entry_type)


def _as_enum(enum: Any, value: Any) -> Any:
    """Значение перечисления или `None`. Незнакомое значение — не повод падать при
    чтении: запись уже подшита, а перечисление могло смениться миграцией данных."""
    if value is None:
        return None
    try:
        return enum(value)
    except ValueError:
        return None
