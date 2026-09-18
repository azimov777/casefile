"""Правка одной проверки и вердикт, оставшийся от прежней её формулировки.

Проверка, сформулированная невыполнимо, обходилась дороже, чем должна (`TRK-14`). Два
изъяна, и второй опаснее первого:

1. `checks` правились только целиком — чтобы поменять третью строку из восьми, надо было
   переслать все восемь, и опечатка в неизменённых семи проходила молча;
2. вердикт ссылается на **номер**, а не на текст, поэтому подшитый до правки оставался
   висеть на номере, который после неё значит другое. Читающий уверен, что проверка 3
   пройдена, хотя пройдена была её прежняя формулировка.

Всё проверяется через настоящий клиент MCP: правит проверки агент, и разбор аргумента,
служебная запись и опись дела — части одного и того же пути.
"""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.queue import Queue
from app.services import tasks as tasks_service
from app.services.auth import Actor
from conftest import Connect, call, refuse

#: Четыре проверки: их хватает, чтобы правка третьей оставила соседей с обеих сторон.
CHECKS = [
    "Первая проверка: набор тестов зелёный",
    "Вторая проверка: линтер чист",
    "Третья проверка: прежний код падает на движке WebKit",
    "Четвёртая проверка: сквозные тесты зелёные",
]

REWRITTEN = "Третья проверка: дефект показан на сборке Safari владельца"


@pytest.fixture
async def with_checks(mcp_session: Connect, task_secret: str, queue: Queue) -> str:
    """Задача в `backlog` с четырьмя проверками. Ключ строкой: объект после чужого
    вызова может оказаться устаревшим (`tests/conftest.py`)."""
    del queue
    async with mcp_session(task_secret) as session:
        created = await call(
            session,
            "create_task",
            queue="TRK",
            title="Правка проверки",
            description="Проверка сформулирована невыполнимо",
            sections={
                "goal": "цель",
                "context": "контекст",
                "constraints": "ограничения",
                "output": "выход",
                "checks": CHECKS,
            },
        )
    return str(created["key"])


async def test_one_check_is_edited_without_resending_the_rest(
    mcp_session: Connect, task_secret: str, with_checks: str
) -> None:
    """Обзорная проверка 2: правится третья, остальные три остаются теми же байтами.

    «Теми же байтами» — не фигура речи: пересылка списка целиком ради одной строки и
    была тем, что пропускало опечатку в остальных. Сравнение идёт со списком-образцом,
    а не с тем, что вернул сам вызов.
    """
    async with mcp_session(task_secret) as session:
        changed = await call(
            session, "update_task", key=with_checks, changes={"check": {"no": 3, "text": REWRITTEN}}
        )
        package = await call(session, "get_task", key=with_checks)

    assert package["task"]["checks"] == [CHECKS[0], CHECKS[1], REWRITTEN, CHECKS[3]]
    assert package["task"]["checks"][:2] == CHECKS[:2]
    assert package["task"]["checks"][3] == CHECKS[3]

    # Служебная запись называет номер, а не только факт «раздел изменён»: без номера
    # читающий не поймёт, какой из вердиктов после этого перестал относиться к делу.
    assert len(changed["entries"]) == 1
    filed = next(item for item in package["index"] if item["no"] == changed["entries"][0])
    assert filed["type"] == "section_changed"
    assert filed["facts"]["field"] == "checks"
    assert filed["facts"]["check_no"] == 3
    assert filed["title"] == "Section changed: checks[3]"


async def test_the_edit_carries_the_two_texts_and_not_the_whole_list(
    mcp_session: Connect, task_secret: str, with_checks: str
) -> None:
    """«Было / стало» у точечной правки — тексты самой проверки.

    Списки целиком здесь были бы копией того, что и так лежит в задаче, а разошедшимся
    с нею оказался бы именно нужный текст.
    """
    async with mcp_session(task_secret) as session:
        changed = await call(
            session, "update_task", key=with_checks, changes={"check": {"no": 3, "text": REWRITTEN}}
        )
        entries = await call(session, "read_entries", key=with_checks, nos=[changed["entries"][0]])

    payload = entries["items"][0]["payload"]
    assert payload == {"field": "checks", "before": CHECKS[2], "after": REWRITTEN, "check_no": 3}


async def test_the_list_and_the_point_edit_are_not_accepted_together(
    mcp_session: Connect, task_secret: str, with_checks: str
) -> None:
    """Два ответа на вопрос «каким стал раздел» — и выбрать между ними трекеру нечем."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session,
            "update_task",
            key=with_checks,
            changes={"checks": CHECKS, "check": {"no": 3, "text": REWRITTEN}},
        )

    assert "conflicts_with" in failure, failure
    assert "check" in failure


async def test_a_number_outside_the_list_is_refused_by_name(
    mcp_session: Connect, task_secret: str, with_checks: str
) -> None:
    """Номер — адрес, и адрес за пределами списка это ошибка, а не «нечего менять»."""
    async with mcp_session(task_secret) as session:
        failure = await refuse(
            session, "update_task", key=with_checks, changes={"check": {"no": 9, "text": REWRITTEN}}
        )

    assert "no_such_check" in failure, failure
    assert '"last": 4' in failure, failure


async def test_a_verdict_filed_before_the_rewrite_reads_as_outdated(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    task_actor: Actor,
    with_checks: str,
) -> None:
    """Обзорная проверка 3: вердикт по переписанной проверке виден устаревшим.

    Сама запись при этом не трогается: записи неизменяемы, и вердикт может быть только
    помечен тем, что случилось после него. Поэтому тело записи сравнивается до и после
    правки байт в байт.
    """
    key = with_checks
    task = await tasks_service.get_task(db_session, key)
    for status in ("open", "in_progress"):
        await tasks_service.transition_task(db_session, task, actor=task_actor, to=status)
    await db_session.commit()

    async with mcp_session(task_secret) as session:
        verdict = await call(
            session, "add_verdict", key=key, check_no=3, outcome="passed", evidence="Проверил"
        )
        before = await call(session, "read_entries", key=key, nos=[verdict["no"]])
        package_before = await call(session, "get_task", key=key)

        # Путь из карточки: сводка, шаг назад в `backlog`, правка.
        await call(
            session,
            "add_summary",
            key=key,
            done="Подшил вердикт",
            remaining="Переписать проверку 3",
            blockers="Ничего",
            next_step="Переписать проверку 3: сборка WebKit дефект не воспроизводит",
        )
        await call(session, "transition", key=key, to="backlog", reason="Проверка невыполнима")
        await call(session, "update_task", key=key, changes={"check": {"no": 3, "text": REWRITTEN}})

        after = await call(session, "read_entries", key=key, nos=[verdict["no"]])
        package_after = await call(session, "get_task", key=key)

    def heading(package: dict[str, Any]) -> dict[str, Any]:
        return next(item for item in package["index"] if item["no"] == verdict["no"])

    assert heading(package_before)["facts"]["outdated"] is False
    assert heading(package_after)["facts"]["outdated"] is True
    assert after["items"][0] == before["items"][0], "запись обязана остаться нетронутой"


async def test_a_whole_list_rewrite_outdates_every_verdict(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    task_actor: Actor,
    with_checks: str,
) -> None:
    """Правка списка целиком задевает любой номер: состав мог измениться.

    Точечная правка знает свой номер, а пересылка списка — нет: проверка могла быть
    добавлена или снята, и номера могли сдвинуться. Помечать в этом случае только
    «свой» вердикт было бы ложью, потому что своего у такой правки нет.
    """
    key = with_checks
    task = await tasks_service.get_task(db_session, key)
    for status in ("open", "in_progress"):
        await tasks_service.transition_task(db_session, task, actor=task_actor, to=status)
    await db_session.commit()

    async with mcp_session(task_secret) as session:
        first = await call(
            session, "add_verdict", key=key, check_no=1, outcome="passed", evidence="Прогон зелёный"
        )
        await call(
            session,
            "add_summary",
            key=key,
            done="Подшил вердикт",
            remaining="Переставить проверки",
            blockers="Ничего",
            next_step="Переставить проверки местами",
        )
        await call(session, "transition", key=key, to="backlog", reason="Состав проверок неверен")
        await call(session, "update_task", key=key, changes={"checks": [*CHECKS, "Пятая проверка"]})
        package = await call(session, "get_task", key=key)

    heading = next(item for item in package["index"] if item["no"] == first["no"])
    assert heading["facts"]["outdated"] is True


async def test_a_task_with_an_outdated_verdict_does_not_close(
    mcp_session: Connect,
    task_secret: str,
    db_session: AsyncSession,
    task_actor: Actor,
    with_checks: str,
) -> None:
    """Обзорная проверка 4: переписанная проверка требует нового вердикта.

    Случай UI-39 целиком: вердикт подшит, проверка оказалась невыполнимой, переписана,
    задача взята заново. Старый вердикт в зачёт не идёт — и отказ называет номер, а не
    сообщает «что-то не так с проверками».
    """
    key = with_checks
    task = await tasks_service.get_task(db_session, key)
    for status in ("open", "in_progress"):
        await tasks_service.transition_task(db_session, task, actor=task_actor, to=status)
    await db_session.commit()

    async with mcp_session(task_secret) as session:
        for check_no in (1, 2, 3, 4):
            await call(
                session,
                "add_verdict",
                key=key,
                check_no=check_no,
                outcome="passed",
                evidence="Проверил",
            )
        await call(
            session,
            "add_summary",
            key=key,
            done="Подшил четыре вердикта",
            remaining="Переписать проверку 3",
            blockers="Ничего",
            next_step="Переписать проверку 3 и проверить заново",
        )
        await call(session, "transition", key=key, to="backlog", reason="Проверка невыполнима")
        await call(session, "update_task", key=key, changes={"check": {"no": 3, "text": REWRITTEN}})
        await call(session, "transition", key=key, to="open")
        await call(session, "transition", key=key, to="in_progress")
        failure = await refuse(
            session,
            "close_task",
            key=key,
            summary={
                "done": "Проверка переписана",
                "remaining": "Проверить заново",
                "blockers": "Ничего",
                "next_step": "Подшить вердикты по нынешним формулировкам",
                "unmeasured": "Отказ ждём на вердиктах, форму сводки тут не мерим",
            },
        )

    assert "checks_not_passed" in failure, failure
    assert '"check_no": 3' in failure, failure
