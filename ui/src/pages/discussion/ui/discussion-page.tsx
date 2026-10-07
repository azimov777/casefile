import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  discussionFeedQueryOptions,
  discussionQueryOptions,
  TurnMark,
  type DiscussionDetail,
} from '@/entities/discussion';
import { StatusMark } from '@/entities/task';
import { AttachTaskForm, DetachTaskButton, NoteForm } from '@/features/manage-discussion';
import { useProjectRights } from '@/features/manage-project';
import { ApiError } from '@/shared/api';
import { useLanguage } from '@/shared/i18n';
import { exactTime, readEntryNo } from '@/shared/lib';
import { Button, Callout, QueryState, RelativeTime } from '@/shared/ui';
import { ConclusionBox } from './conclusion-box';
import { Thread } from './thread';

/** Отказы, после которых обсуждения по этому адресу нет. */
const MISSING: readonly string[] = [
  'discussion_not_found',
  'project_not_found',
  'invalid_discussion_address',
];

/**
 * Предел ширины экрана — мера чтения переписки, как у ленты дела (`pages/case`): длинная
 * строка в переписке читается хуже, чем в таблице, и на 1440 она не должна растягиваться.
 */
const SCREEN = 'flex max-w-[64rem] flex-col gap-4';

/** Рамка блока экрана: итог, задачи, переписка. */
const PANEL = 'flex flex-col gap-3 rounded-control border border-line bg-surface p-3';

/**
 * Экран обсуждения (TRK-672, решение проекта `TRK#51`, п. 8): итог «решено / заменено /
 * открыто» сверху, вся переписка ниже по времени, ответ и заметка прямо здесь, привязанные
 * задачи видны и меняются.
 *
 * Закрытого обсуждения экран не меняет вовсе: форм и кнопок привязки у него нет (а не
 * «есть и отказывают»), сверху плашка. Закрыть обсуждение человек не может — закрывает
 * агент, кнопки на экране нет ни у открытого, ни у закрытого.
 *
 * Состояние — в адресе: `?entry=N` — запись, на которую пришли по ссылке (`TRK~7#3`):
 * её видно сразу, она подсвечена, тело вопроса раскрыто.
 */
export function DiscussionPage() {
  const params = useParams();
  // Канонический адрес: ключ проекта заглавными, как его хранит бэкенд. Набранный руками
  // `/discussions/trk~7` иначе дал бы второй ключ запроса той же темы.
  const address = decodeURIComponent(params.address ?? '').toUpperCase();
  const discussion = useQuery(discussionQueryOptions(address));
  const { t } = useTranslation('discussions');

  if (discussion.error instanceof ApiError && MISSING.includes(discussion.error.code)) {
    return (
      <main className={SCREEN}>
        <h1 className="text-title wrap-anywhere">{t('page.missingTitle', { address })}</h1>
        <Callout>{t('page.missingText')}</Callout>
        <Link to="/questions">{t('page.backToInbox')}</Link>
      </main>
    );
  }

  if (discussion.data === undefined) {
    return (
      <main className={SCREEN}>
        <QueryState query={discussion} loading={t('page.loading', { address })} />
      </main>
    );
  }

  return <Loaded discussion={discussion.data} />;
}

function Loaded({ discussion }: { discussion: DiscussionDetail }) {
  const { address } = discussion;
  const [searchParams] = useSearchParams();
  const openAt = readEntryNo(searchParams.get('entry'));
  const feed = useInfiniteQuery(discussionFeedQueryOptions(address));
  const entries = useMemo(() => feed.data?.pages.flatMap((page) => page.items) ?? [], [feed.data]);
  const rights = useProjectRights();
  const { language } = useLanguage();
  const { t } = useTranslation('discussions');
  const [noting, setNoting] = useState(false);

  const closed = discussion.status === 'closed';
  const canWrite = rights.write && !closed;
  const lastConclusionNo = discussion.conclusion?.no ?? null;

  // Закрылось, пока форма заметки была раскрыта: формы у закрытого нет.
  useEffect(() => {
    if (closed) setNoting(false);
  }, [closed]);

  return (
    <main className={SCREEN} data-discussion={address} data-status={discussion.status}>
      <Link className="w-fit text-meta" to="/questions">
        {t('page.backToInbox')}
      </Link>

      <header className="flex flex-col gap-2">
        <p className="m-0 flex flex-wrap items-center gap-3 text-meta text-muted">
          <span>{t('page.kicker')}</span>
          <code className="font-mono whitespace-nowrap">{address}</code>
          <TurnMark status={discussion.status} turn={discussion.turn} />
          {discussion.open_questions > 0 ? (
            <span className="text-attention">
              {t('row.openQuestions', { count: discussion.open_questions })}
            </span>
          ) : null}
        </p>
        <h1 className="text-title wrap-anywhere">{discussion.title}</h1>
        <p className="m-0 flex flex-wrap items-baseline gap-x-3 text-meta text-muted">
          <span>
            {t('page.openedBy', { author: discussion.created_by.signature ?? t('page.tracker') })}
          </span>
          <RelativeTime value={discussion.created_at} />
        </p>
      </header>

      {closed ? (
        <Callout>
          {t('page.closedNotice', { when: exactTime(discussion.closed_at, language) })}
        </Callout>
      ) : null}

      <section className={PANEL} aria-labelledby="conclusion-title">
        <h2 className="text-screen" id="conclusion-title">
          {t('conclusion.title')}
        </h2>
        <ConclusionBox address={address} conclusion={discussion.conclusion} />
      </section>

      <section className={PANEL} aria-labelledby="tasks-title">
        <h2 className="text-screen" id="tasks-title">
          {t('tasks.title')}
        </h2>
        <p className="m-0 text-meta text-muted">{t('tasks.intro')}</p>
        {discussion.tasks.length === 0 ? (
          <p className="m-0 text-muted italic">{t('tasks.none')}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {discussion.tasks.map((task) => (
              <li
                key={task.key}
                className="flex flex-wrap items-center gap-x-3 gap-y-1"
                data-task={task.key}
              >
                <Link className="font-mono whitespace-nowrap" to={`/tasks/${task.key}`}>
                  {task.key}
                </Link>
                <StatusMark status={task.status} labelled={false} />
                <span className="min-w-0 flex-1 basis-48 wrap-anywhere">{task.title}</span>
                {canWrite ? <DetachTaskButton address={address} taskKey={task.key} /> : null}
              </li>
            ))}
          </ul>
        )}
        {canWrite ? <AttachTaskForm address={address} /> : null}
      </section>

      <section className={PANEL} aria-labelledby="thread-title">
        <h2 className="text-screen" id="thread-title">
          {t('thread.title')}
        </h2>
        <QueryState query={feed} loading={t('thread.loading')} />
        <Thread
          address={address}
          entries={entries}
          canReply={canWrite}
          highlightedNo={openAt}
          conclusionNo={lastConclusionNo}
        />
        {feed.hasNextPage ? (
          <Button onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
            {feed.isFetchingNextPage ? t('thread.loadingMore') : t('thread.more')}
          </Button>
        ) : null}

        {/* Заметка — внизу переписки, где её и пишут: свёрнута, пока не попросили. */}
        {canWrite ? (
          noting ? (
            <NoteForm address={address} onCancel={() => setNoting(false)} />
          ) : (
            <div>
              <Button onClick={() => setNoting(true)}>{t('note.open')}</Button>
            </div>
          )
        ) : null}
      </section>
    </main>
  );
}
