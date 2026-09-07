import { Fragment, type RefObject } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router';
import { PanelLeft } from 'lucide-react';
import { ViewSwitch, readFilters, tasksHref } from '@/features/task-filters';
import { cn } from '@/shared/lib';
import { readPlace, type Place } from './place';

/**
 * Верхняя полоса: где человек находится и как он на это смотрит.
 *
 * Разделов здесь нет — они в боковой панели (решение Д25). Полоса отвечает на другой
 * вопрос: «что я сейчас вижу и каким видом». Пока раздел и вид стояли соседями в одной
 * строке, ссылка вида собирала адрес с нуля и теряла отбор — дефект UI-22.
 */
export function AppTopbar({
  openerRef,
  onOpenSide,
}: {
  openerRef: RefObject<HTMLButtonElement | null>;
  onOpenSide: () => void;
}) {
  const [searchParams] = useSearchParams();
  const { pathname } = useLocation();
  const place = readPlace(pathname, searchParams);
  const filters = readFilters(searchParams);

  return (
    <header className="flex h-(--ui-topbar) items-center gap-2 border-b border-line bg-surface px-3">
      {/*
       * Кнопка панели живёт только на узком экране: на широком панель на месте, и
       * кнопка «показать разделы» показывала бы то, что и так видно (решение Д27).
       * Скрыта `hidden`, а не `display:none` через медиазапрос в другом файле, — чтобы
       * условие стояло там же, где кнопка.
       */}
      <button
        ref={openerRef}
        type="button"
        aria-label="Показать разделы"
        onClick={onOpenSide}
        className={cn(
          'grid size-7 shrink-0 place-items-center rounded-control border border-line-strong text-muted',
          'transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          'fold:hidden',
        )}
      >
        <PanelLeft className="size-(--ui-mark)" aria-hidden="true" />
      </button>

      <Crumbs place={place} />

      {/* Вид переключается только там, где он есть, — на списке задач (решение Д26). */}
      {place.section === 'tasks' ? (
        <div className="ml-auto">
          <ViewSwitch view={filters.view} />
        </div>
      ) : null}
    </header>
  );
}

/**
 * Где человек находится, словами: очередь, раздел и — внутри задачи — её ключ.
 *
 * Не `nav`, а `p` с `aria-label`: это не набор ссылок для перехода, а ответ на вопрос
 * «где я». Ссылкой здесь становится только то, откуда человек пришёл и куда вернётся.
 */
function Crumbs({ place }: { place: Place }) {
  const parts = crumbsOf(place);

  return (
    <p className="flex min-w-0 items-center gap-1.5 text-meta text-muted" aria-label="Где я">
      {parts.map((part, index) => (
        <Fragment key={part.label}>
          {index === 0 ? null : (
            <span aria-hidden="true" className="text-line-strong">
              /
            </span>
          )}
          {part.to === undefined ? (
            <span className={cn('truncate', part.mono ? 'font-mono text-text' : '')}>
              {part.label}
            </span>
          ) : (
            <Link
              to={part.to}
              className={cn(
                'truncate text-muted no-underline hover:text-accent hover:underline',
                part.mono ? 'font-mono' : '',
              )}
            >
              {part.label}
            </Link>
          )}
        </Fragment>
      ))}
    </p>
  );
}

interface Crumb {
  label: string;
  /** Ссылка — только у того, куда человек может вернуться. Текущее место не ссылка. */
  to?: string;
  mono?: boolean;
}

function crumbsOf(place: Place): Crumb[] {
  if (place.section === 'questions') return [{ label: 'Входящая' }];

  const queue: Crumb =
    place.queue === null
      ? { label: 'Все задачи' }
      : { label: place.queue, mono: true, to: tasksHref('', { queue: place.queue }) };

  if (place.section === 'tasks') {
    // На самом списке очередь — уже текущее место: ссылка вела бы туда же, откуда
    // человек смотрит, и по дороге стирала бы остальной отбор.
    return [{ ...queue, to: undefined }, { label: 'Задачи' }];
  }

  if (place.taskKey === null) return [queue];

  const task: Crumb = {
    label: place.taskKey,
    mono: true,
    to: place.section === 'case' ? `/tasks/${place.taskKey}` : undefined,
  };

  return place.section === 'case'
    ? [queue, task, { label: 'Дело' }]
    : [queue, { ...task, to: undefined }];
}
