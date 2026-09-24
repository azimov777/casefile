"""project description limit

Revision ID: b7d2f94c0e15
Revises: 8e4a61c3d2f7
Create Date: 2026-09-25 03:00:00.000000+00:00

Описание проекта не длиннее 320 знаков (`CONCEPT.md`, 3.2, «Переход с очередей»; TRK-153,
TRK-158): оно едет в карточке задачи. Описания длиннее — наследство очередей, где в одном
markdown слипались «что это», факты и решения, — переезжают без потерь:

- каждое описание длиннее предела становится записью `note` в деле своего проекта:
  заголовок «Описание до v0.4.0», тело — прежний текст дословно, автор — сам трекер
  (род `tracker`, без подписи), `action_id` свой у каждого проекта;
- поле описания у такого проекта пустеет; описания не длиннее предела не трогаются;
- ограничение `ck_projects_description_length` (`char_length`, то есть знаки, а не байты)
  держит предел в схеме дальше.

## Номер и `seq` — те же пути, что у кода

`seq` выдаёт `IDENTITY` при вставке — как у любой записи. `no` считается так же, как
`EntryRepository.allocate_project_no`: `max(no) + 1` среди записей проекта. У установки,
обновляемой с v0.3, дело проекта пустое (ревизия `5c1d8e7a2b90` задним числом ничего не
подшивает), и запись получает №1. У базы, которая уже стояла на дереве с делом проекта и
завела в нём записи (демо, атрибуты), номер следующий за последним — дыр и дублей нет.

Сценарий приложения отсюда не вызывается: миграция не зависит от кода, который после неё
изменится, и работает синхронным соединением Alembic. Поэтому повторена его суть: сначала
очередь изменений (`pg_advisory_xact_lock` с ключом `CHANGES_LOCK` из `app/db/locks.py`),
потом строки — порядок `seq` совпадает с порядком фиксации и при живых писателях. Записи
`field_changed` об опустевшем поле нет намеренно: она повторила бы весь длинный текст второй
раз, а объяснение перемены — сама запись «Описание до v0.4.0».

Имена объектов не квалифицированы схемой: приём архива переноса установки гоняет миграции
во временной схеме, и архив v0.3 проходит этот же перенос (`CONCEPT.md`, 5.5).

## Откат

Снимает ограничение и только: записи неизменяемы (триггер `entries_immutable`), удалить
«Описание до v0.4.0» нельзя, а текст из неё обратно в поле не возвращается — повторный
подъём завёл бы тогда вторую такую же запись. Прежняя ревизия принимает и пустое
описание, и заметку в деле проекта, поэтому откат проходит на любых данных.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d2f94c0e15"
down_revision: str | None = "8e4a61c3d2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Предел описания в знаках — `MAX_PROJECT_DESCRIPTION_LENGTH` (`app/domain/projects.py`)
#: на момент ревизии. Литерал: миграция описывает переход, а не нынешнее значение.
MAX_DESCRIPTION_LENGTH = 320

#: Ключ очереди изменений — `CHANGES_LOCK` (`app/db/locks.py`).
CHANGES_LOCK = 0x6A6F75726E616C

#: Заголовок записи с прежним описанием (`CONCEPT.md`, 3.2).
NOTE_TITLE = "Описание до v0.4.0"

#: Имя собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`): `ck_<таблица>_<имя>`.
CONSTRAINT = "ck_projects_description_length"

MOVE_LONG_DESCRIPTIONS = f"""
INSERT INTO entries (
    project_id, no, type, title, body, payload, refs, action_id,
    created_by_kind, created_by_signature
)
SELECT
    projects.id,
    COALESCE((SELECT max(entries.no) FROM entries WHERE entries.project_id = projects.id), 0) + 1,
    'note',
    '{NOTE_TITLE}',
    projects.description,
    '{{}}'::jsonb,
    '[]'::jsonb,
    gen_random_uuid(),
    'tracker',
    NULL
FROM projects
WHERE char_length(projects.description) > {MAX_DESCRIPTION_LENGTH}
ORDER BY projects.key
"""


def upgrade() -> None:
    op.execute(f"SELECT pg_advisory_xact_lock({CHANGES_LOCK})")
    op.execute(MOVE_LONG_DESCRIPTIONS)
    op.execute(
        "UPDATE projects SET description = '', updated_at = now() "
        f"WHERE char_length(description) > {MAX_DESCRIPTION_LENGTH}"
    )
    op.create_check_constraint(
        op.f(CONSTRAINT), "projects", f"char_length(description) <= {MAX_DESCRIPTION_LENGTH}"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "projects", type_="check")
