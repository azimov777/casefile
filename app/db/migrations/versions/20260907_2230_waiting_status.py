"""waiting status

Revision ID: a1c7e64b0d92
Revises: b8e5f2a10c47
Create Date: 2026-09-07 22:30:00.000000+00:00

Статус `waiting` заведён (`CONCEPT.md`, 3.3): задача, у которой следующий ход за
человеком или за внешним событием, говорит об этом статусом и находится отбором
`status: waiting`, а не вычитыванием сводок всех задач в работе.

Миграция состоит из одной операции — расширения списка допустимых значений в
ограничении CHECK. Данные не трогаются, и это не упущение: новый статус никому не
наследуется. Задача попадает в `waiting` только явным переходом, а угадать по прошлым
сводкам, кто из стоящих в `in_progress` на самом деле ждал человека, миграция не может и
пытаться не должна — это переписывание истории (`CONCEPT.md`, 3.4).

Обратная миграция симметрична и требует, чтобы в `waiting` уже никого не было: см.
`downgrade`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c7e64b0d92"
down_revision: str | None = "b7d41e2a9c53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_tasks_task_status"

STATUSES_BEFORE = ("backlog", "open", "in_progress", "done", "cancelled")
STATUSES_AFTER = ("backlog", "open", "in_progress", "waiting", "done", "cancelled")


def _replace_constraint(statuses: Sequence[str]) -> None:
    """Меняет список допустимых статусов заменой ограничения CHECK.

    Перечисления в проекте — VARCHAR с CHECK, а не native enum (`app/db/base.py`,
    `string_enum`), ровно ради этой операции: у native enum новое значение недоступно в
    той же транзакции, где его добавили.
    """
    values = ", ".join(f"'{status}'" for status in statuses)
    op.execute(f"ALTER TABLE tasks DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE tasks ADD CONSTRAINT {CONSTRAINT} CHECK (status IN ({values}))")


def upgrade() -> None:
    _replace_constraint(STATUSES_AFTER)


def downgrade() -> None:
    """Сужает ограничение обратно и **падает**, если в `waiting` кто-то стоит.

    Задачи назад не переводятся намеренно. Куда возвращать ждущую задачу, знает только
    тот, кто её туда отправил: в `open`, если ждали ответа, в `in_progress`, если работа
    шла. Выбрать за него значило бы соврать в статусе, а подшить об этом запись в дело
    откат схемы права не имеет. Поэтому откат требует, чтобы установку разобрали руками:
    отказ ограничения с именем таблицы понятнее молчаливого перевода не туда.
    """
    _replace_constraint(STATUSES_BEFORE)
