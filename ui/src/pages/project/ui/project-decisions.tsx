import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { AuthorName } from '@/entities/entry';
import { DecisionStatusMark, decisionTasksQuery, type ProjectDecision } from '@/entities/project';
import { tasksHref } from '@/features/task-filters';
import { RelativeTime } from '@/shared/ui';

/** Блок-список, как атрибуты рядом: строки решений идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним. */
const BLOCK_HEAD = 'flex flex-col gap-1 border-b border-b-line px-3 pt-3 pb-2';

/** Строка решения: поля как у строки атрибута, линия между строками. */
const ROW = 'flex flex-col gap-1 border-b border-b-line px-3 py-2 last:border-b-0';

/** Ссылка на запись решения: ключ контракта моноширинным, целиком на одной строке. */
const REF = 'font-mono whitespace-nowrap';

interface ProjectDecisionsProps {
  projectKey: string;
  /** Все решения проекта по номеру, со статусом от бэкенда (`ProjectDetailRead.decisions`). */
  decisions: ProjectDecision[];
  /**
   * Адрес этого же экрана с раскрытой записью решения в деле ниже (`?entry=N`), с прочим
   * состоянием адреса как было. Тело решения читается там, а не здесь: дело проекта —
   * единственное место, где его показывают.
   */
  entryHref: (no: number) => string;
}

/**
 * Решения проекта (TRK-554, `../docs/CONCEPT.md`, 3.2): записи `decision` дела проекта
 * со статусом, который бэкенд посчитал при чтении.
 *
 * Сверху действующие — то, что по договору задаёт работу агентов. Заменённые свёрнуты
 * ниже, у каждого — чем заменено: история не пропадает, но и не спорит с тем, что
 * действует. Список, а не таблица: описью-таблицей на этом экране остаётся дело проекта,
 * и тело решения раскрывается там же — ссылкой на запись, а не вторым показом рядом.
 *
 * У решения — число задач, которые на него ссылаются, ссылкой на список задач с отбором
 * `decision: TRK#N` и показанным архивом: это обратный путь «что сделано по решению», и
 * закрытые задачи в нём важнее открытых.
 */
export function ProjectDecisions({ projectKey, decisions, entryHref }: ProjectDecisionsProps) {
  const { t } = useTranslation('project');
  const [showSuperseded, setShowSuperseded] = useState(false);
  const supersededId = useId();

  const inForce = decisions.filter((decision) => decision.status === 'in_force');
  const superseded = decisions.filter((decision) => decision.status !== 'in_force');
  const byNo = new Map(decisions.map((decision) => [decision.no, decision]));

  return (
    <section className={LIST_BLOCK} aria-labelledby="project-decisions">
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id="project-decisions">
          {t('decisions.title')}
        </h2>
        <p className="text-meta text-muted">{t('decisions.hint')}</p>
      </div>

      {inForce.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">
          {decisions.length === 0 ? t('decisions.none') : t('decisions.noneInForce')}
        </p>
      ) : (
        <ul className="flex list-none flex-col p-0" aria-label={t('decisions.inForce')}>
          {inForce.map((decision) => (
            <DecisionRow
              key={decision.no}
              projectKey={projectKey}
              decision={decision}
              successor={null}
              entryHref={entryHref}
            />
          ))}
        </ul>
      )}

      {superseded.length === 0 ? null : (
        <div className="flex flex-col border-t border-t-line">
          {/*
           * Заменённые свёрнуты: это история, а не то, что задаёт работу. Раскрытие —
           * кнопка с `aria-expanded`, тот же вид, что у имени атрибута рядом.
           */}
          <button
            type="button"
            className="cursor-pointer border-none bg-transparent px-3 py-2 text-left text-meta text-muted before:content-['▸_'] max-fold:min-h-(--ui-tap) hover:underline aria-expanded:before:content-['▾_']"
            aria-expanded={showSuperseded}
            aria-controls={showSuperseded ? supersededId : undefined}
            onClick={() => setShowSuperseded((open) => !open)}
          >
            {t('decisions.superseded', { count: superseded.length })}
          </button>
          {showSuperseded ? (
            <ul
              id={supersededId}
              className="flex list-none flex-col border-t border-t-line p-0"
              aria-label={t('decisions.supersededList')}
            >
              {superseded.map((decision) => (
                <DecisionRow
                  key={decision.no}
                  projectKey={projectKey}
                  decision={decision}
                  successor={
                    decision.superseded_by == null
                      ? null
                      : (byNo.get(decision.superseded_by) ?? null)
                  }
                  entryHref={entryHref}
                />
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </section>
  );
}

/**
 * Одно решение: адрес записи, само решение одной фразой и статус; под ними — кто и когда
 * принял, что заменило, чем заменено и сколько задач по нему сделано.
 */
function DecisionRow({
  projectKey,
  decision,
  successor,
  entryHref,
}: {
  projectKey: string;
  decision: ProjectDecision;
  /** Решение, заменившее это; `null` у действующего. */
  successor: ProjectDecision | null;
  entryHref: (no: number) => string;
}) {
  const { t } = useTranslation('project');
  const superseded = decision.status !== 'in_force';

  return (
    <li className={ROW} data-decision={decision.ref} data-status={decision.status}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Link to={entryHref(decision.no)} className={REF}>
          {decision.ref}
        </Link>
        <DecisionStatusMark status={decision.status} />
      </div>
      {/* Заменённое зачёркнуто: решение больше не задаёт работу, но читается целиком. */}
      <p className={superseded ? 'text-muted line-through wrap-anywhere' : 'wrap-anywhere'}>
        {decision.title}
      </p>
      {successor === null ? null : (
        <p className="text-meta wrap-anywhere">
          {t('decisions.supersededBy')}{' '}
          <Link to={entryHref(successor.no)} className={REF}>
            {successor.ref}
          </Link>{' '}
          {successor.title}
        </p>
      )}
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-meta text-muted">
        <AuthorName author={decision.author} />
        <RelativeTime value={decision.created_at} />
        {decision.supersedes.length === 0 ? null : (
          <span>
            {t('decisions.replaces')}{' '}
            {decision.supersedes.map((no, index) => (
              <span key={no}>
                {index === 0 ? null : ', '}
                <Link to={entryHref(no)} className={REF}>
                  {`${projectKey}#${no}`}
                </Link>
              </span>
            ))}
          </span>
        )}
        {decision.tasks === 0 ? (
          <span>{t('decisions.noTasks')}</span>
        ) : (
          <Link to={tasksHref('', { query: decisionTasksQuery(decision.ref), showArchive: true })}>
            {t('decisions.tasks', { count: decision.tasks })}
          </Link>
        )}
      </p>
    </li>
  );
}
