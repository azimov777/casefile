"""Данные, которые инструмент отдаёт агенту.

Инструмент возвращает обычный словарь, а SDK сворачивает его в результат вызова тем же
сериализатором pydantic, каким FastAPI сворачивает ответ REST. Отсюда важное следствие,
на котором стоит проверка 3 задачи: `datetime` не приводится к строке **здесь**, иначе
формат разошёлся бы с REST (`2026-09-04T10:00:00Z` против `...+00:00`), и «поле в поле»
перестало бы выполняться. Перечисления, наоборот, разворачиваются в значение явно: у
`StrEnum` сериализация случайно совпадает со значением, и полагаться на совпадение
нельзя.

## Почему это не переиспользование схем REST

`mcp` не имеет права зависеть от `api` (`docs/CONVENTIONS.md`): расхождение интерфейсов
проект ловит тем, что оба зовут одни сценарии, а не тем, что делят схемы ответов. Поэтому
имена и смысл полей здесь повторяют `app/api/schemas/`, а удерживает их вместе тест
`tests/test_mcp_tools.py`, сравнивающий пакет преемника из MCP с ответом REST.

## Что совпадает с REST, а что нарочно короче

Пакет преемника (`task_package`) совпадает **целиком**: это вход агента в задачу, и
терять в нём поля нельзя. Справочные представления — очередь и участник — короче: агенту
нужен контекст, а не строка реестра, и `id`, времена правки и подпись заводившего съели
бы контекст, ничего не добавив к решению.

## Почему ответ изменяющего инструмента короче пакета преемника

`transition` и `update_task` отвечают `mutation` — четырьмя полями вместо карточки. Это
продолжение того же правила, и разница здесь не в объёме, а в том, **кто уже знает
содержимое**.

Агент приходит к изменению из `get_task`: описание, пять разделов и список проверок он
прочитал и держит в контексте. Вернуть их снова значит взять с него плату второй раз за
то же самое, и цена растёт с числом переходов: у задачи, идущей `backlog → open →
in_progress → done`, карточка приезжала четыре раза. Замер на живой сессии показал
задачу, чьи разделы приехали восемь раз.

Поэтому в коротком ответе остаётся ровно то, чего агент **не мог знать заранее**: новая
версия (без неё следующий `update_task` упрётся в `version_conflict`), новый статус (его
выбрал не только вызывающий, но и таблица переходов) и номера подшитых записей (их
выдаёт база). Ключ повторяется, потому что ответ должен читаться сам по себе. Всё
остальное агент прислал сам либо уже видел.

Второго, полного режима у этих инструментов нет намеренно: параметр вроде `fields` дал бы
два поведения, из которых проверяется одно. Кому нужна карточка целиком — зовёт
`get_task`, и это сказано в описании каждого инструмента, чтобы агент не звал его на
всякий случай после каждого действия.

REST этого правила не знает и знать не должен: там потребитель другой — интерфейс,
который перерисовывает карточку после каждого действия и ходит за ней в ту же секунду.

## Обрезка длинного текста

Единственное место обрезки — выдача `search_tasks` (`TRACKER_MCP_TEXT_LIMIT`): только там
в одном ответе может оказаться два десятка описаний и разделов. Обрезка объявлена рядом
со значением (`<поле>_truncated`, `<поле>_length`), а полный текст — один вызов
`get_task`. Тела записей дела не обрезаются нигде: их запрашивают по номеру, и взять
полный текст было бы больше неоткуда.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from app.db.models.entry import Entry
from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.domain.authors import Author
from app.domain.case import EntryFacts, EntryHeading
from app.domain.search import FEATURES_FIELD, MANDATORY_FIELD
from app.domain.tasks import TaskFeatures
from app.services.links import TaskLink
from app.services.search import FoundTask
from app.services.tasks import TaskMutation, TaskPackage

#: Поля задачи, которые бывают длинными: описание и пять разделов. Обрезаются только они
#: и только в выдаче поиска.
LONG_TEXT_FIELDS: frozenset[str] = frozenset(
    {"description", "goal", "context", "constraints", "output"}
)


def author(value: Author) -> dict[str, Any]:
    """Кто сделал действие: род и подпись. У самого трекера подписи нет."""
    return {"kind": value.kind.value, "signature": value.signature}


def queue_ref(queue: Queue) -> dict[str, Any]:
    """Очередь одной строкой: ключ и название. Описание запрашивают `get_queue`.

    Одно представление на карточку задачи и на выдачу `list_queues`: очередь, названная
    коротко, обязана выглядеть одинаково везде, где она не главный предмет ответа.
    """
    return {"key": queue.key, "title": queue.title}


def task(item: Task) -> dict[str, Any]:
    """Карточка задачи — тот же набор полей, что у `TaskRead` в REST."""
    return {
        "id": str(item.id),
        "key": item.key,
        "queue": queue_ref(item.queue),
        "title": item.title,
        "description": item.description,
        "goal": item.goal,
        "context": item.context,
        "constraints": item.constraints,
        "output": item.output,
        "checks": list(item.checks),
        "status": item.status.value,
        "assignee": item.assignee,
        "priority": item.priority.value,
        "version": item.version,
        "created_by": author(item.created_by),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def mutation(value: TaskMutation) -> dict[str, Any]:
    """Ответ изменяющего инструмента: что стало и чем это подшито, без карточки.

    Почему не карточка — в шапке модуля. Здесь важно, что `entries` бывает пустым, и
    это законный ответ: клиент прислал то, что уже стоит, — версия не выросла, дело не
    пополнилось. Отличать «применилось» от «уже так было» агент будет именно по нему,
    поэтому отдельного поля `changed` рядом нет: два способа узнать один факт разошлись
    бы при первой же правке.
    """
    return {
        "key": value.task.key,
        "status": value.task.status.value,
        "version": value.task.version,
        "entries": list(value.entries),
    }


def found_task(found: FoundTask, *, fields: Sequence[str], text_limit: int) -> dict[str, Any]:
    """Строка выдачи поиска: только запрошенные поля, длинные тексты с потолком.

    Пустой набор полей означает «вся задача» — то же правило, что в REST. Ключ остаётся
    всегда: выдача без него бесполезна, по ней нельзя ни прочитать задачу, ни сослаться
    на неё.

    Признаки идут вложенным объектом, тем же, что в пакете преемника: агент, выбирающий
    задачу из списка, видит `blocked` и открытые вопросы сразу, а не вызывает `get_task`
    на каждую строку. Их нет в ответе, если их не просили (`fields` без `features`).
    """
    payload = task(found.task)
    if found.features is not None:
        payload[FEATURES_FIELD] = features(found.features)
    if fields:
        selected = {*fields, MANDATORY_FIELD}
        payload = {name: value for name, value in payload.items() if name in selected}
    for name in LONG_TEXT_FIELDS & payload.keys():
        _clip_into(payload, name, text_limit)
    return payload


def features(value: TaskFeatures) -> dict[str, Any]:
    """Вычисляемые признаки задачи (`CONCEPT.md`, 4.3)."""
    return {
        "blocked": value.blocked,
        "open_questions": value.open_questions,
        "open_blocking_questions": value.open_blocking_questions,
        "open_remarks": value.open_remarks,
        "last_summary_at": value.last_summary_at,
        "last_entry_at": value.last_entry_at,
    }


def link(value: TaskLink) -> dict[str, Any]:
    """Связь со стороны своей задачи: вид назван ролью **этой** задачи.

    В `other` лежит задача на **другом** конце — сторону вычислил сценарий, и определять
    её здесь во второй раз не нужно и неверно: канонизация могла записать связь в
    обратном порядке (`docs/notes/mcp.md`).
    """
    return {
        "kind": value.kind.value,
        "other": {
            "key": value.other.key,
            "title": value.other.title,
            "status": value.other.status.value,
        },
        "author": author(value.author),
        "created_at": value.created_at,
    }


def facts(value: EntryFacts) -> dict[str, Any]:
    """Факты записи для описи: те же поля и в том же порядке, что в схеме REST.

    Пакет преемника обязан совпадать с ответом REST поле в поле (обзорная проверка
    задачи 03, `tests/test_mcp_tools.py`), поэтому «отдать факты только интерфейсу»
    нельзя: расхождение здесь означало бы два разных описания одного дела. Пустые части
    едут вместе с остальными — по той же причине.
    """
    return {
        "from_status": None if value.from_status is None else value.from_status.value,
        "to_status": None if value.to_status is None else value.to_status.value,
        "has_reason": value.has_reason,
        "field": None if value.field is None else value.field.value,
        "link_kind": None if value.link_kind is None else value.link_kind.value,
        "other_key": value.other_key,
        "assignee_from": value.assignee_from,
        "assignee_to": value.assignee_to,
        "addressees": None if value.addressees is None else list(value.addressees),
        "blocking": value.blocking,
        "question_no": value.question_no,
        "check_no": value.check_no,
        "outcome": None if value.outcome is None else value.outcome.value,
        "remark_no": value.remark_no,
        "remark_outcome": None if value.remark_outcome is None else value.remark_outcome.value,
        "continuation_key": value.continuation_key,
    }


def heading(value: EntryHeading) -> dict[str, Any]:
    """Строка описи дела: то, что видно о записи, не читая её тела."""
    return {
        "no": value.no,
        "type": value.type.value,
        "author": author(value.author),
        "created_at": value.created_at,
        "title": value.title,
        "facts": facts(value.facts),
    }


def entry(value: Entry, *, task_key: str) -> dict[str, Any]:
    """Запись дела целиком. Ключ задачи приходит извне: у записи только `task_id`."""
    return {
        "id": str(value.id),
        "seq": value.seq,
        "no": value.no,
        "task_key": task_key,
        "type": value.type.value,
        "author": author(value.author),
        "title": value.title,
        "body": value.body,
        "payload": dict(value.payload),
        "refs": list(value.refs),
        "created_at": value.created_at,
    }


def task_package(package: TaskPackage) -> dict[str, Any]:
    """Пакет преемника: всё, что нужно агенту с чистым контекстом, одним вызовом.

    Совпадает с `GET /api/v1/tasks/{key}` поле в поле, и это проверяется тестом. Не
    ради красоты: агент и человек обязаны видеть одну и ту же задачу, иначе разбор
    «почему агент решил иначе, чем показывал интерфейс» упирается в два разных ответа.
    """
    key = package.task.key
    return {
        "task": task(package.task),
        "links": [link(item) for item in package.links],
        "features": features(package.features),
        "summary": None if package.summary is None else entry(package.summary, task_key=key),
        "questions": [entry(question, task_key=key) for question in package.questions],
        "remarks": [entry(remark, task_key=key) for remark in package.remarks],
        "transitions": [status.value for status in package.transitions],
        "index": [heading(item) for item in package.index],
    }


def queue(item: Queue) -> dict[str, Any]:
    """Очередь с описанием — общим контекстом всех её задач.

    Короче ответа REST: `id`, счётчик номеров и времена правки интерфейсу нужны, а
    агенту — нет, и каждое лишнее поле здесь оплачено его контекстом.
    """
    return {"key": item.key, "title": item.title, "description": item.description}


def participant(item: Participant) -> dict[str, Any]:
    """Участник реестра: кому можно адресовать вопрос и что о нём известно."""
    return {"kind": item.kind.value, "name": item.name, "description": item.description}


def page(items: Iterable[dict[str, Any]], *, next_cursor: str | None) -> dict[str, Any]:
    """Страница выдачи. Форма одна у всех инструментов, которые её отдают.

    `next_cursor` пуст — дальше ничего нет. Отдельного признака «есть ещё» здесь нет
    намеренно: два поля об одном и том же однажды разойдутся, а у REST он существует
    ради интерфейса, который рисует кнопку.
    """
    return {"items": list(items), "next_cursor": next_cursor}


def _clip_into(payload: dict[str, Any], name: str, limit: int) -> None:
    """Обрезает поле и объявляет обрезку рядом с ним.

    Признак отдельным полем, а не многоточием в тексте: агент, сравнивающий строки, не
    должен принимать метку за часть значения. Полная длина сообщается тем же ответом —
    по ней видно, сколько осталось за краем.
    """
    text = payload[name]
    if not isinstance(text, str) or len(text) <= limit:
        return
    payload[name] = text[:limit]
    payload[f"{name}_truncated"] = True
    payload[f"{name}_length"] = len(text)
