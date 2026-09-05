import { Link } from 'react-router';
import type { LinkKind, TaskLink } from '@/entities/task';
import { Badge } from '@/shared/ui';
import styles from './task-links.module.css';

/**
 * Связи с обеих сторон. Вид назван от лица этой задачи, статус — у той, что на другом
 * конце: именно из `blocked_by` на незакрытую задачу бэкенд считает признак «заблокирована».
 */
export function TaskLinks({ links }: { links: TaskLink[] }) {
  if (links.length === 0) return <p className={styles.empty}>Связей нет.</p>;

  const byKind = new Map<LinkKind, TaskLink[]>();
  for (const link of links) {
    const same = byKind.get(link.kind) ?? [];
    same.push(link);
    byKind.set(link.kind, same);
  }

  return (
    <div className={styles.groups}>
      {[...byKind].map(([kind, group]) => (
        <div key={kind} className={styles.group}>
          <Badge mono>{kind}</Badge>
          <ul className={styles.list}>
            {group.map((link) => (
              <li key={link.other.key} className={styles.item}>
                <Link className={styles.key} to={`/tasks/${link.other.key}`}>
                  {link.other.key}
                </Link>
                <span className={styles.title}>{link.other.title}</span>
                <Badge mono>{link.other.status}</Badge>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
