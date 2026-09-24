import { Link, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Badge, RelativeTime } from '@/shared/ui';
import { listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { Task } from '../api/tasks';
import { hasFeatureBadges } from './feature-badges';
import { PriorityMark } from './priority-mark';
import { TaskFeatureMarks } from './feature-marks';
import { TaskParents } from './task-parents';

/**
 * Задача карточкой: то же, что строка списка, но в один столбец. Признаки берутся
 * из той же выдачи, поэтому запроса на карточку нет.
 *
 * Кликабельна целиком: настоящая ссылка в задачу одна, на названии, а на всю карточку
 * её растягивает псевдоэлемент. Строка списка этот приём отменила (UI-39), карточка —
 * нет: `position: relative` в WebKit не создаёт containing block только у
 * `display: table-row`, а карточка — обычный блочный `article`, и `inset: 0` считается
 * от неё. Перетаскивания нет и не будет: статусы двигают агенты (`CONCEPT.md`, 7).
 *
 * Вторая ссылка бывает только у задачи с родителем: она ведёт в родителя и поднята
 * над растяжкой (UI-119).
 */
export function TaskCard({ task }: { task: Task }) {
  const { search } = useLocation();
  const features = task.features ?? null;
  const { t } = useTranslation('ui');

  return (
    /*
     * `relative` — точка отсчёта для растянутой ссылки: `after:inset-0` считается отсюда.
     *
     * Рамка и заливка меняются под курсором: видно, какая карточка под ним, — на доске
     * их десятки в шести столбцах.
     */
    <article className="relative flex flex-col gap-2 rounded-mark border border-line bg-surface p-3 transition-[border-color,background-color] duration-(--motion-fast) ease-fast hover:border-line-strong hover:bg-sunken">
      {/*
       * Родитель — первой строкой, над ключом (UI-119): по нему доска с десятками
       * карточек читается программами, и задачу для этого открывать не надо. Одна
       * строка с многоточием: название ниже по-прежнему занимает свои две (Д21),
       * а столбец не ширится от длинного названия родителя (UI-115). Ссылка поднята
       * над растяжкой и ведёт в родителя; остальная карточка — в саму задачу.
       * У задачи верхнего уровня строки нет вовсе.
       */}
      <TaskParents parent={task.parent} raised />

      <div className="flex items-center justify-between gap-2">
        {/* Ключ не поднят над растяжкой: клик по нему ведёт в ту же задачу.
            `whitespace-nowrap` держит его целым на переносе (UI-151). */}
        <span className="font-mono text-meta whitespace-nowrap">{task.key}</span>
        <PriorityMark priority={task.priority} withName={false} />
      </div>

      {/*
       * Название занимает не больше двух строк (решение Д21): раньше оно переносилось
       * по три-четыре, и подвал с исполнителем и признаками вставал на разной высоте
       * от карточки к карточке — карточки переставали сравниваться взглядом.
       *
       * Обрезанное отдаётся целиком подсказкой: обрезание без доступа к скрытому было бы
       * потерей данных.
       *
       * `wrap-anywhere` (`overflow-wrap: anywhere`) — не украшение переноса, а снятие
       * пола ширины. Названия задач этого трекера полны путей и имён из контракта
       * (`ui/src/pages/tasks/ui/tasks-board.tsx`), а такое слово не переносится нигде:
       * ни пробела, ни дефиса внутри. Обычный `break-word` разрывает слово при отрисовке,
       * но `min-content` элемента не уменьшает — а именно `min-content` карточки задавал
       * ширину столбцу доски и разводил его вбок (UI-115). `anywhere` уменьшает и его,
       * поэтому длинное слово переносится внутри двух строк, а не вылезает за карточку.
       */}
      <p className="line-clamp-2 leading-[1.35] wrap-anywhere" title={task.title ?? ''}>
        <Link
          /*
           * Ссылку нельзя перетаскивать: иначе протяжка мышью по названию таскала бы её
           * адрес вместо того, чтобы выделять текст. Атрибута `draggable="false"` для
           * этого мало — у Chromium своё правило `-webkit-user-drag`, и по умолчанию
           * оно у ссылок «тащить элемент».
           *
           * Растяжка и обводка фокуса живут на одном псевдоэлементе: обводка обязана
           * обойти карточку целиком, а не одну строку названия, — поэтому собственная
           * обводка ссылки снята.
           */
          className="text-text no-underline [-webkit-user-drag:none] after:absolute after:inset-0 after:rounded-mark after:content-[''] hover:underline focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-offset-1 focus-visible:after:outline-focus"
          to={taskRefHref({ key: task.key, entryNo: null })}
          // Отбор, с которым человек смотрел список, едет с ним в задачу: обратно
          // он вернётся к тем же строкам, а не ко всем задачам очереди.
          state={listReturnState(search)}
          draggable={false}
          onClick={skipClickWhileSelecting}
        >
          {/* Поднятое над растяжкой (`relative z-1`) выделяется мышью как текст, но
              мишенью быть перестаёт: это цена приёма, и она названа заметкой
              «Растянутая ссылка: мишень надо делить» в `docs/notes/ui.md`. */}
          <span className="relative z-1">{task.title ?? ''}</span>
        </Link>
      </p>

      {/* Подвал прижат к низу: у карточек столбца он стоит на одном расстоянии от края. */}
      <div className="mt-auto flex flex-wrap items-center gap-2 text-meta text-muted">
        {task.assignee === null || task.assignee === undefined ? (
          <span className="italic">{t('task.cardUnassigned')}</span>
        ) : (
          <Badge mono>
            <span className="relative z-1">{task.assignee}</span>
          </Badge>
        )}
        {/* То же время, что в строке списка: активность в деле, а не правка карточки. */}
        {features?.last_entry_at === null || features?.last_entry_at === undefined ? (
          <span className="italic">{t('task.emptyCase')}</span>
        ) : (
          <RelativeTime value={features.last_entry_at} plain />
        )}
      </div>

      {features === null || !hasFeatureBadges(features) ? null : (
        <div className="flex flex-wrap items-center gap-2 text-meta text-muted">
          <TaskFeatureMarks features={features} />
        </div>
      )}
    </article>
  );
}
