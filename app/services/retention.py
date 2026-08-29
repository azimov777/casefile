"""Чистка растущих журналов: один проход по трём таблицам.

Сценарий запускается командой (`python -m app.cli cleanup`) и, если включено
расписание, планировщиком автодействий. Политика и согласование с окном
переподключения SSE живут в `app/domain/retention.py` — здесь только оркестрация.

## Пачки коммитятся по одной, и это осознанное отступление

Границу транзакции в проекте держит вход в приложение, а сценарий коммитит сам только
там, где нужна промежуточная фиксация. Здесь она нужна: смысл пачки в том, чтобы
блокировка снималась и WAL сбрасывался по ходу прохода, а не в самом конце. Проход,
прерванный на середине, оставляет удалённым ровно то, что успел, — доделает следующий
запуск.

## Необработанное сроку хранения не подчиняется

Событие, до которого не дошёл воркер, и доставка, ожидающая повтора, не удаляются
никогда, каким бы старым ни был их `created_at`. Это не история, а невыполненная
работа: удалить её значит потерять её, а не убрать журнал. У очереди событий и у
очереди доставок статус `pending` поэтому исключён на уровне выборки репозитория, а не
проверкой здесь.

## Пустой реестр правил не даёт праву на удаление

Журнал правила, удалённого из кода, чистится по своему — более короткому — сроку, а
отличается он от журнала живого правила только сверкой с реестром. Если реестр по
какой-то причине пуст, все записи выглядят «правилами, которых больше нет», и короткий
срок снёс бы историю живых правил. Поэтому пустой реестр отменяет разделение: весь
журнал чистится по сроку живых правил, а отдельная строка отчёта говорит, почему.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.repositories import (
    AutomationRunRepository,
    OutboxRepository,
    WebhookDeliveryRepository,
)
from app.domain.retention import (
    RetentionPolicy,
    RetentionReport,
    RetentionTarget,
    StreamWindowCheck,
    TargetOutcome,
    utcnow,
)
from app.services import automation as automation_service

logger = get_logger("retention")

#: Причина, по которой цель пропущена. Строкой, а не флагом: она печатается в отчёте.
NO_RULE_REGISTRY = "rule registry is empty, every run is treated as a live one"


def policy_from_settings(settings: Settings | None = None) -> RetentionPolicy:
    """Политика из настроек установки. Значения проверяет сама политика."""
    settings = settings or get_settings()
    return RetentionPolicy(
        outbox_days=settings.retention_outbox_days,
        automation_runs_days=settings.retention_automation_runs_days,
        orphan_runs_days=settings.retention_orphan_runs_days,
        webhook_deliveries_days=settings.retention_webhook_deliveries_days,
        batch_size=settings.retention_batch_size,
        max_batches=settings.retention_max_batches,
    )


async def cleanup(
    session: AsyncSession,
    *,
    policy: RetentionPolicy | None = None,
    replay_limit: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> RetentionReport:
    """Один проход чистки. Возвращает отчёт: что удалено и что осталось несогласованным.

    `dry_run` считает подходящие строки и ничего не удаляет — первый запуск на живой
    установке стоит делать именно так: числа в отчёте показывают, во что обойдётся
    настоящий проход.
    """
    settings = get_settings()
    policy = policy or policy_from_settings(settings)
    replay_limit = settings.stream_replay_limit if replay_limit is None else replay_limit
    started_at = now or utcnow()

    outbox, window = await _sweep_outbox(
        session,
        policy=policy,
        replay_limit=replay_limit,
        now=started_at,
        dry_run=dry_run,
    )
    runs = await _sweep_runs(session, policy=policy, now=started_at, dry_run=dry_run)
    deliveries = await _sweep_deliveries(session, policy=policy, now=started_at, dry_run=dry_run)

    report = RetentionReport(
        outcomes=(outbox, *runs, deliveries),
        stream_window=window,
        started_at=started_at,
        dry_run=dry_run,
    )
    if not window.is_consistent:
        # Предупреждение, а не отказ: обещание уже защищено полом окна, и отказ оставил
        # бы таблицу расти. Молчать при этом нельзя — расхождение настроек чинит человек.
        logger.warning("%s", window.message())
    if report.capped:
        logger.warning(
            "Retention pass hit its per-target limit of %s rows; run it again",
            policy.max_rows,
        )
    return report


async def _sweep_outbox(
    session: AsyncSession,
    *,
    policy: RetentionPolicy,
    replay_limit: int,
    now: datetime,
    dry_run: bool,
) -> tuple[TargetOutcome, StreamWindowCheck]:
    """Очередь событий: возраст и пол окна переподключения ограничивают проход вместе."""
    repository = OutboxRepository(session)
    cutoff = policy.cutoff(RetentionTarget.OUTBOX_EVENTS, now=now)
    floor = await repository.replay_floor(replay_limit=replay_limit)
    kept = await repository.count_kept_by_window(cutoff=cutoff, floor=floor)

    window = StreamWindowCheck(
        replay_limit=replay_limit,
        retention_days=policy.outbox_days,
        cutoff=cutoff,
        oldest_replayable_at=None if floor is None else floor[0],
        protected=kept,
    )
    outcome = await _sweep(
        session,
        target=RetentionTarget.OUTBOX_EVENTS,
        cutoff=cutoff,
        policy=policy,
        dry_run=dry_run,
        count=lambda: repository.count_expired(cutoff=cutoff, floor=floor),
        delete=lambda limit: repository.delete_expired(cutoff=cutoff, floor=floor, limit=limit),
        protected=kept,
    )
    return outcome, window


async def _sweep_runs(
    session: AsyncSession,
    *,
    policy: RetentionPolicy,
    now: datetime,
    dry_run: bool,
) -> tuple[TargetOutcome, TargetOutcome]:
    """Журнал автоматики: живые правила и правила, которых больше нет в коде.

    Порядок важен: сначала журнал живых правил по своему сроку, потом журнал
    исчезнувших по короткому. Наоборот работало бы так же, но отчёт читался бы хуже —
    в нём сначала идёт то, что чистится всегда.
    """
    repository = AutomationRunRepository(session)
    known = sorted(definition.key for definition in automation_service.definitions())

    live_cutoff = policy.cutoff(RetentionTarget.AUTOMATION_RUNS, now=now)
    live = await _sweep(
        session,
        target=RetentionTarget.AUTOMATION_RUNS,
        cutoff=live_cutoff,
        policy=policy,
        dry_run=dry_run,
        count=lambda: repository.count_expired(
            cutoff=live_cutoff,
            known_rule_keys=known or None,
        ),
        delete=lambda limit: repository.delete_expired(
            cutoff=live_cutoff,
            limit=limit,
            known_rule_keys=known or None,
        ),
    )

    orphan_cutoff = policy.cutoff(RetentionTarget.ORPHAN_AUTOMATION_RUNS, now=now)
    if not known:
        logger.warning("Retention skipped orphan runs: %s", NO_RULE_REGISTRY)
        orphan = TargetOutcome(
            target=RetentionTarget.ORPHAN_AUTOMATION_RUNS,
            cutoff=orphan_cutoff,
            deleted=0,
            batches=0,
            skipped=NO_RULE_REGISTRY,
        )
        return live, orphan

    orphan = await _sweep(
        session,
        target=RetentionTarget.ORPHAN_AUTOMATION_RUNS,
        cutoff=orphan_cutoff,
        policy=policy,
        dry_run=dry_run,
        count=lambda: repository.count_expired(
            cutoff=orphan_cutoff,
            known_rule_keys=known,
            orphan=True,
        ),
        delete=lambda limit: repository.delete_expired(
            cutoff=orphan_cutoff,
            limit=limit,
            known_rule_keys=known,
            orphan=True,
        ),
    )
    return live, orphan


async def _sweep_deliveries(
    session: AsyncSession,
    *,
    policy: RetentionPolicy,
    now: datetime,
    dry_run: bool,
) -> TargetOutcome:
    """Журнал доставок вебхуков. Ожидающие повтора не трогаются, см. шапку модуля."""
    repository = WebhookDeliveryRepository(session)
    cutoff = policy.cutoff(RetentionTarget.WEBHOOK_DELIVERIES, now=now)
    return await _sweep(
        session,
        target=RetentionTarget.WEBHOOK_DELIVERIES,
        cutoff=cutoff,
        policy=policy,
        dry_run=dry_run,
        count=lambda: repository.count_expired(cutoff=cutoff),
        delete=lambda limit: repository.delete_expired(cutoff=cutoff, limit=limit),
    )


async def _sweep(
    session: AsyncSession,
    *,
    target: RetentionTarget,
    cutoff: datetime,
    policy: RetentionPolicy,
    dry_run: bool,
    count: Callable[[], Awaitable[int]],
    delete: Callable[[int], Awaitable[int]],
    protected: int = 0,
) -> TargetOutcome:
    """Удаляет одну цель пачками, пока не кончатся строки или пачки.

    Потолок пачек — не перестраховка: без него первый запуск на установке, которая
    росла год, удалял бы миллионы строк одним заходом. Упёршись в потолок, проход
    сообщает об этом, и остаток забирает следующий запуск — а не тянет базу часами.
    """
    if dry_run:
        pending = await count()
        return TargetOutcome(
            target=target,
            cutoff=cutoff,
            deleted=pending,
            batches=0,
            capped=pending > policy.max_rows,
            protected=protected,
        )

    deleted = 0
    batches = 0
    capped = False
    while True:
        if batches >= policy.max_batches:
            capped = await count() > 0
            break
        removed = await delete(policy.batch_size)
        if removed:
            # Коммит на пачку: см. шапку модуля. Без него блокировка держится до конца
            # прохода, и вся его работа лежит в одной транзакции.
            await session.commit()
            deleted += removed
            batches += 1
        if removed < policy.batch_size:
            break

    return TargetOutcome(
        target=target,
        cutoff=cutoff,
        deleted=deleted,
        batches=batches,
        capped=capped,
        protected=protected,
    )
