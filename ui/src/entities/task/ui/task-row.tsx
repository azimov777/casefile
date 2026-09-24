import type { MouseEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { RelativeTime } from '@/shared/ui';
import { cn, listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { TaskFeatureMarks } from './feature-marks';
import { PriorityMark } from './priority-mark';
import { StatusMark } from './status-mark';
import { ParentBadge } from './parent-badge';

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
 *
 * **Там, где таблице не хватает места, та же строка — карточка** (UI-134). Ветку
 * выбирает запрос к контейнеру таблицы (`@max-list:`, порог `--container-list`,
 * `pages/tasks/ui/tasks-table.tsx`): строка становится флексом с переносом, и ячейки
 * встают в порядке разметки — ключ и название первой строкой, статус, исполнитель,
 * приоритет, признаки и активность второй. Название там не режется многоточием, а
 * переносится до трёх строк: на телефоне нет подсказки по наведению, и урезанное
 * название было бы потерей, а не плотностью. Высота там от содержимого — ритм держат
 * одинаковые поля карточек, а не токен высоты.
 */
export function TaskRow({ task, parentSlot = false }: { task: Task; parentSlot?: boolean }) {
  // Адрес списка целиком, вместе с отбором: он поедет в задачу состоянием перехода.
  const { search } = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation('ui');
  const features = task.features ?? null;
  const activity = features?.last_entry_at ?? null;
  const title = task.title ?? '';
  const unassigned = task.assignee === null || task.assignee === undefined;
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
      className={cn(
        'h-(--ui-row-height) cursor-pointer border-t border-line hover:bg-sunken has-[[data-link=task]:focus-visible]:outline-2 has-[[data-link=task]:focus-visible]:-outline-offset-2 has-[[data-link=task]:focus-visible]:outline-focus',
        /*
         * Карточка: флекс с переносом. Название берёт основой 70% строки, и справа от
         * него статусу места нет — он и всё следующее уходят второй строкой. Первая
         * карточка без верхней линии: шапки над ней на экране нет, и линия легла бы
         * второй рядом с рамкой таблицы.
         */
        '@max-list:flex @max-list:h-auto @max-list:flex-wrap @max-list:items-baseline @max-list:gap-x-3 @max-list:gap-y-1.5 @max-list:px-3 @max-list:py-2.5 @max-list:first:border-t-0',
      )}
      onClick={openTask}
      onAuxClick={openTaskAside}
    >
      {/* `whitespace-nowrap` держит ключ целым: столбец узкий, и без него браузер
          вправе перенести строку по дефису внутри ключа (UI-151). */}
      <th
        scope="row"
        className="px-3 text-left font-normal font-mono text-mark whitespace-nowrap text-faint @max-list:shrink-0 @max-list:px-0"
      >
        {task.key}
      </th>
      {/* `max-w-0` держит название в ширине столбца таблицы; в карточке столбца нет,
          и ширину задаёт основа флекса. */}
      <td className="max-w-0 overflow-hidden px-3 @max-list:max-w-none @max-list:min-w-0 @max-list:grow @max-list:basis-7/10 @max-list:px-0">
        {/*
         * Родитель стоит в ячейке названия, справа, а не своим столбцом (UI-119): у
         * большинства строк родителя нет, и столбец под него стоял бы пустым. В строке —
         * плашка с ключом, целиком родитель открывается нажатием (`ParentBadge`, UI-152).
         * Место под плашку — гнездо одной ширины у **всех** строк таблицы, если хоть у
         * одной есть родитель (`parentSlot`): так название задачи с родителем и без стоит
         * на одном месте и одной ширины, и не прыгает от строки к строке. В таблице без
         * дочерних задач гнезда нет, и название ширины не теряет.
         */}
        {/* В карточке плашка встаёт под название и только у задачи с родителем: карточки
            и так разной высоты, держать ровным нечего. */}
        <div className="flex items-center gap-3 @max-list:flex-col @max-list:items-start @max-list:gap-1">
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
            <span
              className="block truncate @max-list:line-clamp-3 @max-list:whitespace-normal @max-list:wrap-anywhere"
              title={title}
            >
              {title}
            </span>
          </Link>
          {parentSlot ? (
            <span
              className={cn(
                'flex w-(--ui-parent-slot) shrink-0 justify-end @max-list:w-auto @max-list:max-w-full @max-list:justify-start',
                (task.parents ?? []).length === 0 && '@max-list:hidden',
              )}
            >
              <ParentBadge parents={task.parents ?? []} childKey={task.key} />
            </span>
          ) : null}
        </div>
      </td>
      <td className="px-3 @max-list:px-0">
        <StatusMark status={task.status} />
      </td>
      {/* Пустой исполнитель в карточке не рисуется вовсе: прочерк между знаками
          статуса и приоритета читался бы как разделитель, а не как «никого». */}
      <td
        className={cn('px-3 text-mark text-faint @max-list:px-0', unassigned && '@max-list:hidden')}
      >
        {unassigned ? (
          <span aria-hidden="true">—</span>
        ) : (
          /* Курсор текстовый: имя исполнителя из списка выделяют и копируют, и рука
             над ним обещала бы, что здесь нечего выделять. Мишенью оно при этом
             остаётся — обработчик строки отличает выделение от клика. */
          <span className="cursor-text">{task.assignee}</span>
        )}
      </td>
      <td className="px-3 @max-list:px-0">
        <PriorityMark priority={task.priority} />
      </td>
      <td className="px-3 @max-list:px-0">
        <span className="flex items-center gap-2">
          {features === null ? null : <TaskFeatureMarks features={features} />}
        </span>
      </td>
      {/* Единственное время в строке: когда в дело последний раз что-то подшивали.
          `updated_at` отсюда убран — он двигался и от правки карточки, и человек
          не мог сказать, чем два относительных времени в соседних ячейках различаются. */}
      {/* В карточке активность прижата вправо второй строки — туда же, где она стоит
          в таблице. */}
      <td className="px-3 text-right text-mark text-faint whitespace-nowrap @max-list:ml-auto @max-list:px-0">
        {activity === null ? (
          <span aria-hidden="true">{t('task.emptyCase')}</span>
        ) : (
          <RelativeTime value={activity} plain />
        )}
      </td>
    </tr>
  );
}
