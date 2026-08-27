"""Сколько задач ссылается на справочник или на поле — одна точка на весь проект.

Зачем модуль существует. Справочники и реестр полей защищены от разрушительных
правок: статус с задачами нельзя удалить, категорию такого статуса нельзя
переопределить, очередь с задачами нельзя стереть, у поля со значениями нельзя
поменять тип и нельзя удалить вариант перечисления, которым пользуются. Каждая из
этих проверок должна пересчитать задачи — и делает это отсюда.

Отдельный модуль, а не метод репозитория напрямую, — ради направления зависимостей.
Сценарии справочников и полей не должны знать про сценарии задач: иначе три модуля
замкнулись бы в цикл (задачи проверяют статусы, статусы считают задачи). Здесь же
лежит тонкая прослойка, которая знает только про таблицу задач и ничего — про её
сценарии.

Функции ничего не проверяют и ничего не запрещают: они отвечают числом, а решение
принимает вызывающий сценарий. Транзакцию не фиксируют — границу держит вход в
приложение.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import IssueRepository


async def count_issues_with_status(session: AsyncSession, status_id: uuid.UUID) -> int:
    """Сколько задач стоит в этом статусе."""
    return await IssueRepository(session).count_by_status(status_id)


async def count_issues_with_issue_type(session: AsyncSession, issue_type_id: uuid.UUID) -> int:
    """Сколько задач этого типа."""
    return await IssueRepository(session).count_by_issue_type(issue_type_id)


async def count_issues_with_resolution(session: AsyncSession, resolution_id: uuid.UUID) -> int:
    """Сколько задач закрыто с этой резолюцией."""
    return await IssueRepository(session).count_by_resolution(resolution_id)


async def count_issues_in_queue(session: AsyncSession, queue_id: uuid.UUID) -> int:
    """Сколько задач в очереди. От этого зависит, можно ли очередь удалить."""
    return await IssueRepository(session).count_in_queue(queue_id)


async def move_issues_to_status(
    session: AsyncSession,
    *,
    from_status_id: uuid.UUID,
    to_status_id: uuid.UUID,
    queue_id: uuid.UUID | None = None,
) -> int:
    """Переносит задачи из одного статуса в другой и возвращает число перенесённых.

    `queue_id` сужает перенос до одной очереди; `None` — переносить во всех.
    Проверку допустимости целевого статуса делает вызывающий сценарий — здесь только
    запрос. Массовый `UPDATE` идёт мимо объектов сессии и мимо единой точки применения
    изменений: журнала он не пишет и события не порождает. Это осознанно — перенос
    сотни задач одной строкой истории понятнее сотни одинаковых записей, — но задача 06
    обязана решить это явно, а не унаследовать молчание.
    """
    return await IssueRepository(session).move_to_status(
        from_status_id=from_status_id,
        to_status_id=to_status_id,
        queue_id=queue_id,
    )


async def count_issues_with_field(session: AsyncSession, field_ref: str) -> int:
    """Сколько задач имеет значение этого поля.

    От ответа зависят три запрета сразу: сменить тип поля, сменить его множественность
    и удалить поле насовсем вместо того, чтобы скрыть.

    Адресация — ссылкой (`severity`, `TRK.severity`), потому что именно она служит
    ключом в `values`; формат описан в `app/domain/fields.py`.
    """
    return await IssueRepository(session).count_with_field(field_ref)


async def count_issues_with_field_value(
    session: AsyncSession,
    field_ref: str,
    value: Any,
) -> int:
    """Сколько задач держит в этом поле именно это значение.

    Нужна, чтобы не дать выбросить вариант перечисления, которым уже пользуются:
    задачи остались бы со значением, которого нет в списке вариантов.

    Множественное поле хранит массив, одиночное — скаляр, и запрос учитывает оба случая.
    """
    return await IssueRepository(session).count_with_field_value(field_ref, value)


async def missing_issue_keys(session: AsyncSession, keys: set[str]) -> set[str]:
    """Какие из ключей не принадлежат существующим задачам.

    Нужна валидатору кастомных полей: поле типа «ссылка на задачу» не должно принимать
    ключ несуществующей задачи. Одним запросом на весь набор, а не по ключу за раз.
    """
    if not keys:
        return set()
    return keys - await IssueRepository(session).existing_keys(keys)
