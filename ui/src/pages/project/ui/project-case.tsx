import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import { EntryIndex, headingOfEntry, projectCaseQueryOptions } from '@/entities/entry';
import { Button, QueryState } from '@/shared/ui';

/** Блок-список: без своих полей, строки описи идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним — у него, у блока их нет. */
const BLOCK_HEAD = 'flex flex-wrap items-baseline gap-3 border-b border-b-line px-3 pt-3 pb-2';

interface ProjectCaseProps {
  projectKey: string;
  /** Раскрытая запись из адреса (`?entry=N`): ссылка `TRK#7` приходит сюда. */
  openAt: number | null;
  onOpenChange: (no: number | null) => void;
}

/**
 * Дело проекта описью: та же `EntryIndex`, что у карточки задачи, с владельцем-проектом.
 *
 * Описи в ответе проекта нет — строки собираются из записей дела (`headingOfEntry`), а
 * тело по клику читается отдельно адресом записи, как у задачи: опись не обещает, что
 * тело уже в памяти, и держать два пути к одному телу незачем.
 */
export function ProjectCase({ projectKey, openAt, onOpenChange }: ProjectCaseProps) {
  const feed = useInfiniteQuery(projectCaseQueryOptions(projectKey));
  const { t } = useTranslation('project');
  const { t: brick } = useTranslation('ui');

  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const index = entries.map(headingOfEntry);

  return (
    <section className={LIST_BLOCK} aria-labelledby="project-case">
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id="project-case">
          {t('case')}
        </h2>
        {/* Число — только у дочитанного дела: у недочитанного оно было бы числом
            подгруженных страниц, а не записей, и врало бы тихо. */}
        {feed.data !== undefined && !feed.hasNextPage && index.length > 0 ? (
          <span className="text-meta text-muted">
            {brick('index.count', { count: index.length })}
          </span>
        ) : null}
      </div>

      {feed.data === undefined ? (
        <div className="px-3 py-2">
          <QueryState query={feed} loading={t('caseLoading')} />
        </div>
      ) : (
        <>
          <EntryIndex
            owner={{ kind: 'project', key: projectKey }}
            index={index}
            openAt={openAt}
            onOpenChange={onOpenChange}
          />
          {feed.hasNextPage ? (
            <div className="px-3 py-2">
              <Button
                tone="quiet"
                size="sm"
                onClick={() => void feed.fetchNextPage()}
                disabled={feed.isFetchingNextPage}
              >
                {feed.isFetchingNextPage ? t('loadingMore') : t('more')}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
