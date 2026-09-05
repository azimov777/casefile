import { useState, type ReactNode } from 'react';
import { Badge, RelativeTime } from '@/shared/ui';
import type { Entry } from '../api/entries';
import { AuthorName } from './author-name';
import { EntryBody } from './entry-body';
import styles from './entry-card.module.css';

interface EntryCardProps {
  entry: Entry;
  /** Обзорные проверки задачи: вердикту нужен текст его проверки. */
  checks?: string[];
  /** Запись, на которую пришли по ссылке: её видно сразу и она подсвечена. */
  highlighted?: boolean;
  /** Ответы на вопрос: они живут под своим вопросом, а не отдельными записями ленты. */
  children?: ReactNode;
}

/**
 * Запись дела в ленте: шапка с номером, типом, автором и временем — и тело по типу.
 *
 * Ссылка на запись копируется в виде `TRK-42#12`: в этом виде её понимает и трекер,
 * и агент, которому человек её потом покажет, — в отличие от адреса страницы.
 */
export function EntryCard({ entry, checks, highlighted = false, children }: EntryCardProps) {
  const reference = `${entry.task_key}#${entry.no}`;

  return (
    <article
      id={`entry-${entry.no}`}
      className={`${styles.card} ${highlighted ? styles.highlighted : ''}`}
      aria-label={reference}
    >
      <header className={styles.head}>
        <span className={styles.no}>#{entry.no}</span>
        <Badge mono>{entry.type}</Badge>
        <AuthorName author={entry.author} />
        <RelativeTime value={entry.created_at} />
        <CopyReference reference={reference} />
      </header>

      <h3 className={styles.title}>{entry.title}</h3>

      <EntryBody entry={entry} checks={checks} />

      {children}
    </article>
  );
}

/**
 * Копирование ссылки. Буфер обмена есть не всегда: браузер даёт его только в защищённом
 * контексте и может отказать по правам — поэтому отказ показывается, а не проглатывается.
 */
function CopyReference({ reference }: { reference: string }) {
  const [state, setState] = useState<'idle' | 'done' | 'failed'>('idle');

  async function copy() {
    try {
      await navigator.clipboard.writeText(reference);
      setState('done');
    } catch {
      setState('failed');
    }
  }

  return (
    <span className={styles.copy}>
      <button type="button" className={styles.copyButton} onClick={() => void copy()}>
        Скопировать {reference}
      </button>
      {state === 'idle' ? null : (
        <span className={styles.copyState} role="status">
          {state === 'done' ? 'скопировано' : 'буфер обмена недоступен'}
        </span>
      )}
    </span>
  );
}
