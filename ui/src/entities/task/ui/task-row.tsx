import { Link, useLocation } from 'react-router';
import { Badge, RelativeTime } from '@/shared/ui';
import { listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { PriorityMark } from './priority-mark';
import { StatusMark } from './status-mark';
import { TaskFeatureBadges } from './task-features';
import styles from './task-row.module.css';

/**
 * Строка списка задач. Ничего не вычисляет: признаки приходят из `features` той же
 * выдачи, поэтому запроса на строку нет (`../tracker/docs/FRONTEND.md`, «Строка списка»).
 *
 * В задачу ведёт вся строка, а не один ключ. Настоящая ссылка ровно одна — на
 * названии, самой широкой и самой заметной ячейке, — а на всю строку её растягивает
 * псевдоэлемент. Обернуть строку в `<a>` нельзя: ссылка внутри ссылки недопустима,
 * а обход с клавиатуры дал бы остановку на каждой ячейке вместо одной на задачу.
 */
export function TaskRow({ task }: { task: Task }) {
  // Адрес списка целиком, вместе с отбором: он поедет в задачу состоянием перехода.
  const { search } = useLocation();
  const features = task.features ?? null;
  const tags = task.tags ?? [];
  const activity = features?.last_entry_at ?? null;

  return (
    <tr className={styles.row}>
      {/* Ключ намеренно не поднят над растяжкой: клик по нему ведёт в ту же задачу,
          то есть туда, куда он и вёл, когда был единственной мишенью. */}
      <th scope="row" className={styles.key}>
        {task.key}
      </th>
      <td className={styles.title}>
        <Link
          className={styles.link}
          to={taskRefHref({ key: task.key, entryNo: null })}
          // Отбор, с которым человек смотрел список, едет с ним в задачу: обратно
          // он вернётся к тем же строкам, а не ко всем задачам очереди.
          state={listReturnState(search)}
          // Перетаскивание ссылки выключено, иначе протяжка по названию таскала бы
          // ссылку вместо того, чтобы выделять текст.
          draggable={false}
          onClick={skipClickWhileSelecting}
        >
          <span className={styles.raised}>{task.title ?? ''}</span>
        </Link>
      </td>
      <td>
        <StatusMark status={task.status} />
      </td>
      <td className={styles.assignee}>
        {task.assignee === null || task.assignee === undefined ? (
          <span className={styles.empty}>не назначена</span>
        ) : (
          /* Поднят над растяжкой: имя исполнителя из списка выделяют и копируют. */
          <span className={styles.raised}>{task.assignee}</span>
        )}
      </td>
      <td>
        <PriorityMark priority={task.priority} />
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
      {/* Единственное время в строке: когда в дело последний раз что-то подшивали.
          `updated_at` отсюда убран — он двигался и от правки карточки, и человек
          не мог сказать, чем два относительных времени в соседних ячейках различаются. */}
      <td className={styles.activity}>
        {activity === null ? (
          <span className={styles.empty}>в деле пусто</span>
        ) : (
          <RelativeTime value={activity} />
        )}
      </td>
    </tr>
  );
}
