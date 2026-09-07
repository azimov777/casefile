import { Link } from 'react-router';
import {
  PriorityMark,
  StatusMark,
  TaskFeatureBadges,
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

      {/*
       * Четыре разных вещи перестали быть четырьмя одинаковыми плашками (решение Д7):
       * статус — форма со значением, приоритет — высота столбиков, исполнитель и теги
       * остаются плашками, потому что они и есть метки. Род значения при этом никуда
       * не делся: он ушёл в доступное имя знака и в подпись плашки.
       */}
      <div className={styles.badges}>
        <StatusMark status={task.status} />
        <PriorityMark priority={task.priority} />
        <span className={styles.assignee}>
          {task.assignee === null ? (
            <span className={styles.empty}>исполнитель не назначен</span>
          ) : (
            <Badge mono kind="исполнитель">
              {task.assignee}
            </Badge>
          )}
        </span>
        {task.tags.map((tag) => (
          <Badge key={tag} mono kind="тег">
            {tag}
          </Badge>
        ))}

        {/* Признаки в той же строке, что и плашки: две отдельные строки одинаковых
            плашек занимали место главного, ничего не добавляя к различимости. */}
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
          {/*
           * Возможные переходы — справка, и выглядеть должны справкой. Плашками они
           * читались как кнопки, которых нет и не будет: статусы двигают агенты
           * (`CONCEPT.md`, 7), а человек их только видит. Поэтому обычный текст
           * моноширинным, через запятую.
           */}
          <dd className={styles.transitions}>
            {transitions.length === 0 ? (
              <span className={styles.empty}>никуда: статус конечный</span>
            ) : (
              transitions.join(', ')
            )}
          </dd>
        </div>
      </dl>
    </header>
  );
}
