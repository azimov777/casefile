import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { discussionHref } from '@/shared/lib';
import { RelativeTime } from '@/shared/ui';
import type { Discussion } from '../api/discussions';
import { TurnMark } from './turn-mark';

/**
 * Обсуждение строкой: адрес, название, чей ход, число вопросов без ответа и когда
 * в нём писали в последний раз. Вся строка — ссылка на экран обсуждения: ради этого
 * шага человек во входящую и приходит.
 */
export function DiscussionRow({ discussion }: { discussion: Discussion }) {
  const { t } = useTranslation('discussions');

  return (
    <article
      className="flex flex-col gap-2 rounded-control border border-line bg-surface p-3"
      aria-label={t('row.label', { address: discussion.address })}
      data-discussion={discussion.address}
    >
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        <Link className="font-mono whitespace-nowrap" to={discussionHref(discussion.address)}>
          {discussion.address}
        </Link>
        <TurnMark status={discussion.status} turn={discussion.turn} />
        {discussion.open_questions > 0 ? (
          <span className="text-attention">
            {t('row.openQuestions', { count: discussion.open_questions })}
          </span>
        ) : null}
        <RelativeTime value={discussion.closed_at ?? discussion.updated_at} />
      </header>
      <h3 className="text-screen wrap-anywhere">
        <Link
          className="text-text no-underline hover:underline"
          to={discussionHref(discussion.address)}
        >
          {discussion.title}
        </Link>
      </h3>
    </article>
  );
}
