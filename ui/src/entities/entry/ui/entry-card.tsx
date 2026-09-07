import { useState, type ReactNode } from 'react';
import { RelativeTime } from '@/shared/ui';
import type { Entry } from '../api/entries';
import { isServiceEntry } from '../api/entries';
import { entryHeadline, factsOfEntry } from '../model/headline';
import { AuthorName } from './author-name';
import { EntryBody } from './entry-body';
import { EntryHeadline } from './entry-headline';
import { EntryKind } from './entry-kind';
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
  const headline = entryHeadline(entry.type, factsOfEntry(entry), entry.task_key);
  // Служебная запись несёт один факт и получает столько места, сколько в ней смысла:
  // строка вместо карточки. Прятать её нельзя — дело обязано быть полным.
  const service = isServiceEntry(entry.type);

  return (
    <article
      id={`entry-${entry.no}`}
      className={`${styles.card} ${service ? styles.service : ''} ${
        highlighted ? styles.highlighted : ''
      }`}
      // Тип записи виден разметке, а не только глазу: сквозной тест меряет высоту
      // служебных записей, а искать их по тексту плашки значило бы завязаться на
      // подпись, которую завтра перепишут.
      data-type={entry.type}
      aria-label={reference}
    >
      <header className={styles.head}>
        {/* Точка на нити времени: род записи виден до чтения слова (решение Д13). */}
        <span className={styles.dot} aria-hidden="true">
          <EntryKind type={entry.type} withName={false} />
        </span>
        <span className={styles.no}>#{entry.no}</span>
        <EntryKind type={entry.type} />
        {/* Заголовок служебной записи стоит прямо в шапке: отдельной строкой он был бы
            вторым разом сказанным одним и тем же. */}
        {service && headline.kind === 'built' ? (
          <span className={styles.headline}>
            <EntryHeadline headline={headline} />
          </span>
        ) : null}
        <AuthorName author={entry.author} />
        <RelativeTime value={entry.created_at} />
        <CopyReference reference={reference} />
      </header>

      {/*
       * Чей заголовок — решает `entryHeadline`. У записи агента он написан автором;
       * у `answer` и `verdict` его выводит трекер по-английски, и здесь он собирается
       * заново по-русски; у сводки он дословно повторяет «следующий шаг» из тела,
       * и второй раз его показывать незачем.
       */}
      {service ? null : headline.kind === 'built' ? (
        <h3 className={styles.title}>
          <EntryHeadline headline={headline} />
        </h3>
      ) : headline.kind === 'author' ? (
        <h3 className={styles.title}>{entry.title}</h3>
      ) : null}

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
