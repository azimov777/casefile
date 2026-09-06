import { Link } from 'react-router';
import { Badge, RelativeTime } from '@/shared/ui';
import { skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { TaskFeatureBadges } from './task-features';
import { priorityTone } from './tones';
import styles from './task-card.module.css';

/**
 * Задача карточкой: то же, что строка списка, но в один столбец. Признаки берутся
 * из той же выдачи, поэтому запроса на карточку нет.
 *
 * Кликабельна целиком — тем же приёмом, что строка списка: настоящая ссылка одна,
 * на названии, а на всю карточку её растягивает псевдоэлемент. Перетаскивания нет
 * и не будет: статусы двигают агенты (`CONCEPT.md`, 7).
 */
export function TaskCard({ task }: { task: Task }) {
  const features = task.features ?? null;

  return (
    <article className={styles.card}>
      <div className={styles.top}>
        {/* Ключ не поднят над растяжкой: клик по нему ведёт в ту же задачу. */}
        <span className={styles.key}>{task.key}</span>
        {task.priority === null || task.priority === undefined ? null : (
          <Badge mono tone={priorityTone(task.priority)}>
            {task.priority}
          </Badge>
        )}
      </div>

      <p className={styles.title}>
        <Link
          className={styles.link}
          to={taskRefHref({ key: task.key, entryNo: null })}
          draggable={false}
          onClick={skipClickWhileSelecting}
        >
          <span className={styles.raised}>{task.title ?? ''}</span>
        </Link>
      </p>

      <div className={styles.bottom}>
        {task.assignee === null || task.assignee === undefined ? (
          <span className={styles.empty}>не назначена</span>
        ) : (
          <Badge mono>
            <span className={styles.raised}>{task.assignee}</span>
          </Badge>
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
