"""Замечание человека и его разбор: обзорные проверки задачи TRK-9.

Механика здесь одна, а проверяется она с трёх сторон, потому что обещания разные:

- **пакет одним вызовом.** Замечание бесполезно, если его надо искать: агент с чистым
  контекстом читает `get_task` и обязан увидеть «вышло не то» там же, где открытые
  вопросы, — без `read_entries` и без разбора описи;
- **структура вместо текста.** «Рассмотрено» и «выполнено» — разные вещи, и различать их
  по словам в теле значит не различать вовсе: исход это значение, ключ продолжения —
  ссылка, а «разобрано, но работа не закрыта» — запрос;
- **трекер ничего не делает сам.** Подшитое замечание не двигает статус, не блокирует
  работу и не гасится сводкой: оно правит курс, а не дёргает стоп-кран.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project
from app.db.models.task import Task
from app.domain.authors import label_author
from app.domain.case import EntryType, RemarkOutcome
from app.domain.errors import EntryFieldsInvalidError, SearchFieldUnknownError
from app.domain.tasks import TaskStatus
from app.domain.tokens import TokenScope
from app.services import case as case_service
from app.services import search as search_service
from app.services import tasks as tasks_service
from app.services.auth import Actor
from conftest import Connect, call, refuse

READY = {
    "project": "trk",
    "title": "Починить выдачу ключей",
    "description": "Ключ сгорает на неудачном запросе",
    "goal": "Ключи не сгорают",
    "context": "Номер выдаёт проект",
    "constraints": "Счётчик не переписывать",
    "output": "Тест на несгоревший номер",
    "checks": ["Создание задачи без названия не тратит номер"],
    # В работу задачу берёт исполнитель (`CONCEPT.md`, 3.3): запросы идут от `owner`.
    "assignee": "owner",
}

SUMMARY = {
    "done": "разобрался",
    "remaining": "дописать",
    "blockers": "нет",
    "next_step": "дописать тест",
}

#: Закрывающая сводка: та же четвёрка и пятая часть, обязательная только при закрытии.
CLOSING_SUMMARY = {
    **SUMMARY,
    "unmeasured": "Живая проверка на проде не гонялась, риск считаю теоретическим",
}


# --- Помощники ------------------------------------------------------------------------


async def make(session: AsyncSession, actor: Actor, project: Project, title: str) -> Task:
    return await tasks_service.create_task(
        session,
        actor=actor,
        project=project,
        title=title,
        description="описание",
        goal="цель",
        context="контекст",
        constraints="ограничения",
        output="выход",
        checks=["проверка"],
        # В работу задачу берёт исполнитель (`CONCEPT.md`, 3.3): им назначен автор.
        assignee=actor.author.signature,
    )


async def remark(session: AsyncSession, actor: Actor, task: Task, title: str) -> Any:
    return await case_service.add_entry(
        session, task, actor=actor, type=EntryType.REMARK, title=title, body="подробности"
    )


async def create(client: AsyncClient, title: str) -> str:
    response = await client.post("/api/v1/tasks", json={**READY, "title": title})
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["key"])


async def file_entry(client: AsyncClient, key: str, **body: Any) -> Any:
    return await client.post(f"/api/v1/tasks/{key}/entries", json=body)


async def close(client: AsyncClient, key: str) -> None:
    """Проводит задачу до `done`: в работу, потом закрытием со сводкой и вердиктами."""
    for to in ("open", "in_progress"):
        moved = await client.post(f"/api/v1/tasks/{key}/transition", json={"to": to})
        assert moved.status_code == 200, moved.text
    done = await client.post(
        f"/api/v1/tasks/{key}/close",
        json={
            "summary": CLOSING_SUMMARY,
            "verdicts": [
                {"check_no": check_no, "outcome": "passed"}
                for check_no in range(1, len(READY["checks"]) + 1)
            ],
        },
    )
    assert done.status_code == 200, done.text


async def card(client: AsyncClient, key: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/tasks/{key}")
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


# --- Главная проверка: пакет одним вызовом --------------------------------------------


async def test_the_package_carries_every_open_remark_in_full(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 1 в REST: замечание из-под сводки и десятка записей видно сразу.

    Замечание подшивается **до** сводки и заваливается сверху: если бы пакет отдавал
    только опись, читателю пришлось бы разбирать заголовки и лезть в `read_entries` — то
    есть делать ровно то, ради отсутствия чего механика и заведена.
    """
    key = await create(auth_client, "замечание под завалом")
    filed = await file_entry(
        auth_client, key, type="remark", title="Вышло не то: список не читается", body="Подробно"
    )
    assert filed.status_code == 201, filed.text
    remark_no = filed.json()["data"]["no"]

    await file_entry(auth_client, key, type="summary", payload=SUMMARY)
    for index in range(10):
        await file_entry(auth_client, key, type="note", title=f"шум {index}")

    package = await card(auth_client, key)

    assert [item["no"] for item in package["remarks"]] == [remark_no]
    only = package["remarks"][0]
    assert only["type"] == "remark"
    assert only["title"] == "Вышло не то: список не читается"
    assert only["body"] == "Подробно"
    assert only["author"] == {"kind": "human", "signature": "owner"}
    assert only["created_at"]
    assert package["features"]["open_remarks"] == 1


async def test_the_package_carries_every_open_remark_in_mcp_too(
    mcp_session: Connect,
    task_secret: str,
    task: Task,
) -> None:
    """Обзорная проверка 1 в MCP: тот же пакет, те же поля — второго контракта нет."""
    # Ключ снимается до сессии: инструмент коммитит, объект задачи после этого просрочен,
    # и обращение к его полю ушло бы в базу мимо сессии теста.
    key = task.key
    async with mcp_session(task_secret) as session:
        filed = await call(
            session, "add_entry", key=key, type="remark", title="Вышло не то", body="Подробно"
        )
        await call(
            session,
            "add_summary",
            key=key,
            done="сделано",
            remaining="осталось",
            blockers="нет",
            next_step="дальше",
        )
        package = await call(session, "get_task", key=key)

    assert [item["no"] for item in package["remarks"]] == [filed["no"]]
    assert package["remarks"][0]["body"] == "Подробно"
    assert package["features"]["open_remarks"] == 1


# --- Вторая главная: рассмотрено против выполнено --------------------------------------


async def test_a_resolution_closes_the_remark_and_names_where_the_work_went(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 2: исход читается значением, а ключ продолжения — ссылкой.

    Разобранное замечание уходит из пакета, но не из дела: и исход, и адрес работы
    читаются из записи и из строки описи, не разбирая текст.
    """
    key = await create(auth_client, "разобранное замечание")
    continuation = await create(auth_client, "продолжение")
    filed = await file_entry(auth_client, key, type="remark", title="Вышло не то")
    remark_no = filed.json()["data"]["no"]

    resolved = await file_entry(
        auth_client,
        key,
        type="resolution",
        payload={"remark_no": remark_no, "outcome": "accepted", "task": continuation},
        body="Принято, работа ушла в отдельную задачу",
    )

    assert resolved.status_code == 201, resolved.text
    data = resolved.json()["data"]
    assert data["payload"] == {
        "remark_no": remark_no,
        "outcome": "accepted",
        "task": continuation,
    }
    assert data["title"] == f"Resolution of {key}#{remark_no}: accepted"

    package = await card(auth_client, key)
    assert package["remarks"] == []
    assert package["features"]["open_remarks"] == 0
    heading = next(item for item in package["index"] if item["type"] == "resolution")
    assert heading["facts"]["remark_no"] == remark_no
    assert heading["facts"]["outcome"] == "accepted"
    assert heading["facts"]["continuation_key"] == continuation


async def test_reviewed_but_unfinished_is_a_query_not_a_reading(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 2, вторая половина: «разобрано, но работа не закрыта» — отбор.

    Признак задачи считать это не может честно: он меняется, когда закрывается **другая**
    задача, без единой записи в этом деле. Поэтому это поле отбора, и проверяется оно
    так, как им будут пользоваться, — запросом до и после закрытия продолжения.
    """
    key = await create(auth_client, "приняли в работу")
    continuation = await create(auth_client, "продолжение")
    filed = await file_entry(auth_client, key, type="remark", title="Вышло не то")
    await file_entry(
        auth_client,
        key,
        type="resolution",
        payload={
            "remark_no": filed.json()["data"]["no"],
            "outcome": "accepted",
            "task": continuation,
        },
    )

    async def found(query: str) -> list[str]:
        response = await auth_client.get("/api/v1/tasks", params={"query": query})
        assert response.status_code == 200, response.text
        return [item["key"] for item in response.json()["data"]]

    assert await found("remarks_in_work: > 0") == [key]
    assert await found("open_remarks: > 0") == []

    await close(auth_client, continuation)

    assert await found("remarks_in_work: > 0") == []


async def test_the_outcomes_are_told_apart_by_value(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """«Поправил сразу» и «принял в работу» — разные значения, а не разные слова.

    Заодно правило пары: ключ продолжения принимается только с `accepted` и там
    обязателен. Иначе «приняли» без адреса было бы обещанием без ссылки, а «поправлено»
    с адресом — вторым способом сказать то же самое.
    """
    key = await create(auth_client, "четыре исхода")
    continuation = await create(auth_client, "продолжение")
    filed = [
        (await file_entry(auth_client, key, type="remark", title=f"замечание {index}")).json()[
            "data"
        ]["no"]
        for index in range(4)
    ]

    outcomes = [
        ({"outcome": "fixed"}, 201),
        ({"outcome": "needs_detail"}, 201),
        ({"outcome": "declined"}, 201),
        ({"outcome": "accepted", "task": continuation}, 201),
    ]
    for remark_no, (payload, expected) in zip(filed, outcomes, strict=True):
        response = await file_entry(
            auth_client, key, type="resolution", payload={"remark_no": remark_no, **payload}
        )
        assert response.status_code == expected, response.text
        assert response.json()["data"]["payload"]["outcome"] == payload["outcome"]

    without_task = await file_entry(
        auth_client,
        key,
        type="resolution",
        payload={"remark_no": filed[0], "outcome": "accepted"},
    )
    with_extra_task = await file_entry(
        auth_client,
        key,
        type="resolution",
        payload={"remark_no": filed[0], "outcome": "fixed", "task": continuation},
    )

    assert without_task.status_code == 422
    assert with_extra_task.status_code == 422
    reasons = {
        field["field"]: field["reason"]
        for field in without_task.json()["error"]["details"]["fields"]
    }
    assert reasons == {"task": "required"}


# --- Несколько замечаний ---------------------------------------------------------------


async def test_each_remark_has_its_own_fate(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Обзорная проверка 3: частичный разбор не закрывает остальные замечания."""
    task = await make(db_session, task_actor, project, "три замечания разом")
    first = await remark(db_session, task_actor, task, "первое")
    second = await remark(db_session, task_actor, task, "второе")
    third = await remark(db_session, task_actor, task, "третье")

    await case_service.resolve(
        db_session, task, actor=task_actor, remark_no=second.no, outcome=RemarkOutcome.FIXED
    )

    open_remarks = await case_service.open_remarks(db_session, task, actor=task_actor)
    assert [item.no for item in open_remarks] == [first.no, third.no]


async def test_a_resolution_points_at_a_remark_of_this_task(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Разбор сводки или чужого номера отклоняется: иначе признак не сошёлся бы с делом."""
    task = await make(db_session, task_actor, project, "проверка адресации")
    summary = await case_service.add_summary(
        db_session,
        task,
        actor=task_actor,
        done="сделано",
        remaining="осталось",
        blockers="нет",
        next_step="дальше",
    )

    with pytest.raises(EntryFieldsInvalidError) as wrong_type:
        await case_service.resolve(
            db_session, task, actor=task_actor, remark_no=summary.no, outcome=RemarkOutcome.FIXED
        )
    with pytest.raises(EntryFieldsInvalidError) as missing:
        await case_service.resolve(
            db_session, task, actor=task_actor, remark_no=999, outcome=RemarkOutcome.FIXED
        )

    assert wrong_type.value.details["fields"][0]["reason"] == "not_a_remark"
    assert missing.value.details["fields"][0]["reason"] == "unknown_entry"


async def test_a_continuation_task_must_exist(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Ключ продолжения проверяется на существование: ссылка в никуда хуже её отсутствия."""
    task = await make(db_session, task_actor, project, "несуществующее продолжение")
    filed = await remark(db_session, task_actor, task, "вышло не то")

    with pytest.raises(EntryFieldsInvalidError) as error:
        await case_service.resolve(
            db_session,
            task,
            actor=task_actor,
            remark_no=filed.no,
            outcome=RemarkOutcome.ACCEPTED,
            continuation="TRK-404",
        )

    assert error.value.details["fields"][0] == {
        "field": "task",
        "reason": "unknown_task",
        "key": "TRK-404",
    }


# --- Трекер ничего не делает сам -------------------------------------------------------


async def test_a_remark_reaches_a_closed_task_and_leaves_its_card_alone(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорные проверки 4 и 5: закрытую задачу замечание пополняет, но не оживляет.

    Сравнивается весь пакет, кроме дела, связей и признака: статус, разделы, версия,
    вердикты и допустимые переходы обязаны совпасть до знака. Иначе «человек правит
    курс» означало бы «человек переоткрывает закрытое».
    """
    key = await create(auth_client, "закрытая, но не устраивает")
    await close(auth_client, key)
    before = await card(auth_client, key)

    filed = await file_entry(auth_client, key, type="remark", title="Вышло не то")

    assert filed.status_code == 201, filed.text
    after = await card(auth_client, key)
    changed = {"remarks", "features", "index"}
    assert {name: value for name, value in after.items() if name not in changed} == {
        name: value for name, value in before.items() if name not in changed
    }
    assert [item["title"] for item in after["remarks"]] == ["Вышло не то"]
    assert after["features"]["open_remarks"] == 1
    assert after["features"] | {"open_remarks": 0} == before["features"]
    assert [item["type"] for item in after["index"][len(before["index"]) :]] == ["remark"]


async def test_an_open_remark_does_not_hold_the_work(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорные проверки 6 и 7: замечание не блокер, а сводка — не разбор."""
    key = await create(auth_client, "замечание не стоп-кран")
    await file_entry(auth_client, key, type="remark", title="Вышло не то")

    opened = await auth_client.post(f"/api/v1/tasks/{key}/transition", json={"to": "open"})
    taken = await auth_client.post(f"/api/v1/tasks/{key}/transition", json={"to": "in_progress"})
    await file_entry(auth_client, key, type="summary", payload=SUMMARY)

    assert opened.status_code == 200, opened.text
    assert taken.status_code == 200, taken.text
    package = await card(auth_client, key)
    assert package["task"]["status"] == "in_progress"
    assert package["features"]["open_remarks"] == 1
    assert len(package["remarks"]) == 1


# --- Отбор -----------------------------------------------------------------------------


async def test_remarks_are_searchable_in_every_status(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Обзорная проверка 8: отбор работает и на закрытой задаче.

    Замечание к `done` — главный случай механики: именно на закрытое человек и смотрит,
    когда говорит «вышло не то». Отбор, теряющий такие задачи, обесценивает признак.
    """
    cancelled = await make(db_session, task_actor, project, "отменённая, замечание внутри")
    await tasks_service.transition_task(
        db_session, cancelled, actor=task_actor, to=TaskStatus.CANCELLED, reason="не нужна"
    )
    await remark(db_session, task_actor, cancelled, "вышло не то")
    quiet = await make(db_session, task_actor, project, "без замечаний")

    found = await search_service.search_tasks(
        db_session, actor=task_actor, query="open_remarks: > 0"
    )

    assert [item.task.key for item in found.page.items] == [cancelled.key]
    assert quiet.key not in [item.task.key for item in found.page.items]


async def test_an_unknown_field_names_the_new_ones_among_the_allowed(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Обзорная проверка 8, вторая половина: новые поля перечислены в отказе."""
    del project

    with pytest.raises(SearchFieldUnknownError) as error:
        await search_service.search_tasks(db_session, actor=task_actor, query="remarks: > 0")

    allowed = error.value.details["allowed"]
    assert "open_remarks" in allowed
    assert "remarks_in_work" in allowed


async def test_the_feature_of_a_row_matches_the_card(
    db_session: AsyncSession,
    task_actor: Actor,
    project: Project,
) -> None:
    """Счётчик в строке списка и в карточке — одно определение, а не два похожих.

    Проверяется на данных, где они могли бы разойтись: одно замечание разобрано, другое
    нет, а между ними лежат чужие записи.
    """
    task = await make(db_session, task_actor, project, "признак строки против карточки")
    resolved = await remark(db_session, task_actor, task, "первое")
    await remark(db_session, task_actor, task, "второе")
    await case_service.resolve(
        db_session, task, actor=task_actor, remark_no=resolved.no, outcome=RemarkOutcome.DECLINED
    )

    package = await tasks_service.read_task_package(db_session, task.key, actor=task_actor)
    found = await search_service.search_tasks(
        db_session, actor=task_actor, query=f'text: "{task.title}"'
    )

    row = found.page.items[0].features
    assert row is not None
    assert package.features.open_remarks == 1
    assert row.open_remarks == package.features.open_remarks


# --- Поперёк задач ---------------------------------------------------------------------


async def inbox(client: AsyncClient, **params: Any) -> list[tuple[str, int, str]]:
    """«Входящая» замечаний: ключ задачи, номер записи и заголовок каждой строки."""
    response = await client.get("/api/v1/remarks", params=params)
    assert response.status_code == 200, response.text
    return [(item["task_key"], item["no"], item["title"]) for item in response.json()["data"]]


async def test_the_inbox_returns_open_remarks_across_tasks_in_full(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 1 задачи TRK-11: один запрос — и текст, и адрес каждого замечания.

    Собрать это из списка задач нельзя: `open_remarks: > 0` отдаёт задачи, а не записи, и
    за текстом пришлось бы идти в каждую задачу отдельно.
    """
    first = await create(auth_client, "первая задача")
    second = await create(auth_client, "вторая задача")
    await file_entry(auth_client, first, type="remark", title="Раз", body="тело раз")
    await file_entry(auth_client, second, type="remark", title="Два", body="тело два")

    response = await auth_client.get("/api/v1/remarks")

    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert [(row["task_key"], row["title"]) for row in rows] == [(first, "Раз"), (second, "Два")]
    assert rows[0]["body"] == "тело раз"
    assert rows[0]["author"] == {"kind": "human", "signature": "owner"}
    assert rows[0]["no"] and rows[0]["created_at"]
    assert response.json()["meta"]["has_more"] is False


async def test_a_resolved_remark_leaves_the_inbox_but_not_the_case(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 2: выдача идёт от самого старого, разбор убирает строку.

    Из дела замечание при этом никуда не девается: `open=false` снимает фильтр и отдаёт
    все замечания — и разобранные, и нет, — как тот же параметр у вопросов.
    """
    key = await create(auth_client, "две претензии")
    first = await file_entry(auth_client, key, type="remark", title="Старое")
    await file_entry(auth_client, key, type="remark", title="Новое")
    assert [title for _, _, title in await inbox(auth_client)] == ["Старое", "Новое"]

    await file_entry(
        auth_client,
        key,
        type="resolution",
        payload={"remark_no": first.json()["data"]["no"], "outcome": "fixed"},
    )

    assert [title for _, _, title in await inbox(auth_client)] == ["Новое"]
    assert [title for _, _, title in await inbox(auth_client, open=False)] == ["Старое", "Новое"]


async def test_the_inbox_pages_by_seq_without_losing_or_repeating(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 3: подшивка во время листания не ломает страницы.

    Курсор идёт по сквозному `seq`: новая запись получает номер больше всех выданных и
    попадает в хвост, а не вклинивается в уже прочитанное. Проверяется именно так —
    страница, подшивка, вторая страница.
    """
    key = await create(auth_client, "много замечаний")
    for index in range(4):
        await file_entry(auth_client, key, type="remark", title=f"замечание {index}")

    first_page = await auth_client.get("/api/v1/remarks", params={"limit": 2})
    cursor = first_page.json()["meta"]["next_cursor"]
    await file_entry(auth_client, key, type="remark", title="подшито во время листания")
    second_page = await auth_client.get("/api/v1/remarks", params={"limit": 2, "cursor": cursor})

    seen = [row["title"] for row in first_page.json()["data"]]
    seen += [row["title"] for row in second_page.json()["data"]]
    assert seen == ["замечание 0", "замечание 1", "замечание 2", "замечание 3"]
    assert len(seen) == len(set(seen))


async def test_the_inbox_filters_by_author_and_by_project(
    db_session: AsyncSession,
    auth_client: AsyncClient,
    task_actor: Actor,
    project: Project,
) -> None:
    """Обзорная проверка 4: «мои» — это подпись, и агентская подпись ищется так же.

    Замечание временного агента здесь главный случай: его подписи нет в реестре, и
    отбор, разрешающий автора по участникам, потерял бы её вовсе.
    """
    key = await create(auth_client, "чужие и свои")
    task = await tasks_service.get_task(db_session, key)
    agent = Actor(author=label_author("nightly_bot"), scope=TokenScope.TASK)
    await file_entry(auth_client, key, type="remark", title="от человека")
    await case_service.add_entry(
        db_session, task, actor=agent, type=EntryType.REMARK, title="от временного агента"
    )

    assert [title for _, _, title in await inbox(auth_client, author="owner")] == ["от человека"]
    assert [title for _, _, title in await inbox(auth_client, author="NIGHTLY_BOT")] == [
        "от временного агента"
    ]
    assert await inbox(auth_client, author="никого_такого_нет") == []
    assert len(await inbox(auth_client, project="trk")) == 2
    assert await inbox(auth_client, project="TRK", author="owner") == [
        (key, 2, "от человека"),
    ]


async def test_the_inbox_covers_closed_tasks(
    auth_client: AsyncClient,
    project: Project,
) -> None:
    """Обзорная проверка 5: замечание к `done` и к `cancelled` не теряется.

    Это не крайний случай, а основной: на сделанное человек и смотрит, когда говорит
    «вышло не то».
    """
    done = await create(auth_client, "сделанная")
    cancelled = await create(auth_client, "отменённая")
    await close(auth_client, done)
    moved = await auth_client.post(
        f"/api/v1/tasks/{cancelled}/transition", json={"to": "cancelled", "reason": "не нужна"}
    )
    assert moved.status_code == 200, moved.text
    await file_entry(auth_client, done, type="remark", title="к сделанной")
    await file_entry(auth_client, cancelled, type="remark", title="к отменённой")

    assert [(key, title) for key, _, title in await inbox(auth_client)] == [
        (done, "к сделанной"),
        (cancelled, "к отменённой"),
    ]


# --- MCP -------------------------------------------------------------------------------


async def test_resolve_refuses_a_continuation_with_a_wrong_outcome_in_mcp(
    mcp_session: Connect,
    task_secret: str,
    task: Task,
) -> None:
    """Отказ приходит тем же кодом, что и в REST: правило одно, а не два похожих."""
    key = task.key
    async with mcp_session(task_secret) as session:
        filed = await call(session, "add_entry", key=key, type="remark", title="Вышло не то")
        failure = await refuse(
            session,
            "resolve",
            key=key,
            remark_no=filed["no"],
            outcome="fixed",
            task=key,
        )
        resolved = await call(
            session,
            "resolve",
            key=key,
            remark_no=filed["no"],
            outcome="declined",
            body="Так и задумано",
        )
        stored = await call(session, "read_entries", key=key, nos=[resolved["no"]])
        package = await call(session, "get_task", key=key)

    assert "entry_fields_invalid" in failure
    # Ключ продолжения приезжает пустым, а не отсутствует: форма нагрузки одна и та же
    # в REST и в MCP, и «поля нет» против «поле пустое» читалось бы как два контракта.
    # Нагрузку смотрит `read_entries`: сам `resolve` отвечает коротко (TRK-35).
    assert stored["items"][0]["payload"] == {
        "remark_no": filed["no"],
        "outcome": "declined",
        "task": None,
    }
    assert package["remarks"] == []
    assert package["features"]["open_remarks"] == 0
