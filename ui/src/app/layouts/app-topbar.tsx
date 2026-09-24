import { Fragment, type RefObject } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Link, useLocation, useSearchParams } from 'react-router';
import { PanelLeft } from 'lucide-react';
import { bootstrapQueryOptions } from '@/entities/session';
import { ViewSwitch, readFilters, tasksHref } from '@/features/task-filters';
import { LiveStatus, type LiveJournal } from '@/features/live-journal';
import { LanguageSwitch } from '@/features/switch-language';
import { cn } from '@/shared/lib';
import { Button } from '@/shared/ui';
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
  const { t } = useTranslation('ui');

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
       *
       * Шкала кнопок `Button` (UI-128), а не свой набор классов: у прежней ручной
       * кнопки фон не был назван явно, и браузер рисовал поверх неё свой `ButtonFace` —
       * тот самый серый прямоугольник со снимка (UI-137#11; `docs/notes/ui.md`,
       * «Кнопка без объявленного фона получает `ButtonFace` браузера»). Тон `quiet`
       * называет фон явно (`bg-transparent`) и размер `sm` — тот же, что у остальных
       * плотных кнопок верхней полосы (`control-size.ts`: «`sm` — ... верхняя полоса»).
       */}
      <Button
        ref={openerRef}
        tone="quiet"
        size="sm"
        /*
         * Кнопка говорит и о том, что за ней ждёт: на узком экране счётчик вопросов
         * уехал в панель вместе со всем остальным, а «меня спрашивают» — то, ради чего
         * человек вообще открывает трекер, и молчать об этом до нажатия нельзя.
         */
        // Нулевая форма подписи — это просто «показать разделы»: сказать о вопросах
        // нечего, и обходить склонение двоеточием не приходится.
        aria-label={t('app.showSections', { count: waiting })}
        onClick={onOpenSide}
        className="relative shrink-0 px-1.5 fold:hidden"
      >
        <PanelLeft className="size-(--ui-mark)" aria-hidden="true" />
        {waiting > 0 ? (
          <span
            aria-hidden="true"
            className="absolute -top-px -right-px size-2 rounded-pill bg-attention ring-2 ring-surface"
          />
        ) : null}
      </Button>

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
 * Где человек находится, словами: проект, раздел и — внутри задачи — её ключ.
 *
 * Не `nav`, а `p` с `aria-label`: это не набор ссылок для перехода, а ответ на вопрос
 * «где я». Ссылкой здесь становится только то, откуда человек пришёл и куда вернётся.
 */
function Crumbs({ place }: { place: Place }) {
  const { t } = useTranslation('ui');
  const parts = crumbsOf(place, t);

  return (
    /*
     * Основа нулевая, а рост — весь остаток (UI-134). Крошки не решают, переносить ли
     * полосу: перенос вызывает только правая группа, которой и правда не хватило места
     * (увеличенный текст, узкое окно). Если на строку не хватает самих крошек — в
     * мгновение «подключаемся», самое длинное из состояний потока, — они уступают
     * многоточием, а не уводят вниз всю правую группу, чтобы вернуть её через секунду.
     */
    <p
      className="flex min-w-0 grow basis-0 items-center gap-1.5 text-meta text-muted"
      aria-label={t('app.whereAmI')}
    >
      {parts.map((part, index) => (
        <Fragment key={part.label}>
          {index === 0 ? null : (
            <span
              aria-hidden="true"
              className={cn('text-line-strong', part.wide && 'max-fold:hidden')}
            >
              /
            </span>
          )}
          {part.to === undefined ? (
            <span
              className={cn(
                'truncate',
                part.mono ? 'font-mono text-text' : '',
                part.wide && 'max-fold:hidden',
              )}
            >
              {part.label}
            </span>
          ) : (
            <Link
              to={part.to}
              className={cn(
                'truncate text-muted no-underline hover:text-accent hover:underline',
                part.mono ? 'font-mono' : '',
                /*
                 * Минимум и высоты, и ширины — только на телефоне (`max-fold:`):
                 * крошка «UI» (ключ проекта из двух знаков, моноширинным) мерилась
                 * 14×18 на 390 px (UI-154). На столе крошка была бы шире своего
                 * текста, а строка — плотнее соседних, ровно то, что запрещает
                 * `ui/docs/CONCEPT.md`, §6.
                 */
                'inline-flex items-center max-fold:min-h-(--ui-tap) max-fold:min-w-(--ui-tap)',
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
  /**
   * Только выше точки остановки `fold`. Ниже неё крошка повторяла бы заголовок
   * страницы прямо под собой («Задачи»), а место в полосе нужно переключателю вида
   * (UI-134). Со ссылкой такая крошка не бывает: ссылку прятать нельзя.
   */
  wide?: boolean;
}

function crumbsOf(place: Place, t: TFunction<'ui'>): Crumb[] {
  if (place.section === 'questions') return [{ label: t('app.inbox') }];
  if (place.section === 'connect') return [{ label: t('app.connect') }];
  if (place.section === 'access') return [{ label: t('app.access') }];
  if (place.section === 'people') return [{ label: t('app.people') }];
  if (place.section === 'account') return [{ label: t('app.account') }];

  const project: Crumb =
    place.project === null
      ? { label: t('app.allTasks') }
      : { label: place.project, mono: true, to: tasksHref('', { project: place.project }) };

  if (place.section === 'tasks') {
    // На самом списке проект — уже текущее место: ссылка вела бы туда же, откуда
    // человек смотрит, и по дороге стирала бы остальной отбор.
    return [
      { ...project, to: undefined },
      { label: t('app.crumbTasks'), wide: true },
    ];
  }

  // Экран проекта: ключ ведёт в его задачи, как и внутри задачи, а раздел назван словом.
  if (place.section === 'project') return [project, { label: t('app.crumbProject') }];

  if (place.taskKey === null) return [project];

  const task: Crumb = {
    label: place.taskKey,
    mono: true,
    to: place.section === 'case' ? `/tasks/${place.taskKey}` : undefined,
  };

  return place.section === 'case'
    ? [project, task, { label: t('app.crumbCase') }]
    : [project, { ...task, to: undefined }];
}
