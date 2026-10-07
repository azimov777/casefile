import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, type To } from 'react-router';
import { useInfiniteQuery } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import { DirectionLink } from '@/entities/direction';
import {
  EntryHeadline,
  EntryKind,
  entryHeadline,
  headingOfEntry,
  holderCaseQueryOptions,
} from '@/entities/entry';
import type { ProjectDecision, ProjectDetail } from '@/entities/project';
import type { HolderTab } from '@/features/manage-project';
import { QueryState, RelativeTime } from '@/shared/ui';

/** Блок-список, как разделы вкладок: строки идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним. */
const BLOCK_HEAD = 'border-b border-b-line px-3 pt-3 pb-2';

/** Строка блока: одна строка на столе, перенос на телефоне; линия между строками. */
const ROW =
  'flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-b-line px-3 py-2 last:border-b-0';

/** Последних решений на «Обзоре» (TRK-606#10, п. 3). */
const LATEST_DECISIONS = 3;

/** Последних записей дела на «Обзоре» (TRK-606#10, п. 3). */
const LATEST_ENTRIES = 5;

interface ProjectOverviewProps {
  projectKey: string;
  /** Активные направления из карточки проекта: адрес и название. */
  directions: ProjectDetail['directions'];
  /** Все решения проекта из карточки, со статусом от бэкенда. */
  decisions: ProjectDecision[];
  /** Адрес «Дела» с раскрытой записью — туда ведут решения и строки дела. */
  entryHref: (no: number) => To;
  tabHref: (tab: HolderTab) => To;
}

/**
 * Вкладка «Обзор» экрана проекта (TRK-618, решение TRK#46): направления, свежее по
 * решениям и по делу — то, что человек читает на каждом заходе, примерно на один экран.
 * Подробности — на своих вкладках, сюда они приходят ссылками «Все N решений» и
 * «Всё дело». Рост числа решений и записей «Обзор» не удлиняет.
 */
export function ProjectOverview({
  projectKey,
  directions,
  decisions,
  entryHref,
  tabHref,
}: ProjectOverviewProps) {
  return (
    <div className="flex flex-col gap-4">
      {/* Две колонки на точке `card`: направления — короткие строки, решения — с
          названием во всю оставшуюся ширину. На узком экране — одна колонка. */}
      <div className="flex flex-col gap-4 card:flex-row card:items-start">
        <div className="flex flex-col card:min-w-0 card:flex-[2_1_0]">
          <OverviewDirections directions={directions} />
        </div>
        <div className="flex flex-col card:min-w-0 card:flex-[3_1_0]">
          <LatestDecisions decisions={decisions} entryHref={entryHref} tabHref={tabHref} />
        </div>
      </div>
      <LatestEntries projectKey={projectKey} entryHref={entryHref} tabHref={tabHref} />
    </div>
  );
}

/** Блок «Обзора» с заголовком: раздел, названный своим заголовком для диктора. */
function OverviewBlock({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className={LIST_BLOCK} aria-labelledby={id}>
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id={id}>
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

/** Ссылка «Все N решений →» или «Всё дело →» под списком блока. */
function MoreLink({ to, children }: { to: To; children: ReactNode }) {
  return (
    <div className="border-t border-t-line px-3 py-2">
      <Link to={to} className="inline-flex items-center gap-1 text-meta">
        {children}
        <ArrowRight className="size-(--ui-mark)" aria-hidden="true" />
      </Link>
    </div>
  );
}

/** Направления проекта списком: название ссылкой на страницу направления и адрес. */
function OverviewDirections({ directions }: { directions: ProjectDetail['directions'] }) {
  const { t } = useTranslation('project');

  return (
    <OverviewBlock id="overview-directions" title={t('overview.directions')}>
      {directions.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">{t('overview.directionsNone')}</p>
      ) : (
        <ul className="flex list-none flex-col p-0">
          {directions.map((direction) => (
            <li key={direction.address} className={ROW} data-overview-direction={direction.address}>
              <DirectionLink
                address={direction.address}
                title={direction.title}
                className="font-semibold"
              />
              <span className="font-mono text-meta whitespace-nowrap text-muted">
                {direction.address}
              </span>
            </li>
          ))}
        </ul>
      )}
    </OverviewBlock>
  );
}

/**
 * Три последних действующих решения — по номеру записи, сверху новое: ключ ссылкой на
 * запись в «Деле», название и время. Заменённые здесь не показываются: «Обзор» отвечает
 * на «что решено сейчас», история — на вкладке «Решения».
 */
function LatestDecisions({
  decisions,
  entryHref,
  tabHref,
}: {
  decisions: ProjectDecision[];
  entryHref: (no: number) => To;
  tabHref: (tab: HolderTab) => To;
}) {
  const { t } = useTranslation('project');
  const inForce = decisions.filter((decision) => decision.status === 'in_force');
  const latest = [...inForce].sort((a, b) => b.no - a.no).slice(0, LATEST_DECISIONS);

  return (
    <OverviewBlock id="overview-decisions" title={t('overview.decisions')}>
      {latest.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">
          {decisions.length === 0 ? t('decisions.none') : t('decisions.noneInForce')}
        </p>
      ) : (
        <>
          <ul className="flex list-none flex-col p-0">
            {latest.map((decision) => (
              <li key={decision.no} className={ROW} data-overview-decision={decision.ref}>
                <Link to={entryHref(decision.no)} className="font-mono whitespace-nowrap">
                  {decision.ref}
                </Link>
                <span className="min-w-0 flex-1 basis-48 wrap-anywhere">{decision.title}</span>
                <span className="ml-auto text-meta whitespace-nowrap text-muted">
                  <RelativeTime value={decision.created_at} />
                </span>
              </li>
            ))}
          </ul>
          <MoreLink to={tabHref('decisions')}>
            {t('overview.allDecisions', { count: inForce.length })}
          </MoreLink>
        </>
      )}
    </OverviewBlock>
  );
}

/**
 * Пять последних записей дела строками описи: номер, род, заголовок ссылкой и время,
 * сверху новое. Нажатие ведёт в «Дело» с раскрытой записью (`?entry=N`) — там её тело.
 *
 * Дело читается тем же запросом, что и вкладка «Дело» (`holderCaseQueryOptions`): кэш
 * один, переход на вкладку второго запроса не делает. Бэкенд отдаёт дело по возрастанию
 * номера страницами по 200, обратного порядка у него нет, поэтому хвост — после
 * последней страницы: пока они есть, блок дочитывает их сам. Дело проекта короткое, и
 * обычно это одна страница; без дочитывания «последние» у дела длиннее страницы были бы
 * последними из первых двухсот — то есть неправдой.
 */
function LatestEntries({
  projectKey,
  entryHref,
  tabHref,
}: {
  projectKey: string;
  entryHref: (no: number) => To;
  tabHref: (tab: HolderTab) => To;
}) {
  const { t } = useTranslation('project');
  const { t: brick } = useTranslation('ui');
  const feed = useInfiniteQuery(holderCaseQueryOptions({ kind: 'project', key: projectKey }));
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = feed;

  useEffect(() => {
    // Отказ следующей страницы не повторяется сам: иначе отказ крутился бы по кругу.
    if (hasNextPage && !isFetchingNextPage && !isFetchNextPageError) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage]);

  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const latest = entries.slice(-LATEST_ENTRIES).reverse().map(headingOfEntry);

  return (
    <OverviewBlock id="overview-case" title={t('overview.case')}>
      {feed.data === undefined || (hasNextPage && feed.error !== null) ? (
        <div className="px-3 py-2">
          <QueryState query={feed} loading={t('caseLoading')} />
        </div>
      ) : hasNextPage ? (
        <p className="px-3 py-2 text-muted">{t('caseLoading')}</p>
      ) : latest.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">{t('overview.caseNone')}</p>
      ) : (
        <>
          <ul className="flex list-none flex-col p-0">
            {latest.map((heading) => {
              const headline = entryHeadline(heading.facts, projectKey, brick);
              return (
                <li key={heading.no} className={ROW} data-overview-entry={heading.no}>
                  <span className="font-mono text-muted">{heading.no}</span>
                  <EntryKind type={heading.type} />
                  <Link
                    to={entryHref(heading.no)}
                    className="min-w-0 flex-1 basis-48 wrap-anywhere"
                  >
                    {headline.kind === 'built' ? (
                      <EntryHeadline headline={headline} linked={false} />
                    ) : (
                      heading.title
                    )}
                  </Link>
                  <span className="ml-auto text-meta whitespace-nowrap text-muted">
                    <RelativeTime value={heading.created_at} />
                  </span>
                </li>
              );
            })}
          </ul>
          <MoreLink to={tabHref('case')}>{t('overview.allCase')}</MoreLink>
        </>
      )}
    </OverviewBlock>
  );
}
