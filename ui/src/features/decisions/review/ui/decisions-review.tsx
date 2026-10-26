import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { decisionsQueryOptions, parseDecisionRef, type DecisionRow } from '@/entities/decision';
import { useLanguage } from '@/shared/i18n';
import { formatNumber } from '@/shared/lib';
import { QueryState, SegmentedNav, SegmentedNavLink } from '@/shared/ui';
import { groupDecisions, readFilter, withFilter, type DecisionFilter } from '../model/filter';
import { DecisionReviewRow } from './decision-row';

const FILTERS: readonly DecisionFilter[] = ['inforce', 'unconfirmed', 'removed'];

interface DecisionsReviewProps {
  /** Ключ проекта: его решения и решения его областей. */
  project: string;
  /** Адрес области: из решений проекта остаются только её собственные (страница области). */
  area?: string;
  /**
   * Номера решений, которые нашёл поиск бэкенда по тексту (`?q=` страницы области); `null` —
   * поиска нет. Отбор по номерам, а не по тексту: что подходит, решает бэкенд.
   */
  matches?: ReadonlySet<number> | null;
  /** Показывать ли действия проверки: архивный проект только читается. */
  canReview: boolean;
  tasksHref: (ref: string) => string;
}

/**
 * Список решений с отбором и проверкой (TRK-758): «Действующие», «Не подтверждены» и
 * «Показать снятые» — заменённые, отклонённые, удалённые. Отбор живёт в адресе (`?show=`),
 * переключатель — ссылки, как вкладки (`TRK/ui-list#17`).
 *
 * Читает `GET /api/v1/decisions?project=` — решения проекта и всех его областей разом;
 * страница области оставляет свои. Раскладку по отборам даёт `groupDecisions` по готовым
 * полям строк, а не по своим правилам. Блока-обёртки и заголовка здесь нет: их ставит экран,
 * чтобы список встал и в «Решения» проекта, и во вкладку области, и во Входящую.
 */
export function DecisionsReview({
  project,
  area,
  matches = null,
  canReview,
  tasksHref,
}: DecisionsReviewProps) {
  const { t } = useTranslation('decisions');
  const { language } = useLanguage();
  const [search] = useSearchParams();
  const decisions = useQuery(decisionsQueryOptions(project));
  const [notice, setNotice] = useState<string | null>(null);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  const filter = readFilter(search);

  // Проверенная строка уходит из отбора и уносит фокус с собой: он идёт на строку состояния.
  useEffect(() => {
    if (notice !== null) noticeRef.current?.focus();
  }, [notice]);

  if (decisions.data === undefined) {
    return (
      <div className="px-3 py-2">
        <QueryState query={decisions} loading={t('loading')} />
      </div>
    );
  }

  const rows = decisions.data.rows.filter((row) => keeps(row, area, matches));
  const groups = groupDecisions(rows);
  const shown =
    filter === 'unconfirmed'
      ? groups.unconfirmed
      : filter === 'removed'
        ? groups.removed
        : groups.inForce;
  const counts: Record<DecisionFilter, number> = {
    inforce: groups.inForce.length,
    unconfirmed: groups.unconfirmed.length,
    removed: groups.removed.length,
  };

  return (
    <>
      <div className="flex flex-col gap-2 border-b border-b-line px-3 py-2">
        <div className="max-w-full overflow-x-auto p-1 -m-1">
          <SegmentedNav label={t('filter.label')} size="sm" className="w-max">
            {FILTERS.map((option) => (
              <SegmentedNavLink
                key={option}
                to={{ search: `?${withFilter(search, option).toString()}` }}
                current={option === filter ? 'true' : false}
                data-filter={option}
              >
                <span className="whitespace-nowrap">
                  {t(`filter.${option === 'inforce' ? 'inForce' : option}`)}{' '}
                  <span className="font-normal text-muted tabular-nums">
                    {formatNumber(counts[option], language)}
                  </span>
                </span>
              </SegmentedNavLink>
            ))}
          </SegmentedNav>
        </div>
        <p
          ref={noticeRef}
          tabIndex={-1}
          role="status"
          className="text-meta text-muted focus-visible:outline-2 focus-visible:outline-focus"
        >
          {notice}
        </p>
      </div>

      {shown.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">
          {t(
            matches !== null
              ? 'empty.noMatch'
              : `empty.${filter === 'inforce' ? 'inForce' : filter}`,
          )}
        </p>
      ) : (
        <ul
          className="flex list-none flex-col p-0"
          aria-label={t('list')}
          aria-busy={decisions.isFetching}
          data-filter-shown={filter}
        >
          {shown.map((row) => (
            <DecisionReviewRow
              key={row.ref}
              row={row}
              canReview={canReview}
              tasksHref={tasksHref}
              onReviewed={() => setNotice(t('row.reviewed'))}
            />
          ))}
        </ul>
      )}
    </>
  );
}

/** Нужна ли строка этому экрану: решения одной области и найденные поиском. */
function keeps(row: DecisionRow, area: string | undefined, matches: ReadonlySet<number> | null) {
  if (area !== undefined && row.area !== area) return false;
  if (matches === null) return true;
  const place = parseDecisionRef(row.ref);
  return place !== null && matches.has(place.no);
}
