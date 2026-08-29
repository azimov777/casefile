"""Выборки по состоянию правил автоматики и по журналу срабатываний.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение.

Нетривиального здесь два места. `claim_due` — выборка планировщика, устроенная так же,
как выборка воркера из outbox. `count_since` — счётчик для защиты от зацикливания, и он
обязан считать по строкам журнала, а не по счётчику в памяти процесса: движок работает и
в воркере, и в планировщике, и в обработчике HTTP-запроса, а лимит у правила один.
"""

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.automation import AutomationRule, AutomationRun
from app.db.pagination import Page, paginate
from app.domain.automation import RunStatus


class AutomationRuleRepository:
    """Состояние правил: чтение реестром, синхронизация, выборка планировщиком."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flush(self) -> None:
        await self._session.flush()

    async def get_by_key(self, rule_key: str) -> AutomationRule | None:
        statement = select(AutomationRule).where(AutomationRule.rule_key == rule_key)
        return (await self._session.scalars(statement)).one_or_none()

    async def get_by_id(self, rule_id: uuid.UUID) -> AutomationRule | None:
        return await self._session.get(AutomationRule, rule_id)

    async def insert_missing(self, params_by_key: Mapping[str, dict[str, Any]]) -> list[str]:
        """Заводит строки под ключи, которых ещё нет. Возвращает **заведённые** ключи.

        Одна вставка с `ON CONFLICT DO NOTHING`, а не «прочитать существующие ключи и
        добавить недостающие». Синхронизацию запускают три процесса сразу — API в
        lifespan, воркер и планировщик первым шагом цикла, — и на пустой базе они делают
        это одновременно. Между чтением и вставкой успевает вклиниться другой процесс,
        поэтому проверка перед вставкой гонку не закрывает ни в каком порядке: закрывает
        её только атомарность самой вставки.

        `RETURNING` отдаёт строки, которые вставились на самом деле, а не те, которые
        вставить пытались: вызывающий пишет этот список в лог, и у проигравшего гонку он
        обязан быть пустым.

        Существующую строку вставка не трогает — ни включённость, ни параметры, ни
        привязку к очереди: это состояние, настроенное человеком, а объявление из кода
        его не переопределяет.
        """
        if not params_by_key:
            return []
        statement = (
            # Таблица, а не модель: ORM-вставка с `RETURNING` ждёт строку на каждую
            # переданную, а `DO NOTHING` их как раз пропускает.
            pg_insert(AutomationRule.__table__)
            .values(
                [
                    {"rule_key": key, "params": params}
                    for key, params in sorted(params_by_key.items())
                ]
            )
            .on_conflict_do_nothing(index_elements=[AutomationRule.rule_key])
            .returning(AutomationRule.rule_key)
        )
        return sorted((await self._session.execute(statement)).scalars().all())

    async def list_all(self) -> list[AutomationRule]:
        statement = select(AutomationRule).order_by(AutomationRule.rule_key)
        return list((await self._session.scalars(statement)).unique())

    async def list_page(
        self,
        *,
        queue_id: uuid.UUID | None = None,
        is_enabled: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[AutomationRule]:
        statement = select(AutomationRule)
        if queue_id is not None:
            statement = statement.where(AutomationRule.queue_id == queue_id)
        if is_enabled is not None:
            statement = statement.where(AutomationRule.is_enabled.is_(is_enabled))
        return await paginate(
            self._session,
            statement,
            AutomationRule,
            limit=limit,
            cursor=cursor,
        )

    async def claim_due(self, *, now: datetime, keys: Sequence[str]) -> list[AutomationRule]:
        """Автодействия, которым пришло время, с блокировкой строк до конца транзакции.

        `FOR UPDATE SKIP LOCKED` — та же механика, что у `claim_next` в outbox, и нужна
        по той же причине: планировщик обязан быть в единственном экземпляре, но если
        второй всё-таки поднимут, он должен пройти мимо занятой строки, а не выполнить
        то же автодействие второй раз.

        `keys` — ключи автодействий, объявленных в коде **этого** процесса. Без этого
        ограничения планировщик заблокировал бы и строку правила, объявления которого у
        него нет, и держал бы её до конца транзакции просто чтобы пропустить.
        """
        if not keys:
            return []
        statement = (
            select(AutomationRule)
            .where(
                AutomationRule.rule_key.in_(list(keys)),
                AutomationRule.is_enabled.is_(True),
                AutomationRule.next_run_at.isnot(None),
                AutomationRule.next_run_at <= now,
            )
            .order_by(AutomationRule.next_run_at)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.scalars(statement)).unique())


class AutomationRunRepository:
    """Журнал срабатываний: запись движком, чтение человеком, счёт защитой от циклов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: AutomationRun) -> AutomationRun:
        self._session.add(run)
        await self._session.flush()
        return run

    async def list_page(
        self,
        *,
        rule_id: uuid.UUID | None = None,
        issue_id: uuid.UUID | None = None,
        status: RunStatus | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[AutomationRun]:
        statement = select(AutomationRun)
        if rule_id is not None:
            statement = statement.where(AutomationRun.rule_id == rule_id)
        if issue_id is not None:
            statement = statement.where(AutomationRun.issue_id == issue_id)
        if status is not None:
            statement = statement.where(AutomationRun.status == status)
        return await paginate(self._session, statement, AutomationRun, limit=limit, cursor=cursor)

    async def count_since(
        self,
        *,
        rule_id: uuid.UUID,
        issue_id: uuid.UUID | None,
        since: datetime,
    ) -> int:
        """Сколько раз правило **сделало что-то** с этой задачей за окно времени.

        Считаются только успешные срабатывания, и это принципиально: пропуски и отказы
        задачу не меняют и событий не порождают, а значит цикла не образуют. Считать их
        значило бы, что правило, честно отвечающее «условие не выполнено» на каждое
        событие волны, само себя и заблокирует.
        """
        statement = (
            select(func.count())
            .select_from(AutomationRun)
            .where(
                AutomationRun.rule_id == rule_id,
                AutomationRun.status == RunStatus.SUCCESS,
                AutomationRun.created_at >= since,
            )
        )
        statement = statement.where(
            AutomationRun.issue_id.is_(None)
            if issue_id is None
            else AutomationRun.issue_id == issue_id
        )
        return (await self._session.scalar(statement)) or 0

    async def last_success_at(
        self,
        *,
        rule_id: uuid.UUID,
        issue_id: uuid.UUID,
    ) -> datetime | None:
        """Когда правило в последний раз что-то сделало с этой задачей.

        Нужно самим правилам, а не движку: автодействие, которое пишет комментарий, не
        меняет строку задачи, поэтому его собственный фильтр «без движения 7 дней»
        останется истинным и на следующем тике. Без этого вопроса такое правило
        комментировало бы одну задачу каждый тик расписания.
        """
        statement = select(func.max(AutomationRun.created_at)).where(
            AutomationRun.rule_id == rule_id,
            AutomationRun.issue_id == issue_id,
            AutomationRun.status == RunStatus.SUCCESS,
        )
        return await self._session.scalar(statement)

    def _expired(
        self,
        *,
        cutoff: datetime,
        known_rule_keys: Collection[str] | None,
        orphan: bool,
    ) -> Select[tuple[uuid.UUID]]:
        """Идентификаторы записей журнала под удаление, от самых старых.

        `known_rule_keys` — ключи правил, объявленных в коде **сейчас**. Строку правила,
        исчезнувшего из кода, синхронизация реестра не удаляет (иначе каскад унёс бы
        вместе с ней весь журнал), поэтому отличить «журнал живого правила» от «журнала
        правила, которого больше нет» можно только сверкой с реестром. Сверка идёт по
        `rule_key` самой записи, а не через соединение с таблицей правил: копия ключа
        лежит в строке журнала ровно для таких вопросов.

        `known_rule_keys=None` означает «не различать»: срок один на весь журнал.
        Допустимо только с `orphan=False` — с `orphan=True` это выбрало бы все строки
        разом под самый короткий срок.
        """
        if orphan and known_rule_keys is None:
            raise ValueError("Orphan runs cannot be selected without the list of known rules")
        statement = (
            select(AutomationRun.id)
            .where(AutomationRun.created_at < cutoff)
            .order_by(AutomationRun.created_at, AutomationRun.id)
        )
        if known_rule_keys is None:
            return statement
        keys = sorted(known_rule_keys)
        if orphan:
            return statement.where(AutomationRun.rule_key.notin_(keys))
        return statement.where(AutomationRun.rule_key.in_(keys))

    async def count_expired(
        self,
        *,
        cutoff: datetime,
        known_rule_keys: Collection[str] | None = None,
        orphan: bool = False,
    ) -> int:
        """Сколько записей журнала старше срока."""
        expired = self._expired(
            cutoff=cutoff,
            known_rule_keys=known_rule_keys,
            orphan=orphan,
        ).subquery()
        statement = select(func.count()).select_from(expired)
        return int((await self._session.scalar(statement)) or 0)

    async def delete_expired(
        self,
        *,
        cutoff: datetime,
        limit: int,
        known_rule_keys: Collection[str] | None = None,
        orphan: bool = False,
    ) -> int:
        """Удаляет одну пачку самых старых записей. Возвращает число удалённых строк.

        Пачкой, а не одной командой: журнал автоматики — самая быстрорастущая из трёх
        таблиц на включённом правиле, и `DELETE` без потолка держал бы блокировку всё
        время выполнения.
        """
        victims = self._expired(
            cutoff=cutoff,
            known_rule_keys=known_rule_keys,
            orphan=orphan,
        ).limit(limit)
        statement = delete(AutomationRun).where(AutomationRun.id.in_(victims.scalar_subquery()))
        result = await self._session.execute(
            statement,
            execution_options={"synchronize_session": False},
        )
        return result.rowcount or 0
