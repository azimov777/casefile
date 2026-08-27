"""Сколько задач ссылается на справочник — одна точка на весь проект.

Зачем модуль существует. Справочники защищены от разрушительных правок: статус с
задачами нельзя удалить, категорию такого статуса нельзя переопределить, очередь с
задачами нельзя стереть. Каждая из этих проверок должна пересчитать задачи, но самой
таблицы задач ещё нет — она появляется в задаче 05.

Поэтому здесь заглушки, и это временное состояние, а не архитектура. Задача 05 обязана
заменить тела функций настоящими запросами; до тех пор они честно отвечают «ноль» и
сами следят за тем, чтобы это не превратилось в тихую дыру: как только в реестре
моделей появится таблица `issues`, каждая функция начнёт падать с понятным сообщением.
Тихо разрешить удаление статуса, под которым стоят пятьсот задач, нельзя ничем.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base

#: Имя таблицы задач. Её появление в метаданных — признак того, что задача 05 сделана
#: и заглушки пора заменить настоящими запросами.
ISSUES_TABLE = "issues"

_REPLACEMENT_HINT = (
    "Issue table exists: replace the stubs in app/services/issue_usage.py "
    "with real queries before catalog protection can be trusted"
)


def _assert_still_a_stub() -> None:
    """Страховка от молчаливой дыры: заглушка обязана исчезнуть вместе с задачей 05.

    Проверка идёт по реестру моделей, а не по базе: она бесплатна и срабатывает ровно
    в тот момент, когда автор задачи 05 импортирует модель `Issue` в
    `app/db/models/__init__.py`. `NotImplementedError` здесь — правильная реакция:
    это ошибка разработки, а не ситуация, которую должен обрабатывать клиент.
    """
    if ISSUES_TABLE in Base.metadata.tables:
        raise NotImplementedError(_REPLACEMENT_HINT)


async def count_issues_with_status(session: AsyncSession, status_id: uuid.UUID) -> int:
    """Сколько задач стоит в этом статусе. Задача 05: `SELECT count(*) ... WHERE status_id = ?`."""
    _assert_still_a_stub()
    return 0


async def count_issues_with_issue_type(session: AsyncSession, issue_type_id: uuid.UUID) -> int:
    """Сколько задач этого типа."""
    _assert_still_a_stub()
    return 0


async def count_issues_with_resolution(session: AsyncSession, resolution_id: uuid.UUID) -> int:
    """Сколько задач закрыто с этой резолюцией."""
    _assert_still_a_stub()
    return 0


async def count_issues_in_queue(session: AsyncSession, queue_id: uuid.UUID) -> int:
    """Сколько задач в очереди. От этого зависит, можно ли очередь удалить."""
    _assert_still_a_stub()
    return 0


async def move_issues_to_status(
    session: AsyncSession,
    *,
    from_status_id: uuid.UUID,
    to_status_id: uuid.UUID,
    queue_id: uuid.UUID | None = None,
) -> int:
    """Переносит задачи из одного статуса в другой и возвращает число перенесённых.

    `queue_id` сужает перенос до одной очереди; `None` — переносить во всех.
    Задача 05: `UPDATE issues SET status_id = :to WHERE status_id = :from [AND queue_id = ...]`.
    Проверку допустимости целевого статуса делает вызывающий сценарий — здесь только запрос.
    """
    _assert_still_a_stub()
    return 0
