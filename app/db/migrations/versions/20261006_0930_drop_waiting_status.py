"""drop waiting status

Revision ID: a9cb1ec147c4
Revises: 4b8e2d7c1f90
Create Date: 2026-10-06 09:30:00.000000+00:00

Статус `waiting` снят (TRK#121; TRK-573, решение владельца
TRK-569#9). Ожидание больше не хранится: его держит носитель в деле — вопрос с `blocking`
или связь `blocked_by`, — а ждущая задача стоит в `open` и становится кандидатом сама,
когда носитель закрыт.

Миграция повторяет снятие `review` (ревизия `f3b90c47ad15`) и делает три вещи по порядку:

1. подшивает в дело каждой задачи, стоящей в `waiting`, запись `status_changed`
   `waiting → open` от автора рода `tracker` с причиной, называющей TRK-573: скачок
   статуса обязан быть объяснён в деле, иначе преемник увидит задачу в `open` и не
   поймёт, куда делось ожидание. У каждой записи свой `action_id`;
2. переводит сами задачи в `open` и поднимает `version`: копия карточки у клиента после
   такой правки устарела, и оптимистичная блокировка обязана это заметить;
3. заменяет ограничение CHECK на список без `waiting`. Последним: пока задачи ещё стоят
   в `waiting`, новое ограничение их бы и отвергло.

Переводятся все задачи в `waiting`, в том числе задачи архивных проектов: заморозка
архива — правило сценариев, а не схемы, и задача, оставленная в снятом статусе, не
прошла бы новое ограничение. Ожидание без носителя миграция не угадывает и вопросов не
подшивает: до выпуска задачи установки разобраны так, чтобы у каждой ожидание держалось
на вопросе или блокере (TRK-570).

## Как у кода, но без кода

Сценарий приложения отсюда не вызывается: он импортирует доменное перечисление, где
`waiting` уже нет, и упал бы на разборе текущего статуса первой же задачи. Поэтому
повторена его суть: сначала очередь изменений (`pg_advisory_xact_lock` с ключом
`CHANGES_LOCK` из `app/db/locks.py`), потом строки; `no` — `max(no) + 1` среди записей
задачи, как у `EntryRepository.allocate_no`; `seq` выдаёт `IDENTITY`. Старые записи
`status_changed` с `waiting` в нагрузке не трогаются: журнал неизменяем (TRK#127),
а при чтении незнакомый статус в фактах описи читается как `null`
(`app/db/repositories/entries.py`, `_as_enum`).

Имена не квалифицированы схемой: приём архива переноса установки гоняет миграции во
временной схеме, и архив прежней версии с задачами в `waiting` проходит этот же перевод
(TRK#202).

## Откат

Возвращает `waiting` в ограничение и **не** переводит задачи обратно. После `upgrade`
задача, дождавшаяся в `open`, неотличима от задачи, которую туда поставили сами, а
угадывать по записям дела значит вернуть в `waiting` то, что там уже не стоит.
Подшитые записи `status_changed` тоже остаются: дело неизменяемо, и откат схемы историю
не отменяет.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9cb1ec147c4"
down_revision: str | None = "4b8e2d7c1f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ключ очереди изменений — `CHANGES_LOCK` (`app/db/locks.py`).
CHANGES_LOCK = 0x6A6F75726E616C

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_tasks_task_status"

STATUSES_BEFORE = ("backlog", "open", "in_progress", "waiting", "done", "cancelled")
STATUSES_AFTER = ("backlog", "open", "in_progress", "done", "cancelled")

#: Причина перехода в записи дела. Называет задачу, снявшую статус, и носитель, который
#: держит ожидание теперь: без неё запись говорила бы «статус сменился сам», чего в
#: трекере не бывает.
REASON = (
    "TRK-573: статус `waiting` снят решением владельца TRK-569#9. Ожидание держит "
    "носитель в деле — вопрос `blocking` или связь `blocked_by`; ждущая задача стоит "
    "в `open` и становится кандидатом, когда носитель закрыт"
)

RECORD_STATUS_CHANGED = """
INSERT INTO entries (
    task_id, no, type, title, body, payload, refs, action_id,
    created_by_kind, created_by_signature
)
SELECT
    tasks.id,
    COALESCE((SELECT max(entries.no) FROM entries WHERE entries.task_id = tasks.id), 0) + 1,
    'status_changed',
    'Status changed: waiting -> open',
    '',
    jsonb_build_object('from', 'waiting', 'to', 'open', 'reason', CAST(:reason AS text)),
    '[]'::jsonb,
    gen_random_uuid(),
    'tracker',
    NULL
FROM tasks
WHERE tasks.status = 'waiting'
ORDER BY tasks.key
"""

MOVE_TASKS = """
UPDATE tasks
SET status = 'open', version = version + 1, updated_at = now()
WHERE status = 'waiting'
"""


def _replace_constraint(statuses: Sequence[str]) -> None:
    """Меняет список допустимых статусов заменой ограничения CHECK.

    Перечисления в проекте — VARCHAR с CHECK, а не native enum (`app/db/base.py`,
    `string_enum`), ровно ради этой операции: у native enum значение так просто не
    снять.
    """
    values = ", ".join(f"'{status}'" for status in statuses)
    op.execute(f"ALTER TABLE tasks DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE tasks ADD CONSTRAINT {CONSTRAINT} CHECK (status IN ({values}))")


def upgrade() -> None:
    op.execute(f"SELECT pg_advisory_xact_lock({CHANGES_LOCK})")
    # Причина едет параметром, а не подстановкой в текст: русский текст с обратными
    # кавычками в литерале SQL — заявка на сломанный запрос при первой же правке.
    op.execute(sa.text(RECORD_STATUS_CHANGED).bindparams(reason=REASON))
    op.execute(MOVE_TASKS)
    _replace_constraint(STATUSES_AFTER)


def downgrade() -> None:
    """Возвращает `waiting` в ограничение и **не** переводит задачи обратно (см. шапку)."""
    _replace_constraint(STATUSES_BEFORE)
