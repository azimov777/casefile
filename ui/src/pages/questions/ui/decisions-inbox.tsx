import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  parseDecisionRef,
  projectOfDecision,
  unconfirmedDecisionsQueryOptions,
} from '@/entities/decision';
import { decisionTasksQuery } from '@/entities/project';
import { bootstrapQueryOptions } from '@/entities/session';
import { DecisionReviewRow } from '@/features/decisions/review';
import { tasksHref } from '@/features/task-filters';
import { formatNumber } from '@/shared/lib';
import { useLanguage } from '@/shared/i18n';
import { Button, QueryState } from '@/shared/ui';

/** Адрес списка задач, стоящих на решении: закрытые в нём важнее открытых, архив показан. */
function decisionTasksHref(ref: string): string {
  return tasksHref('', { query: decisionTasksQuery(ref), showArchive: true });
}

/**
 * Раздел Входящей «Решения ждут проверки N» (TRK-759): действующие решения всех проектов,
 * которые человек ещё не проверял, старые первыми; с отбором проекта страницы — только его.
 * Строка и четыре действия — те же, что на вкладке «Решения» (`features/decisions/review`),
 * с проектом ссылкой. Проверенная строка уходит из раздела, число перечитывается из
 * `bootstrap`.
 *
 * Число в заголовке — `unconfirmed_decisions` первого кадра: интерфейс за бэкенд не считает.
 * Значок «Входящей» эти решения не прибавляют (TRK-759): их сотни, и значок перестал бы
 * показывать, что агент ждёт ответа. Число видно только здесь.
 */
export function DecisionsInbox({ project }: { project: string }) {
  const { t } = useTranslation('questions');
  const { t: tr } = useTranslation('decisions');
  const listLabel = tr('list');
  const reviewed = tr('row.reviewed');
  const { language } = useLanguage();
  const bootstrap = useQuery(bootstrapQueryOptions());
  const decisions = useInfiniteQuery(unconfirmedDecisionsQueryOptions(project));
  const rows = decisions.data?.pages.flatMap((page) => page.data) ?? [];
  const [notice, setNotice] = useState<string | null>(null);
  const noticeRef = useRef<HTMLParagraphElement>(null);

  // Проверенная строка уходит из раздела и уносит фокус с собой: он идёт на строку состояния.
  useEffect(() => {
    if (notice !== null) noticeRef.current?.focus();
  }, [notice]);

  // Без отбора число — из первого кадра; с проектом — то, что бэкенд насчитал для проекта.
  const count =
    project === ''
      ? (bootstrap.data?.unconfirmed_decisions ?? decisions.data?.pages[0]?.unconfirmed)
      : decisions.data?.pages[0]?.unconfirmed;

  return (
    <section aria-labelledby="decisions-section" className="flex flex-col gap-3">
      <h2 className="text-screen" id="decisions-section">
        {t('decisionsTitle')}
        {count === undefined ? null : (
          <>
            {' '}
            <span className="tabular-nums" data-decisions-count={count}>
              {formatNumber(count, language)}
            </span>
          </>
        )}
      </h2>
      <p className="text-meta text-muted">{t('decisionsIntro')}</p>
      <p
        ref={noticeRef}
        tabIndex={-1}
        role="status"
        className="text-meta text-muted focus-visible:outline-2 focus-visible:outline-focus"
      >
        {notice}
      </p>

      <QueryState
        query={decisions}
        loading={t('loadingDecisions')}
        empty={
          rows.length === 0
            ? project === ''
              ? t('noDecisions')
              : t('noDecisionsProject', { project })
            : undefined
        }
      />

      {rows.length === 0 ? null : (
        <ul
          className="flex list-none flex-col rounded-control border border-line bg-surface p-0"
          aria-label={listLabel}
          aria-busy={decisions.isFetching}
        >
          {rows.map((row) => {
            const place = parseDecisionRef(row.ref);
            return (
              <DecisionReviewRow
                key={row.ref}
                row={row}
                project={place === null ? undefined : projectOfDecision(place)}
                canReview
                tasksHref={decisionTasksHref}
                onReviewed={() => setNotice(reviewed)}
              />
            );
          })}
        </ul>
      )}

      {decisions.hasNextPage ? (
        <Button
          onClick={() => void decisions.fetchNextPage()}
          disabled={decisions.isFetchingNextPage}
        >
          {decisions.isFetchingNextPage ? t('loadingMore') : t('more')}
        </Button>
      ) : null}
    </section>
  );
}
