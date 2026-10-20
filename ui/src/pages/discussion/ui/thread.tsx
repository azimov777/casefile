import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import {
  AuthorName,
  CopyEntryLink,
  EntryBody,
  EntryHeadline,
  EntryKind,
  entryHeadline,
  factsOfEntry,
  isServiceEntry,
} from '@/entities/entry';
import type { DiscussionEntry, DiscussionOption } from '@/entities/discussion';
import { ReplyForm } from '@/features/manage-discussion';
import { cn, discussionHref } from '@/shared/lib';
import { Badge, Button, Markdown, RelativeTime } from '@/shared/ui';

interface ThreadProps {
  address: string;
  entries: DiscussionEntry[];
  /** Обсуждение открыто и человек вправе писать: у вопросов есть «Ответить». */
  canReply: boolean;
  /** Запись, на которую пришли по ссылке: видна сразу, подсвечена, тело раскрыто. */
  highlightedNo: number | null;
  /** Номер последнего итога: он называется актуальным, прежние — прежними. */
  conclusionNo: number | null;
}

/**
 * Переписка: все записи дела обсуждения по времени, от старых к новым.
 *
 * Агент слева, человек справа; служебные записи (привязка, отвязка, закрытие) — строками
 * без рамки, как в деле задачи: дело обязано быть полным, но места им столько, сколько в
 * них смысла. У вопроса видно название, тело раскрывается; вопрос без ответа назван
 * ждущим, и под ним «Ответить на #N». Ответ подшивает форма и сама остаётся на месте:
 * новая запись приходит в ленту перечитыванием.
 */
export function Thread({ address, entries, canReply, highlightedNo, conclusionNo }: ThreadProps) {
  const { t } = useTranslation('discussions');
  const [replyingTo, setReplyingTo] = useState<number | null>(null);

  // Вопрос закрывает любой ответ на него: по существу, снятие и замена (TRK-552).
  const answered = new Set<number>();
  for (const entry of entries) {
    if (entry.type === 'answer') answered.add(entry.payload.question_no);
  }

  // Варианты каждого вопроса: запись ответа с выбором называет текст варианта из вопроса.
  const optionsOf = new Map<number, DiscussionOption[]>();
  for (const entry of entries) {
    if (entry.type === 'question' && entry.payload.options != null) {
      optionsOf.set(entry.no, entry.payload.options);
    }
  }

  if (entries.length === 0) return <p className="m-0 text-muted italic">{t('thread.empty')}</p>;

  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0" aria-label={t('thread.label')}>
      {entries.map((entry) => (
        <li key={entry.no} className="flex flex-col">
          <Item
            address={address}
            entry={entry}
            highlighted={highlightedNo === entry.no}
            isAnswered={entry.type === 'question' && answered.has(entry.no)}
            actual={entry.type === 'conclusion' && entry.no === conclusionNo}
            options={entry.type === 'question' ? (entry.payload.options ?? null) : null}
            chosen={
              entry.type === 'answer' && entry.payload.choice != null
                ? {
                    label: entry.payload.choice,
                    text:
                      optionsOf
                        .get(entry.payload.question_no)
                        ?.find((option) => option.label === entry.payload.choice)?.text ?? null,
                  }
                : null
            }
            replyOpen={replyingTo === entry.no}
            onReply={canReply ? (open) => setReplyingTo(open ? entry.no : null) : undefined}
          />
        </li>
      ))}
    </ol>
  );
}

interface ItemProps {
  address: string;
  entry: DiscussionEntry;
  highlighted: boolean;
  isAnswered: boolean;
  actual: boolean;
  replyOpen: boolean;
  /** Варианты вопроса: форма ответа покажет их карточками. */
  options: DiscussionOption[] | null;
  /** Выбранный в ответе вариант: метка и текст из вопроса (`null` — вопрос старый или текста нет). */
  chosen: { label: string; text: string | null } | null;
  /** Нет — отвечать нельзя (закрыто или нет прав). */
  onReply?: (open: boolean) => void;
}

function Item({
  address,
  entry,
  highlighted,
  isAnswered,
  actual,
  replyOpen,
  options,
  chosen,
  onReply,
}: ItemProps) {
  const { t } = useTranslation('discussions');
  const { t: brick } = useTranslation('ui');
  const ref = useRef<HTMLElement>(null);

  // Ссылка ведёт к записи: её надо найти глазами за долю секунды.
  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView?.({ block: 'center' });
  }, [highlighted]);

  const service = isServiceEntry(entry.type);
  const headline = entryHeadline(factsOfEntry(entry), address, brick);
  const mine = entry.author.kind === 'human';
  const owner = { kind: 'discussion', key: address } as const;
  const reference = `${address}#${entry.no}`;

  const meta = (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-muted">
      <Link
        className="font-mono font-bold whitespace-nowrap text-text"
        to={discussionHref(address, entry.no)}
      >
        #{entry.no}
      </Link>
      <EntryKind type={entry.type} />
      {service && headline.kind === 'built' ? (
        <span className="text-text">
          <EntryHeadline headline={headline} />
        </span>
      ) : null}
      <AuthorName author={entry.author} />
      {entry.type === 'answer' && entry.payload.relayed_from != null ? (
        <span data-relayed-from="" className="italic">
          {t('thread.relayedFrom', { name: entry.payload.relayed_from })}
        </span>
      ) : null}
      <RelativeTime value={entry.created_at} />
      <CopyEntryLink owner={owner} no={entry.no} />
    </header>
  );

  // Служебная запись: строка вместо карточки.
  if (service) {
    return (
      <article
        id={`entry-${entry.no}`}
        ref={ref}
        data-type={entry.type}
        data-highlighted={highlighted ? '' : undefined}
        aria-label={reference}
        className={cn('py-1', highlighted && 'rounded-mark ring-2 ring-accent')}
      >
        {meta}
      </article>
    );
  }

  return (
    <article
      id={`entry-${entry.no}`}
      ref={ref}
      data-type={entry.type}
      data-side={mine ? 'human' : 'agent'}
      data-highlighted={highlighted ? '' : undefined}
      aria-label={reference}
      className={cn(
        'flex max-w-full flex-col gap-2 rounded-control border px-3 py-2 wide:max-w-[92%]',
        mine ? 'self-end border-transparent bg-accent-soft' : 'self-start border-line bg-surface',
        entry.type === 'conclusion' && 'self-stretch border-line-strong',
        highlighted && 'border-accent ring-2 ring-accent',
      )}
    >
      {meta}
      <Content
        entry={entry}
        highlighted={highlighted}
        isAnswered={isAnswered}
        actual={actual}
        chosen={chosen}
      />
      {entry.type === 'question' && onReply !== undefined && !isAnswered ? (
        replyOpen ? (
          <ReplyForm
            address={address}
            questionNo={entry.no}
            options={options}
            onCancel={() => onReply(false)}
          />
        ) : (
          <div>
            <Button onClick={() => onReply(true)}>{t('reply.open', { no: entry.no })}</Button>
          </div>
        )
      ) : null}
    </article>
  );
}

function Content({
  entry,
  highlighted,
  isAnswered,
  actual,
  chosen,
}: {
  entry: DiscussionEntry;
  highlighted: boolean;
  isAnswered: boolean;
  actual: boolean;
  chosen: ItemProps['chosen'];
}) {
  const { t } = useTranslation('discussions');

  switch (entry.type) {
    case 'question':
      return (
        <div className="flex flex-col gap-2">
          <p className="m-0 flex flex-wrap items-baseline gap-2">
            <strong className="wrap-anywhere">{entry.title}</strong>
            <Badge tone={isAnswered ? 'positive' : 'attention'}>
              {isAnswered ? t('thread.answered') : t('thread.waiting')}
            </Badge>
          </p>
          <p className="m-0 flex flex-wrap items-center gap-2 text-meta text-muted">
            <span>{t('thread.addressees')}</span>
            {entry.payload.addressees.map((name) => (
              <Badge key={name} mono>
                {name}
              </Badge>
            ))}
          </p>
          {entry.body.trim() === '' ? null : (
            <Details open={highlighted}>
              <Markdown>{entry.body}</Markdown>
            </Details>
          )}
        </div>
      );

    case 'answer':
      return (
        <>
          {chosen === null ? null : (
            <p
              data-choice={chosen.label}
              className="m-0 flex flex-wrap items-baseline gap-x-2 gap-y-1"
            >
              <strong className="rounded-mark border border-accent bg-surface px-2 whitespace-nowrap text-accent">
                {t('thread.chosen', { label: chosen.label })}
              </strong>
              {chosen.text === null ? null : (
                <span className="min-w-0 wrap-anywhere">{chosen.text}</span>
              )}
            </p>
          )}
          {entry.body.trim() === '' ? null : <Prose body={entry.body} />}
        </>
      );

    case 'note':
      return (
        <div className="flex flex-col gap-1">
          <strong className="wrap-anywhere">{entry.title}</strong>
          {entry.body.trim() === '' || entry.body.trim() === entry.title ? null : (
            <Prose body={entry.body} />
          )}
        </div>
      );

    case 'conclusion':
      return (
        <div className="flex flex-col gap-2">
          <Badge tone={actual ? 'positive' : 'neutral'}>
            {actual ? t('thread.conclusionActual') : t('thread.conclusionPrior')}
          </Badge>
          <Details open={highlighted || actual}>
            <EntryBody entry={entry} />
          </Details>
        </div>
      );

    default:
      return <EntryBody entry={entry} />;
  }
}

function Prose({ body }: { body: string }) {
  return (
    <div className="min-w-0 wrap-anywhere">
      <Markdown>{body}</Markdown>
    </div>
  );
}

/** Тело под спойлером: свёрнуто, пока не попросили, — длинный вопрос не заслоняет переписку. */
function Details({ open, children }: { open: boolean; children: React.ReactNode }) {
  const { t } = useTranslation('discussions');
  return (
    <details open={open || undefined} className="min-w-0">
      <summary className="w-fit cursor-pointer text-meta text-accent max-fold:min-h-(--ui-tap)">
        {t('thread.details')}
      </summary>
      <div className="mt-2 min-w-0 wrap-anywhere">{children}</div>
    </details>
  );
}
