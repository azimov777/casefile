import { Link } from 'react-router';
import { Badge, RelativeTime } from '@/shared/ui';
import type { Task } from '../api/tasks';
import { TaskFeatureBadges } from './task-features';
import { priorityTone } from './tones';
import styles from './task-card.module.css';

/**
 * Задача карточкой: то же, что строка списка, но в один столбец. Признаки берутся
 * из той же выдачи, поэтому запроса на карточку нет.
 *
 * Кликабельна целиком через ключ-ссылку: перетаскивания нет и не будет — статусы
 * двигают агенты (`CONCEPT.md`, 7).
 */
export function TaskCard({ task }: { task: Task }) {
  const features = task.features ?? null;

  return (
    <article className={styles.card}>
      <div className={styles.top}>
        <Link className={styles.key} to={`/tasks/${task.key}`}>
          {task.key}
        </Link>
        {task.priority === null || task.priority === undefined ? null : (
          <Badge mono tone={priorityTone(task.priority)}>
            {task.priority}
          </Badge>
        )}
      </div>

      <p className={styles.title}>{task.title ?? ''}</p>

      <div className={styles.bottom}>
        {task.assignee === null || task.assignee === undefined ? (
          <span className={styles.empty}>не назначена</span>
        ) : (
          <Badge mono>{task.assignee}</Badge>
        )}
        <RelativeTime value={task.updated_at} />
      </div>

      {features === null ? null : (
        <div className={styles.features}>
          <TaskFeatureBadges features={features} />
        </div>
      )}
    </article>
  );
}
