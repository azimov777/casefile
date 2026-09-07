import { Link, useLocation } from 'react-router';
import { RelativeTime } from '@/shared/ui';
import { listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { TaskFeatureMarks } from './feature-marks';
import { PriorityMark } from './priority-mark';
import { StatusMark } from './status-mark';
import { TaskTags } from './task-tags';

/**
 * Строка списка задач. Ничего не вычисляет: признаки приходят из `features` той же
 * выдачи, поэтому запроса на строку нет (`../tracker/docs/FRONTEND.md`, «Строка списка»).
 *
 * В задачу ведёт вся строка, а не один ключ. Настоящая ссылка ровно одна — на
 * названии, самой широкой и самой заметной ячейке, — а на всю строку её растягивает
 * псевдоэлемент. Обернуть строку в `<a>` нельзя: ссылка внутри ссылки недопустима,
 * а обход с клавиатуры дал бы остановку на каждой ячейке вместо одной на задачу.
 *
 * Высота строки задана токеном и не зависит от содержимого: список сканируют
 * взглядом сверху вниз, и строка, выросшая от третьего тега, ломает ритм там,
 * где содержания не прибавилось (решение Д4).
 */
export function TaskRow({ task }: { task: Task }) {
  // Адрес списка целиком, вместе с отбором: он поедет в задачу состоянием перехода.
  const { search } = useLocation();
  const features = task.features ?? null;
  const tags = task.tags ?? [];
  const activity = features?.last_entry_at ?? null;
  const title = task.title ?? '';

  return (
    <tr className="relative h-(--ui-row-height) border-t border-line hover:bg-sunken">
      {/* Ключ намеренно не поднят над растяжкой: клик по нему ведёт в ту же задачу,
          то есть туда, куда он и вёл, когда был единственной мишенью. */}
      <th scope="row" className="px-3 text-left font-normal font-mono text-mark text-faint">
        {task.key}
      </th>
      <td className="max-w-0 overflow-hidden px-3">
        <Link
          className="text-text no-underline [-webkit-user-drag:none] after:absolute after:inset-0 after:content-[''] hover:underline focus-visible:outline-none focus-visible:after:rounded-mark focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-focus"
          to={taskRefHref({ key: task.key, entryNo: null })}
          // Отбор, с которым человек смотрел список, едет с ним в задачу: обратно
          // он вернётся к тем же строкам, а не ко всем задачам очереди.
          state={listReturnState(search)}
          // Перетаскивание ссылки выключено, иначе протяжка по названию таскала бы
          // ссылку вместо того, чтобы выделять текст.
          draggable={false}
          onClick={skipClickWhileSelecting}
        >
          {/* Урезанное многоточием название отдаёт полный текст подсказкой:
              обрезание без доступа к скрытому — потеря данных, а не плотность. */}
          <span className="block truncate" title={title}>
            {title}
          </span>
        </Link>
      </td>
      <td className="px-3">
        <StatusMark status={task.status} />
      </td>
      <td className="px-3 text-mark text-faint">
        {task.assignee === null || task.assignee === undefined ? (
          <span aria-hidden="true">—</span>
        ) : (
          /* Поднят над растяжкой: имя исполнителя из списка выделяют и копируют. */
          <span className="relative z-1">{task.assignee}</span>
        )}
      </td>
      <td className="px-3">
        <PriorityMark priority={task.priority} />
      </td>
      <td className="px-3">
        <TaskTags tags={tags} />
      </td>
      <td className="px-3">
        <span className="flex items-center gap-2">
          {features === null ? null : <TaskFeatureMarks features={features} />}
        </span>
      </td>
      {/* Единственное время в строке: когда в дело последний раз что-то подшивали.
          `updated_at` отсюда убран — он двигался и от правки карточки, и человек
          не мог сказать, чем два относительных времени в соседних ячейках различаются. */}
      <td className="px-3 text-right text-mark text-faint whitespace-nowrap">
        {activity === null ? (
          <span aria-hidden="true">в деле пусто</span>
        ) : (
          <RelativeTime value={activity} />
        )}
      </td>
    </tr>
  );
}
