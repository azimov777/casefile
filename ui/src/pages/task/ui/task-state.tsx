import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { StatusMark, type TaskState } from '@/entities/task';
import { cn } from '@/shared/lib';
import { RelativeTime } from '@/shared/ui';

interface TaskStateBlockProps {
  /** Блок `state` пакета: где задача стоит сейчас, считает бэкенд при каждом чтении (TRK-579). */
  state: TaskState;
  taskKey: string;
  /** Место блока в раскладке страницы: решает экран, а не блок. */
  className?: string;
}

/** Ячейка блока: подпись над значением, как в полосе свойств шапки. */
const CELL = 'flex min-w-0 flex-col gap-1';
const LABEL = 'text-label text-muted';
/** Ключи задач и номера записей — ключи контракта: моноширинным и без разрыва. */
const MONO = 'font-mono text-mark whitespace-nowrap';

/**
 * Блок «Сейчас» под шапкой карточки (TRK-579, TRK#154): статус и причина
 * последнего перехода, сколько записей подшито после сводки, блокеры, дети и решения,
 * принятые после правки задания. Человек его не редактирует: блок считается из дела и
 * связей, и влиять на него можно тем же, чем всегда, — ответом и замечанием.
 *
 * Агенту блок отдаёт ещё `next_step` и части сводки, открытые вопросы, строки записей
 * после сводки. Здесь их нет намеренно: сводка и вопросы стоят ниже целиком в своих
 * блоках, а записи — в описи, и дважды одно и то же на первом экране — это место, которое
 * `e2e/layout.spec.ts` отдаёт сводке и вопросам.
 */
export function TaskStateBlock({ state, taskKey, className }: TaskStateBlockProps) {
  const { t } = useTranslation('task');
  const { last_transition: move } = state;
  const counts = Object.entries(state.children);

  return (
    <section
      className={cn('flex flex-col gap-2 rounded-mark border border-line px-3 py-2', className)}
      aria-labelledby="now"
    >
      <h2 className="text-screen" id="now">
        {t('state.title')}
      </h2>

      <dl className="flex flex-wrap items-start gap-x-8 gap-y-3 text-meta">
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
                    {t('state.by')} <span className={MONO}>{move.by}</span> ·{' '}
                    <RelativeTime value={move.at} />
                  </span>
                </span>
                {move.reason === null ? null : <span className="wrap-anywhere">{move.reason}</span>}
              </>
            )}
          </dd>
        </div>

        <div className={CELL}>
          <dt className={LABEL}>{t('state.filed')}</dt>
          <dd>
            {state.after_summary === null
              ? t('state.recentNoSummary', { count: state.recent_total })
              : t('state.recentAfterSummary', {
                  count: state.recent_total,
                  no: state.after_summary,
                })}
          </dd>
        </div>

        {state.blockers.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('state.blockedBy')}</dt>
            <dd className="flex flex-wrap gap-x-3 gap-y-1">
              {state.blockers.map((key) => (
                <Link key={key} to={`/tasks/${key}`} className={MONO}>
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
                <Link key={key} to={`/tasks/${key}`} className={MONO}>
                  {key}
                </Link>
              ))}
            </dd>
          </div>
        ) : null}

        {state.decisions_after_card.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('state.decisionsAfterCard')}</dt>
            <dd className="flex flex-wrap gap-x-3">
              {state.decisions_after_card.map((no) => (
                <span key={no} className={MONO}>
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
