import { Fragment, type RefObject } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useSearchParams } from 'react-router';
import { PanelLeft } from 'lucide-react';
import { bootstrapQueryOptions } from '@/entities/session';
import { ViewSwitch, readFilters, tasksHref } from '@/features/task-filters';
import { LiveStatus, type LiveJournal } from '@/features/live-journal';
import { LanguageSwitch } from '@/features/switch-language';
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
  live,
  openerRef,
  onOpenSide,
}: {
  live: LiveJournal;
  openerRef: RefObject<HTMLButtonElement | null>;
  onOpenSide: () => void;
}) {
  const [searchParams] = useSearchParams();
  const { pathname } = useLocation();
  const place = readPlace(pathname, searchParams);
  const filters = readFilters(searchParams);
  const bootstrap = useQuery(bootstrapQueryOptions());
  const waiting = bootstrap.data?.open_questions ?? 0;

  return (
    /*
     * Высота минимальная, а не заданная, и строка переносится: при увеличении текста
     * до 200 % содержимое обязано опустить полосу вниз, а не уехать за край. Сочетание
     * `height` с непереносимой строкой — ровно то, из-за чего шапка на 390 px уводила
     * счётчик и выход за правый край документа (UI-23).
     */
    <header className="flex min-h-(--ui-topbar) flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-surface px-3 py-1">
      {/*
       * Кнопка панели живёт только на узком экране: на широком панель на месте, и
       * кнопка «показать разделы» показывала бы то, что и так видно (решение Д27).
       * Скрыта `hidden`, а не `display:none` через медиазапрос в другом файле, — чтобы
       * условие стояло там же, где кнопка.
       */}
      <button
        ref={openerRef}
        type="button"
        /*
         * Кнопка говорит и о том, что за ней ждёт: на узком экране счётчик вопросов
         * уехал в панель вместе со всем остальным, а «меня спрашивают» — то, ради чего
         * человек вообще открывает трекер, и молчать об этом до нажатия нельзя.
         */
        aria-label={
          waiting > 0 ? `Показать разделы, открытых вопросов: ${waiting}` : 'Показать разделы'
        }
        onClick={onOpenSide}
        className={cn(
          'relative grid size-9 shrink-0 place-items-center rounded-control border border-line-strong text-muted',
          'transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          'fold:hidden',
        )}
      >
        <PanelLeft className="size-(--ui-mark)" aria-hidden="true" />
        {waiting > 0 ? (
          <span
            aria-hidden="true"
            className="absolute -top-px -right-px size-2 rounded-pill bg-attention ring-2 ring-surface"
          />
        ) : null}
      </button>

      <Crumbs place={place} />

      {/* Вид переключается только там, где он есть, — на списке задач (решение Д26). */}
      {/*
       * Правая группа переносится вместе с полосой: при увеличенном тексте
       * переключатель вида и состояние потока вдвоём шире узкого экрана, и без
       * переноса они уезжали за правый край, расширяя документ.
       */}
      <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-3 gap-y-1">
        {place.section === 'tasks' ? <ViewSwitch view={filters.view} /> : null}

        {/*
         * Язык живёт в полосе, а не в боковой панели: на узком экране панель уезжает
         * за кнопку, и переключатель был бы доступен через два действия — а на экране
         * входа панели нет вовсе, и человек искал бы его в двух разных местах. Полоса
         * есть на всех экранах оболочки, и это то же место, что и на входе, — верхний
         * правый угол.
         */}
        <LanguageSwitch />

        {/*
         * Свежесть показанного (`CONCEPT.md`, 5) стоит здесь, а не в подвале панели, как
         * в эталоне: на узком экране панель уезжает за кнопку, и «нет связи» человек
         * узнавал бы, только открыв её, — то есть ровно тогда, когда он уже поверил
         * устаревшему экрану. Место одно на обе ширины, второго нет.
         */}
        <LiveStatus status={live.status} />
      </div>
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
