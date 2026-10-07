"""withdraw open task questions

Revision ID: 3b9f4d192289
Revises: 5d0c8e3a71b4
Create Date: 2026-10-07 23:30:00.000000+00:00

Вопросы человеку переехали в обсуждения (решение проекта `TRK#51`, п. 6; TRK-671): новый
вопрос в деле задачи трекер не принимает. Вопрос, открытый в деле задачи на момент
выпуска, ответа там уже не дождётся — человек отвечает в обсуждениях, — а держит признаки
`open_questions` и, с `blocking`, вход задачи в работу. Поэтому каждый такой вопрос
закрывается записью `answer` с исходом `withdrawn` от трекера и телом из решения
владельца (TRK-667#17, п. 2): агент, взявший задачу следующим, переспрашивает через
обсуждение.

Открытый вопрос — `question` в деле задачи без единой записи `answer` с его номером в той
же задаче: то же правило, что у выдачи (`app/db/repositories/entries.py`, `_unanswered`).
Отвеченные, снятые и заменённые вопросы, их ответы и ссылки на них (`refs`) не меняются.
Закрываются вопросы любых задач — закрытых и архивных проектов тоже: заморозка архива —
правило сценариев, а не схемы (как у снятия `waiting`, ревизия `a9cb1ec147c4`), а
открытый вопрос держал бы признак и там.

## Как у кода, но без кода

Сценарий ответа отсюда не вызывается: миграция не зависит от кода приложения, который
меняется дальше. Повторена его суть — запись той же формы, что подшивает `answer`:
заголовок `Answer to TRK-42#3: withdrawn` (`app/domain/case.py`, `_derive_title`, с
нынешним ключом задачи), нагрузка `question_no`, `outcome: withdrawn`, `replaced_by: null`,
автор рода `tracker` без подписи, свой `action_id` у каждой записи. Сначала очередь
изменений (`pg_advisory_xact_lock` с ключом `CHANGES_LOCK` из `app/db/locks.py`); номер —
`max(no)` записей задачи плюс порядковый номер вопроса среди её открытых: у задачи бывает
несколько открытых вопросов, и `max(no) + 1` на каждую строку одной вставки выдал бы им
один номер. `seq` выдаёт `IDENTITY`. Карточку задачи (`version`, `updated_at`) запись
ответа не трогает — как и ответ, подшитый сценарием.

Имена не квалифицированы схемой: приём архива переноса установки гоняет миграции во
временной схеме (`CONCEPT.md`, 5.5), и архив прежней версии с открытыми вопросами
проходит это же закрытие.

## Откат

Ничего не делает: дело неизменяемо (`CONCEPT.md`, 3.4), а снятие вопроса — такая же
страница дела, как любая другая. Откат схемы историю не отменяет.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b9f4d192289"
down_revision: str | None = "5d0c8e3a71b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Ключ очереди изменений — `CHANGES_LOCK` (`app/db/locks.py`).
CHANGES_LOCK = 0x6A6F75726E616C

#: Тело записи снятия — дословно из решения владельца (TRK-667#17, п. 2; TRK#51, п. 6).
BODY = (
    "Вопрос закрыт: вопросы теперь задаются в обсуждениях. Агенту — переспросить через обсуждение."
)

WITHDRAW_OPEN_QUESTIONS = """
INSERT INTO entries (
    task_id, no, type, title, body, payload, refs, action_id,
    created_by_kind, created_by_signature
)
SELECT
    open_questions.task_id,
    open_questions.last_no + open_questions.position,
    'answer',
    'Answer to ' || open_questions.task_key || '#' || open_questions.question_no
        || ': withdrawn',
    CAST(:body AS text),
    jsonb_build_object(
        'question_no', open_questions.question_no,
        'outcome', 'withdrawn',
        'replaced_by', NULL
    ),
    '[]'::jsonb,
    gen_random_uuid(),
    'tracker',
    NULL
FROM (
    SELECT
        question.task_id,
        question.no AS question_no,
        tasks.key AS task_key,
        (SELECT max(other.no) FROM entries AS other WHERE other.task_id = question.task_id)
            AS last_no,
        row_number() OVER (PARTITION BY question.task_id ORDER BY question.no) AS position
    FROM entries AS question
    JOIN tasks ON tasks.id = question.task_id
    WHERE question.type = 'question'
      AND question.task_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM entries AS reply
          WHERE reply.task_id = question.task_id
            AND reply.type = 'answer'
            AND (reply.payload ->> 'question_no')::integer = question.no
      )
) AS open_questions
ORDER BY open_questions.task_key, open_questions.question_no
"""


def upgrade() -> None:
    op.execute(f"SELECT pg_advisory_xact_lock({CHANGES_LOCK})")
    # Тело едет параметром, а не подстановкой в текст: русский текст в литерале SQL —
    # заявка на сломанный запрос при первой же правке.
    op.execute(sa.text(WITHDRAW_OPEN_QUESTIONS).bindparams(body=BODY))


def downgrade() -> None:
    """Ничего не делает: подшитые ответы — страницы неизменяемого дела (см. шапку)."""
