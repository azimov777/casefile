"""drop review status

Revision ID: f3b90c47ad15
Revises: d4a7c1e93f28
Create Date: 2026-09-05 17:00:00.000000+00:00

Статус `review` снят (`CONCEPT.md`, 3.3 и 6): обзорные проверки прогоняет исполнитель,
не выходя из `in_progress`, а требование положительного вердикта по каждой проверке
переехало на переход `in_progress → done`.

Миграция делает три вещи, и порядок между ними важен:

1. подшивает в дело каждой задачи, стоящей в `review`, запись `status_changed` от
   автора рода `tracker` — скачок статуса обязан быть объяснён в деле, иначе преемник
   увидит задачу в `in_progress` и не поймёт, куда делся её выход;
2. переводит сами задачи в `in_progress` и поднимает `version`: копия карточки, которую
   держит клиент, после такой правки устарела, и оптимистичная блокировка обязана это
   заметить;
3. заменяет ограничение CHECK на новый список значений. Последним: пока задачи ещё
   стоят в `review`, новое ограничение их бы и отвергло.

Записи подшиваются прямым `INSERT`, а не сценарием `services`: сценарий импортирует
доменное перечисление, в котором `review` уже нет, и на первой же задаче упал бы
разбором её текущего статуса. Ради этого же старые записи `status_changed` с `review` в
нагрузке остаются нетронутыми: журнал неизменяем, и переписывать историю миграция права
не имеет (`CONCEPT.md`, 3.4).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b90c47ad15"
down_revision: str | None = "d4a7c1e93f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_tasks_task_status"

STATUSES_BEFORE = ("backlog", "open", "in_progress", "review", "done", "cancelled")
STATUSES_AFTER = ("backlog", "open", "in_progress", "done", "cancelled")

#: Причина перехода в записи дела. Непустая по правилу шага назад и по здравому смыслу:
#: без неё запись говорит «статус сменился сам», чего в трекере не бывает.
REASON = (
    "Статус `review` снят: обзорные проверки идут в `in_progress`, "
    "вердикты по каждой проверке требуются перед `done`"
)

#: Номер записи выдаётся тем же правилом, что и в приложении (`allocate_no`): максимум
#: по задаче плюс один. Миграция идёт одной транзакцией на остановленной установке,
#: поэтому гонки за номером здесь нет.
RECORD_STATUS_CHANGED = """
INSERT INTO entries (
    task_id, no, type, title, body, payload, refs, created_by_kind, created_by_signature
)
SELECT
    tasks.id,
    COALESCE((SELECT MAX(entries.no) FROM entries WHERE entries.task_id = tasks.id), 0) + 1,
    'status_changed',
    'Status changed: review -> in_progress',
    '',
    jsonb_build_object('from', 'review', 'to', 'in_progress', 'reason', :reason),
    '[]'::jsonb,
    'tracker',
    NULL
FROM tasks
WHERE tasks.status = 'review'
"""

MOVE_TASKS = """
UPDATE tasks
SET status = 'in_progress', version = version + 1, updated_at = now()
WHERE status = 'review'
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
    # Причина едет параметром, а не подстановкой в текст: русский текст с обратными
    # кавычками в литерале SQL — заявка на сломанный запрос при первой же правке.
    op.execute(sa.text(RECORD_STATUS_CHANGED).bindparams(reason=REASON))
    op.execute(MOVE_TASKS)
    _replace_constraint(STATUSES_AFTER)


def downgrade() -> None:
    """Возвращает `review` в ограничение и **не** переводит задачи обратно.

    Перевод назад невозможен по-честному: после `upgrade` задача из `review` неотличима
    от задачи, которую взяли в работу сами, а угадывать по записям дела значит вернуть в
    `review` то, что там никогда не стояло. Подшитые записи `status_changed` тоже
    остаются: дело неизменяемо, и откат схемы историю не отменяет.
    """
    _replace_constraint(STATUSES_BEFORE)
