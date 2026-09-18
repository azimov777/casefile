import type { MouseEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { RelativeTime } from '@/shared/ui';
import { listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { TaskFeatureMarks } from './feature-marks';
import { PriorityMark } from './priority-mark';
import { StatusMark } from './status-mark';
import { TaskParents } from './task-parents';

/**
 * Строка списка задач. Ничего не вычисляет: признаки приходят из `features` той же
 * выдачи, поэтому запроса на строку нет (`docs/FRONTEND.md`, «Строка списка»).
 *
 * В задачу ведёт вся строка, а не один ключ. Настоящая ссылка в задачу ровно одна — на
 * названии, самой широкой и самой заметной ячейке: она даёт обход с клавиатуры одной
 * остановкой на задачу, контекстное меню, «копировать адрес» и cmd-клик. Остальную
 * площадь строки в задачу уводит обработчик клика на `<tr>`. Вторая ссылка бывает
 * только у задачи с родителем и ведёт в родителя (UI-119): её клик обработчик строки
 * не трогает, как и клик по любой ссылке.
 *
 * **Растяжки псевдоэлементом здесь больше нет** (UI-39). Она рисовала `inset: 0` от
 * `<tr class="relative">`, а `position: relative` у элемента с `display: table-row`
 * в WebKit containing block не создаёт: в Safari растяжка считалась от документа и
 * накрывала весь экран — клик в любом месте страницы уводил в последнюю задачу выдачи.
 * Обёрткой строки в `<a>` это не лечится: ссылка внутри ссылки недопустима, а обход
 * табом дал бы остановку на каждой ячейке.
 *
 * Высота строки задана токеном и не зависит от содержимого: список сканируют
 * взглядом сверху вниз, и строка, выросшая от длинного значения, ломает ритм там,
 * где содержания не прибавилось (решение Д4).
 */
export function TaskRow({ task }: { task: Task }) {
  // Адрес списка целиком, вместе с отбором: он поедет в задачу состоянием перехода.
  const { search } = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation('ui');
  const features = task.features ?? null;
  const activity = features?.last_entry_at ?? null;
  const title = task.title ?? '';
  const href = taskRefHref({ key: task.key, entryNo: null });

  /**
   * Клик по площади строки. Уводит в задачу ровно тогда, когда человек этого хотел.
   *
   * Клик по настоящей ссылке сюда доходит всплытием, но обрабатывать его нельзя:
   * переход по ней делает браузер, и второй переход поверх первого — это два разных
   * пути к одному и тому же, а второй путь мы не заводим.
   */
  function openTask(event: MouseEvent<HTMLTableRowElement>) {
    if (event.target instanceof Element && event.target.closest('a, button, input, label')) return;

    // Протяжка мышью по имени исполнителя кончается кликом внутри строки: человек
    // выделял текст, чтобы скопировать его, а не уходил со страницы.
    if ((window.getSelection()?.toString() ?? '') !== '') return;

    // «Открой рядом» остаётся тем же жестом, что и на ссылке: клик с модификатором
    // ведёт во вторую вкладку, а `alt` у браузера значит «скачать» и переходом не является.
    if (event.metaKey || event.ctrlKey || event.shiftKey) {
      window.open(href, '_blank', 'noopener');
      return;
    }
    if (event.altKey) return;

    navigate(href, { state: listReturnState(search) });
  }

  /** Средняя кнопка мыши — «во вторую вкладку», и на пустом месте строки тоже. */
  function openTaskAside(event: MouseEvent<HTMLTableRowElement>) {
    if (event.button !== 1) return;
    if (event.target instanceof Element && event.target.closest('a')) return;
    event.preventDefault();
    window.open(href, '_blank', 'noopener');
  }

  return (
    /*
     * Обводка фокуса рисуется строкой, а не ссылкой: остановка одна на задачу, и
     * показать надо задачу целиком. `outline` — единственное, чем это можно нарисовать:
     * `box-shadow` у `table-row` не рисует ни один движок (UI-39#5).
     *
     * Строку обводит фокус только на её собственной ссылке (`data-link="task"`). Ссылка
     * на родителя (UI-119) — вторая остановка в строке, и ведёт она в другую задачу:
     * обведённая строка обещала бы Enter в эту. Её фокус рисует общий `:focus-visible`
     * вокруг самой подписи.
     */
    <tr
      className="h-(--ui-row-height) cursor-pointer border-t border-line hover:bg-sunken has-[[data-link=task]:focus-visible]:outline-2 has-[[data-link=task]:focus-visible]:-outline-offset-2 has-[[data-link=task]:focus-visible]:outline-focus"
      onClick={openTask}
      onAuxClick={openTaskAside}
    >
      <th scope="row" className="px-3 text-left font-normal font-mono text-mark text-faint">
        {task.key}
      </th>
      <td className="max-w-0 overflow-hidden px-3">
        {/*
         * Родитель стоит в ячейке названия, справа, а не своим столбцом (UI-119): у
         * большинства строк родителя нет, и столбец под него стоял бы пустым, отнимая
         * ширину у названия. Справа — чтобы подписи родителей читались сверху вниз
         * одной полосой, а начало названия у всех строк стояло на одном месте.
         * В одну строку с названием: высота строки задана токеном и от подписи не
         * растёт (решение Д4). Подпись берёт не больше двух пятых ячейки, остальное
         * — название; тесно обоим, и многоточием уступают оба.
         */}
        <div className="flex items-center gap-3">
          <Link
            data-link="task"
            className="min-w-0 flex-1 text-text no-underline [-webkit-user-drag:none] hover:underline focus-visible:outline-none"
            to={href}
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
          <TaskParents parents={task.parents ?? []} className="max-w-2/5 shrink-0" />
        </div>
      </td>
      <td className="px-3">
        <StatusMark status={task.status} />
      </td>
      <td className="px-3 text-mark text-faint">
        {task.assignee === null || task.assignee === undefined ? (
          <span aria-hidden="true">—</span>
        ) : (
          /* Курсор текстовый: имя исполнителя из списка выделяют и копируют, и рука
             над ним обещала бы, что здесь нечего выделять. Мишенью оно при этом
             остаётся — обработчик строки отличает выделение от клика. */
          <span className="cursor-text">{task.assignee}</span>
        )}
      </td>
      <td className="px-3">
        <PriorityMark priority={task.priority} />
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
          <span aria-hidden="true">{t('task.emptyCase')}</span>
        ) : (
          <RelativeTime value={activity} />
        )}
      </td>
    </tr>
  );
}
