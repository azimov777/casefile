import { Link } from 'react-router';
import { taskRefHref } from '@/shared/lib';
import type { Headline, HeadlinePart } from '../model/headline';
import styles from './entry-headline.module.css';

/**
 * Собранная строка заголовка: слова по-русски, идентификаторы контракта как есть.
 *
 * Ничего не решает сама: что показывать, уже сказано в `Headline`. Здесь только то,
 * как выглядит каждая часть, — и это одно место на ленту дела и опись карточки.
 */
export function EntryHeadline({ headline, linked = true }: EntryHeadlineProps) {
  if (headline.kind !== 'built') return null;

  return (
    <span className={styles.line}>
      {headline.parts.map((part, index) => (
        <Piece key={index} part={part} linked={linked} />
      ))}
    </span>
  );
}

interface EntryHeadlineProps {
  headline: Headline;
  /**
   * Делать ли ключи ссылками. В описи карточки строка целиком — кнопка раскрытия
   * записи, и ссылка внутри неё была бы интерактивом внутри интерактива: `axe`
   * называет это `nested-interactive`, а с клавиатуры туда не попасть осмысленно.
   */
  linked?: boolean;
}

function Piece({ part, linked }: { part: HeadlinePart; linked: boolean }) {
  switch (part.kind) {
    case 'words':
      return <span>{part.text}</span>;
    case 'id':
      return <code className={styles.id}>{part.text}</code>;
    case 'task':
      return linked ? (
        <Link className={styles.ref} to={`/tasks/${part.key}`}>
          {part.key}
        </Link>
      ) : (
        <code className={styles.ref}>{part.key}</code>
      );
    case 'entry':
      return linked ? (
        <Link className={styles.ref} to={taskRefHref({ key: part.key, entryNo: part.no })}>
          {part.key}#{part.no}
        </Link>
      ) : (
        <code className={styles.ref}>
          {part.key}#{part.no}
        </code>
      );
  }
}
