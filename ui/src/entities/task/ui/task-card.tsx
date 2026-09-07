import { Link, useLocation } from 'react-router';
import { Badge, RelativeTime } from '@/shared/ui';
import { listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { hasFeatureBadges } from './feature-badges';
import { PriorityMark } from './priority-mark';
import { TaskFeatureBadges } from './task-features';
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
  const { search } = useLocation();
  const features = task.features ?? null;

  return (
    <article className={styles.card}>
      <div className={styles.top}>
        {/* Ключ не поднят над растяжкой: клик по нему ведёт в ту же задачу. */}
        <span className={styles.key}>{task.key}</span>
        <PriorityMark priority={task.priority} withName={false} />
      </div>

      <p className={styles.title}>
        <Link
          className={styles.link}
          to={taskRefHref({ key: task.key, entryNo: null })}
          // Отбор, с которым человек смотрел список, едет с ним в задачу: обратно
          // он вернётся к тем же строкам, а не ко всем задачам очереди.
          state={listReturnState(search)}
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
        {/* То же время, что в строке списка: активность в деле, а не правка карточки. */}
        {features?.last_entry_at === null || features?.last_entry_at === undefined ? (
          <span className={styles.empty}>в деле пусто</span>
        ) : (
          <RelativeTime value={features.last_entry_at} />
        )}
      </div>

      {features === null || !hasFeatureBadges(features) ? null : (
        <div className={styles.features}>
          <TaskFeatureBadges features={features} />
        </div>
      )}
    </article>
  );
}
