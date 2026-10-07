import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import {
  DiscussionRow,
  discussionHistoryQueryOptions,
  inboxDiscussionsQueryOptions,
} from '@/entities/discussion';
import { NewDiscussion } from '@/features/manage-discussion';
import { useProjectRights } from '@/features/manage-project';
import { Button, QueryState } from '@/shared/ui';

/**
 * Обсуждения во входящей (TRK-672, решение проекта `TRK#51`, п. 8): незакрытые, где ход за
 * человеком, давнишние первыми, с числом вопросов без ответа. Строка — ссылка на экран
 * обсуждения: отвечают там, где видна вся переписка и итог, а не из списка.
 *
 * «Новое обсуждение» стоит в шапке раздела: человек заводит обсуждение запиской, закрыть
 * его он не может, и кнопки закрытия нет нигде.
 */
export function DiscussionsInbox({ project }: { project: string }) {
  const discussions = useInfiniteQuery(inboxDiscussionsQueryOptions(project));
  const items = discussions.data?.pages.flatMap((page) => page.items) ?? [];
  const rights = useProjectRights();
  const { t } = useTranslation('discussions');
  const { t: brick } = useTranslation('questions');

  return (
    <section aria-labelledby="discussions-section" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-screen" id="discussions-section">
          {t('inbox.title')}
        </h2>
        {rights.write ? <NewDiscussion project={project} /> : null}
      </div>
      <p className="m-0 text-meta text-muted">{t('inbox.intro')}</p>

      <QueryState
        query={discussions}
        loading={t('inbox.loading')}
        empty={
          items.length === 0
            ? project === ''
              ? t('inbox.none')
              : t('inbox.noneByProject', { project })
            : undefined
        }
      />

      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {items.map((discussion) => (
          <li key={discussion.address}>
            <DiscussionRow discussion={discussion} />
          </li>
        ))}
      </ul>

      {discussions.hasNextPage ? (
        <Button
          onClick={() => void discussions.fetchNextPage()}
          disabled={discussions.isFetchingNextPage}
        >
          {discussions.isFetchingNextPage ? brick('loadingMore') : brick('more')}
        </Button>
      ) : null}
    </section>
  );
}

/** История обсуждений: все, открытые и закрытые, от свежих к старым. Только чтение. */
export function DiscussionsHistory({ project }: { project: string }) {
  const history = useInfiniteQuery(discussionHistoryQueryOptions(project));
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];
  const { t } = useTranslation('discussions');
  const { t: brick } = useTranslation('questions');

  return (
    <section aria-labelledby="discussions-history-section" className="flex flex-col gap-3">
      <h2 className="text-screen" id="discussions-history-section">
        {t('history.title')}
      </h2>

      <QueryState
        query={history}
        loading={t('history.loading')}
        empty={
          items.length === 0
            ? project === ''
              ? t('history.none')
              : t('history.noneByProject', { project })
            : undefined
        }
      />

      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {items.map((discussion) => (
          <li key={discussion.address}>
            <DiscussionRow discussion={discussion} />
          </li>
        ))}
      </ul>

      {history.hasNextPage ? (
        <Button onClick={() => void history.fetchNextPage()} disabled={history.isFetchingNextPage}>
          {history.isFetchingNextPage ? brick('loadingMore') : brick('more')}
        </Button>
      ) : null}
    </section>
  );
}
