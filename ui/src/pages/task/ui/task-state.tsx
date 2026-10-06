import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { StatusMark, type TaskState } from '@/entities/task';
import { RelativeTime } from '@/shared/ui';

interface TaskStateBlockProps {
  /** Блок `state` пакета: где задача стоит сейчас, считает бэкенд при каждом чтении (TRK-579). */
  state: TaskState;
  taskKey: string;
}

/** Ячейка блока: подпись над значением, как в полосе свойств шапки. */
const CELL = 'flex min-w-0 flex-col gap-1';
const LABEL = 'text-label text-muted';
/** Номера записей, ключи и строки записей — ключи контракта: моноширинным и без разрыва. */
const MONO = 'font-mono text-mark';

/**
 * Блок «Сейчас» под шапкой карточки (TRK-579, `../docs/CONCEPT.md`, 4.2): статус и причина
 * последнего перехода, следующий шаг сводки, что подшито после неё, чьего ответа ждём,
 * блокеры и дети. Человек его не редактирует: блок считается из дела и связей, и влиять на
 * него можно тем же, чем всегда, — ответом и замечанием. Открытые вопросы и замечания
 * здесь названы строкой, а целиком лежат ниже в своих блоках: дважды их не показываем.
 */
export function TaskStateBlock({ state, taskKey }: TaskStateBlockProps) {
  const { t } = useTranslation('task');
  const { last_transition: move, last_summary: summary } = state;
  const counts = Object.entries(state.children);

  return (
    <section
      className="flex flex-col gap-3 rounded-mark border border-line p-3"
      aria-labelledby="now"
    >
      <h2 className="text-screen" id="now">
        {t('state.title')}
      </h2>

      <dl className="flex flex-col gap-3 text-meta">
        <div className={CELL}>
          <dt className={LABEL}>{t('state.lastMove')}</dt>
          <dd className="flex flex-col gap-1">
            {move === null ? (
              <span className="text-muted italic">{t('state.noMove')}</span>
            ) : (
              <>
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  {move.from_status === null ? null : (
                    <>
                      <StatusMark status={move.from_status} labelled={false} />
                      <span className="text-faint" aria-hidden="true">
                        →
                      </span>
                    </>
                  )}
                  <StatusMark status={move.to_status} labelled={false} />
                  <span className="text-muted">
                    {t('state.by', { name: move.by })} · <RelativeTime value={move.at} />
                  </span>
                </span>
                {move.reason === null ? null : <span className="wrap-anywhere">{move.reason}</span>}
              </>
            )}
          </dd>
        </div>

        {summary === null ? null : (
          <>
            <div className={CELL}>
              <dt className={LABEL}>{t('state.nextStep')}</dt>
              <dd className="wrap-anywhere">{summary.next_step}</dd>
            </div>
            <div className={CELL}>
              <dt className={LABEL}>{t('state.inTheWay')}</dt>
              <dd className="wrap-anywhere">{summary.blockers}</dd>
            </div>
            {summary.unmeasured === null ? null : (
              <div className={CELL}>
                <dt className={LABEL}>{t('state.unmeasured')}</dt>
                <dd className="wrap-anywhere">{summary.unmeasured}</dd>
              </div>
            )}
          </>
        )}

        {state.questions.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('state.waitingFor')}</dt>
            <dd>
              <ul className="flex list-none flex-col gap-1 p-0">
                {state.questions.map((question) => (
                  <li key={question.no} className="wrap-anywhere" data-blocking={question.blocking}>
                    <span className={MONO}>
                      {taskKey}#{question.no}
                    </span>{' '}
                    {question.title}{' '}
                    <span className="text-muted">
                      → {question.to.join(', ')}
                      {question.blocking ? ` · ${t('state.blocking')}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        ) : null}

        {state.blockers.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('state.blockedBy')}</dt>
            <dd className="flex flex-wrap gap-x-3 gap-y-1">
              {state.blockers.map((key) => (
                <Link key={key} to={`/tasks/${key}`} className={`${MONO} whitespace-nowrap`}>
                  {key}
                </Link>
              ))}
            </dd>
          </div>
        ) : null}

        {counts.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('state.children')}</dt>
            <dd className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {counts.map(([status, count]) => (
                <span key={status} className="inline-flex items-center gap-1.5">
                  <StatusMark status={status} labelled={false} />
                  <span className="text-muted">{count}</span>
                </span>
              ))}
              {state.children_unclosed.map((key) => (
                <Link key={key} to={`/tasks/${key}`} className={`${MONO} whitespace-nowrap`}>
                  {key}
                </Link>
              ))}
            </dd>
          </div>
        ) : null}

        <div className={CELL}>
          <dt className={LABEL}>
            {state.after_summary === null
              ? t('state.recentNoSummary', { count: state.recent_total })
              : t('state.recentAfterSummary', {
                  count: state.recent_total,
                  no: state.after_summary,
                })}
          </dt>
          <dd>
            {state.recent.length === 0 ? (
              <span className="text-muted italic">{t('state.nothingNew')}</span>
            ) : (
              <ul className="flex list-none flex-col gap-1 p-0">
                {state.recent.map((line) => (
                  <li key={line} className={`${MONO} wrap-anywhere`}>
                    {line}
                  </li>
                ))}
                {state.recent_total > state.recent.length ? (
                  <li className="text-muted">
                    {t('state.more', { count: state.recent_total - state.recent.length })}
                  </li>
                ) : null}
              </ul>
            )}
          </dd>
        </div>

        {state.decisions_after_card.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('state.decisionsAfterCard')}</dt>
            <dd className={`${MONO} flex flex-wrap gap-x-3`}>
              {state.decisions_after_card.map((no) => (
                <span key={no}>
                  {taskKey}#{no}
                </span>
              ))}
            </dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}
