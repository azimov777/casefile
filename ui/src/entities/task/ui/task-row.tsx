import { Badge, RelativeTime } from '@/shared/ui';
import type { Task } from '../api/tasks';
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
        {task.key}
      </th>
      <td className={styles.title}>{task.title ?? ''}</td>
      <td>
        {task.status === null || task.status === undefined ? null : (
          <Badge mono>{task.status}</Badge>
        )}
      </td>
      <td className={styles.assignee}>
        {task.assignee ?? <span className={styles.empty}>не назначена</span>}
      </td>
      <td>
        {task.priority === null || task.priority === undefined ? null : (
          <Badge mono>{task.priority}</Badge>
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

function TaskFeatureBadges({ features }: { features: NonNullable<Task['features']> }) {
  return (
    <>
      {features.blocked ? (
        <Badge tone="danger" title="Есть связь blocked_by на незакрытую задачу">
          заблокирована
        </Badge>
      ) : null}

      {features.open_questions > 0 ? (
        <Badge title="Вопросы без ответа">вопросов {features.open_questions}</Badge>
      ) : null}

      {features.open_blocking_questions > 0 ? (
        <Badge tone="danger" title="Из них помечены blocking">
          блокирующих {features.open_blocking_questions}
        </Badge>
      ) : null}

      {features.last_summary_at === null || features.last_summary_at === undefined ? (
        <span className={styles.empty}>сводки нет</span>
      ) : (
        <span className={styles.summary}>
          сводка <RelativeTime value={features.last_summary_at} />
        </span>
      )}
    </>
  );
}
