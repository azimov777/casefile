import { useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { tasksQueryOptions, tasksTotalQueryOptions, type Task } from '@/entities/task';
import {
  TaskFiltersForm,
  filtersToListParams,
  hasConditions,
  readQueryProblem,
  useTaskFilters,
} from '@/features/task-filters';
import { UpdatesBar } from '@/features/live-journal';
import { type Page } from '@/shared/api';
import { Button, Callout, QueryState, type QueryLike } from '@/shared/ui';
import { TasksBoard } from './tasks-board';
import { TasksPagination } from './tasks-pagination';
import { TasksTable } from './tasks-table';

/**
 * Список задач в двух режимах: таблицей и доской по столбцам статусов. Строка выдачи
 * у них одна и та же, с признаками прямо в ней (`../tracker/docs/FRONTEND.md`,
 * «Строка списка»), а вот читают они по-разному: таблица берёт страницу целиком,
 * а на доске каждый столбец читает свой отбор сам (UI-70). Экран поэтому держит для
 * доски только её число — сколько задач нашлось по отбору.
 *
 * Своего состояния у экрана нет: отбор, режим и номер страницы живут в адресе.
 */
export function TasksPage() {
  const { filters, apply, reset } = useTaskFilters();
  const { t } = useTranslation('tasks');
  const board = filters.view === 'board';
  const params = useMemo(() => filtersToListParams(filters), [filters]);

  /*
   * Запроса всегда два, работает ровно один: хук нельзя позвать условно, а лишний
   * запрос в отключённом режиме означал бы два обращения к списку на одну отрисовку.
   *
   * У доски это запрос без задач — одна строка ради `meta.total`. Он отвечает на два
   * вопроса разом: сколько задач нашлось по отбору (ни один столбец этого не знает —
   * свёрнутый не читает вовсе) и разобрал ли бэкенд запрос, написанный человеком.
   * Второе объясняет форма отбора, и место, по которому она это делает, обязано быть
   * одно: шесть столбцов объяснили бы один и тот же отказ шесть раз.
   */
  const list = useQuery({ ...tasksQueryOptions(params), enabled: !board });
  const counted = useQuery({ ...tasksTotalQueryOptions(params), enabled: board });

  /**
   * Последняя удачная страница таблицы. Отказ разбора запроса не должен опустошать
   * таблицу: человек правит запрос, глядя на то, что нашлось до опечатки.
   * `placeholderData` этого не делает — он держит прошлые строки только на время
   * ожидания, а на отказе отдаёт пустоту.
   */
  const lastLoaded = useRef<Page<Task> | null>(null);
  if (list.data !== undefined) lastLoaded.current = list.data;
  const loaded = list.data ?? lastLoaded.current;

  const active = board ? counted : list;

  /*
   * Состояние запроса над содержимым. У таблицы это её запрос целиком, у доски —
   * запрос числа выдачи, но **без ожидания**: полоса «Загружаем задачи…», появившаяся
   * над доской и пропавшая через мгновение, сдвигает карточки в тот самый кадр,
   * в который человек в них смотрит (замерено: первая карточка `open` уезжала
   * на 58 px вверх). Своё ожидание каждый столбец рисует у себя, а отказ остаётся
   * здесь: он редок, и подвинуть ради него доску честно.
   */
  const state: QueryLike = board
    ? {
        isPending: false,
        isFetching: counted.isFetching,
        error: counted.error,
        refetch: () => void counted.refetch(),
      }
    : list;

  // Отказ разбора относится к полю запроса только тогда, когда запрос отправляли мы
  // из этого поля; негодное значение в адресе — беда всей страницы, а не поля.
  const problem =
    filters.query.trim() === '' ? null : readQueryProblem(active.error, filters.query);

  /**
   * Сколько задач нашлось по отбору. Список задач заполняет `meta.total` всегда
   * (TRK-41); `null` значит «не считали» — тогда ни числа выдачи, ни номеров страниц
   * не показывается, остаётся честное «есть ещё» по `has_more`.
   */
  const total = loaded?.meta?.total ?? null;
  const hasMore = loaded?.meta?.has_more === true;

  /*
   * Что за число стоит у заголовка — одно и то же в обоих режимах: сколько задач
   * нашлось по отбору. У доски оно раньше говорило про прочитанное и росло от нажатий
   * «Ещё»; теперь столбцы читают по мере прокрутки, и число прочитанного меняется
   * от того, куда человек доехал, — про выдачу оно не сказало бы ничего. Числа
   * по статусам стоят там, где им место: в заголовках столбцов.
   */
  const found = board ? (counted.data ?? null) : (total ?? loaded?.items.length ?? null);

  /**
   * Страница за концом выдачи: пересланная ссылка пережила сузившийся отбор. Бэкенд
   * отвечает на неё пустой страницей и прежним `total` — по нему и видно, что задачи
   * есть, просто не здесь.
   */
  const beyond = loaded?.items.length === 0 && total !== null && total > 0;

  return (
    <main className="flex flex-col gap-3">
      {/*
       * Живой поток не перестраивает список сам: он копит изменения и предлагает их
       * полосой. Полоса стоит вне потока вёрстки — строки от её появления не двигаются.
       */}
      <UpdatesBar />

      {/*
       * Заголовок, отбор и переключатель режима — одной строкой. Тремя блоками друг
       * под другом они уводили первую строку таблицы на 415-й пиксель: из двадцати
       * одной задачи на экране оставалось семь.
       *
       * Выравнивание по верху, а не по центру: развёрнутая форма растёт вниз внутри
       * своей колонки и не тянет за собой заголовок с переключателем.
       */}
      <div className="flex flex-wrap items-start gap-3">
        <h1 className="flex items-baseline gap-2 text-screen leading-[1.9]">
          {t('title')}
          {/*
           * Число выдачи стоит здесь, а не полосой над таблицей. Из имени заголовка оно
           * скрыто: то же число программа чтения с экрана берёт из области ниже
           * («Найдено задач: 98»), а «Задачи 98» вместо «Задачи» ломало бы навигацию
           * по заголовкам. Подпись таблицы говорит своё и другое — сколько строк
           * на этой странице.
           */}
          {found === null ? null : (
            <span className="text-label font-normal text-muted" aria-hidden="true">
              {found}
            </span>
          )}
        </h1>
        {/*
         * Колонка отбора занимает всё, что осталось от заголовка, но не меньше 24rem
         * (`basis-96`). `min-w-0` обязателен: без него элемент гибкой раскладки не
         * сжимается меньше своего содержимого, и при увеличенном вдвое тексте основа
         * в 24rem становится шире узкого экрана — строка условий расширяет документ
         * вместо того, чтобы перенестись.
         */}
        <div className="min-w-0 grow basis-96">
          <TaskFiltersForm filters={filters} onApply={apply} onReset={reset} problem={problem} />
        </div>
      </div>

      {/*
       * Смена отбора объявляется вслух: человек с программой чтения с экрана иначе
       * не узнаёт, что выдача пересобралась, — фокус остался на чипе или флажке, а
       * таблица под ним стала другой. Область постоянная: `aria-live` объявляет только
       * то, что появилось внутри уже существующего контейнера.
       */}
      <p aria-live="polite" className="sr-only">
        {found === null ? '' : t('found', { count: found })}
      </p>

      {/*
       * Отказ разбора запроса объясняет форма, у самого поля: там же сказано и то,
       * что в таблице остались строки предыдущего отбора. Полосы над таблицей нет
       * намеренно — она сдвигала бы строки вниз ровно тогда, когда человек правит
       * запрос и сверяется с ними. Всё остальное — общее состояние запроса с повтором.
       */}
      {problem === null ? <QueryState query={state} loading={t('loading')} /> : null}

      {board ? (
        <TasksBoard
          params={params}
          explained={problem !== null}
          collapsed={filters.collapsed}
          onToggle={(status, open) =>
            apply({
              collapsed: open
                ? filters.collapsed.filter((value) => value !== status)
                : [...filters.collapsed, status],
            })
          }
        />
      ) : loaded === null ? null : loaded.items.length === 0 ? (
        /*
         * Пустая страница бывает двух разных бед, и путать их нельзя: по этим условиям
         * задач нет вовсе — или они есть, но кончились раньше этой страницы. Второе
         * лечится не сбросом отбора, а возвратом на существующую страницу, и ряд
         * страниц под сообщением как раз туда и ведёт.
         */
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            {beyond ? (
              <Callout>{t('beyond', { count: total ?? 0 })}</Callout>
            ) : (
              <>
                <Callout>{t('empty')}</Callout>
                <Button tone="quiet" onClick={reset} disabled={!hasConditions(filters)}>
                  {t('resetFilters')}
                </Button>
              </>
            )}
          </div>
          <TasksPagination page={filters.page} total={total} hasMore={hasMore} />
        </div>
      ) : (
        <>
          <TasksTable tasks={loaded.items} stale={list.isFetching || problem !== null} />

          <TasksPagination page={filters.page} total={total} hasMore={hasMore} />
        </>
      )}
    </main>
  );
}
