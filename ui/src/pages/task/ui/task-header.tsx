import { Link } from 'react-router';
import {
  TaskFeatureBadges,
  priorityTone,
  statusTone,
  type TaskDetails,
  type TaskFeatures,
  type TaskStatus,
} from '@/entities/task';
import { Badge, RelativeTime } from '@/shared/ui';
import styles from './task-header.module.css';

interface TaskHeaderProps {
  task: TaskDetails;
  features: TaskFeatures;
  /** Куда задача может уйти по таблице статусов. Справка, а не кнопки: двигают агенты. */
  transitions: TaskStatus[];
}

/** Шапка карточки: где задача стоит и чья она. */
export function TaskHeader({ task, features, transitions }: TaskHeaderProps) {
  return (
    <header className={styles.header}>
      <p className={styles.breadcrumbs}>
        <Link to={`/tasks?queue=${task.queue.key}`}>
          {task.queue.key} — {task.queue.title}
        </Link>
      </p>

      <h1 className={styles.heading}>
        <span className={styles.key}>{task.key}</span> {task.title}
      </h1>

      <div className={styles.badges}>
        <Badge mono tone={statusTone(task.status)}>
          {task.status}
        </Badge>
        <Badge mono tone={priorityTone(task.priority)}>
          {task.priority}
        </Badge>
        <span className={styles.assignee}>
          {task.assignee === null ? (
            <span className={styles.empty}>не назначена</span>
          ) : (
            <Badge mono>{task.assignee}</Badge>
          )}
        </span>
        {task.tags.map((tag) => (
          <Badge key={tag} mono>
            {tag}
          </Badge>
        ))}
      </div>

      <div className={styles.badges}>
        <TaskFeatureBadges features={features} />
      </div>

      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>Обновлена</dt>
          <dd>
            <RelativeTime value={task.updated_at} />
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>Заведена</dt>
          <dd>
            <RelativeTime value={task.created_at} />
          </dd>
        </div>
        <div className={styles.fact}>
          <dt title="Куда задача может уйти по таблице статусов. Проверки перехода считаются в момент перехода">
            Возможные переходы
          </dt>
          <dd className={styles.transitions}>
            {transitions.length === 0 ? (
              <span className={styles.empty}>никуда: статус конечный</span>
            ) : (
              transitions.map((status) => (
                <Badge key={status} mono tone={statusTone(status)}>
                  {status}
                </Badge>
              ))
            )}
          </dd>
        </div>
      </dl>
    </header>
  );
}
