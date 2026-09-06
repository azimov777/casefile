import { Link } from 'react-router';
import { Badge, RelativeTime } from '@/shared/ui';
import type { Task } from '../api/tasks';
import { TaskFeatureBadges } from './task-features';
import { priorityTone, statusTone } from './tones';
import styles from './task-row.module.css';

/**
 * Строка списка задач. Ничего не вычисляет: признаки приходят из `features` той же
 * выдачи, поэтому запроса на строку нет (`../tracker/docs/FRONTEND.md`, «Строка списка»).
 */
export function TaskRow({ task }: { task: Task }) {
  const features = task.features ?? null;
  const tags = task.tags ?? [];

  return (
    <tr>
      <th scope="row" className={styles.key}>
        <Link to={`/tasks/${task.key}`}>{task.key}</Link>
      </th>
      <td className={styles.title}>{task.title ?? ''}</td>
      <td>
        {task.status === null || task.status === undefined ? null : (
          <Badge mono tone={statusTone(task.status)}>
            {task.status}
          </Badge>
        )}
      </td>
      <td className={styles.assignee}>
        {task.assignee ?? <span className={styles.empty}>не назначена</span>}
      </td>
      <td>
        {task.priority === null || task.priority === undefined ? null : (
          <Badge mono tone={priorityTone(task.priority)}>
            {task.priority}
          </Badge>
        )}
      </td>
      <td>
        <span className={styles.tags}>
          {tags.map((tag) => (
            <Badge key={tag} mono>
              {tag}
            </Badge>
          ))}
        </span>
      </td>
      <td>
        <span className={styles.features}>
          {features === null ? null : <TaskFeatureBadges features={features} />}
        </span>
      </td>
      <td className={styles.updated}>
        <RelativeTime value={task.updated_at} />
      </td>
    </tr>
  );
}
