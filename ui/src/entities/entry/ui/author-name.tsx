import type { Author } from '../api/entries';
import styles from './author-name.module.css';

/**
 * Кто говорит. Подпись пуста только у самого трекера: у человека и агента это имя
 * участника, у временного агента — метка. Различать метку и имя намеренно нельзя
 * (`../tracker/docs/FRONTEND.md`), поэтому род показывается отдельной подписью.
 */
export function AuthorName({ author }: { author: Author }) {
  const signature = author.signature ?? null;

  return (
    <span className={styles.author}>
      <span className={styles.signature}>{signature ?? 'трекер'}</span>
      {signature === null ? null : <span className={styles.kind}>{author.kind}</span>}
    </span>
  );
}
