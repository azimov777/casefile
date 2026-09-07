import { useMemo, useRef } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { tasksBoardQueryOptions, tasksQueryOptions, type Task } from '@/entities/task';
import {
  TaskFiltersForm,
  filtersToListParams,
  hasConditions,
  readQueryProblem,
  useTaskFilters,
} from '@/features/task-filters';
import { UpdatesBar } from '@/features/live-journal';
import { type Page } from '@/shared/api';
import { Button, Callout, QueryState } from '@/shared/ui';
import { TasksBoard } from './tasks-board';
import { TasksTable } from './tasks-table';
import { ViewSwitch } from './view-switch';
import styles from './tasks-page.module.css';

/**
 * Список задач в двух режимах: таблицей и доской по столбцам статусов. Данные у них
 * одни и те же — один запрос `GET /api/v1/tasks` с признаками прямо в строке
 * (`../tracker/docs/FRONTEND.md`, «Строка списка»).
 *
 * Своего состояния у экрана нет: отбор, режим и курсор живут в адресе.
 */
export function TasksPage() {
  const { filters, apply, goToPage, reset } = useTaskFilters();
  const board = filters.view === 'board';
  const params = useMemo(() => filtersToListParams(filters), [filters]);

  // Запроса всегда два, работает ровно один: хук нельзя позвать условно, а лишний
  // запрос в отключённом режиме означал бы два обращения к списку на одну отрисовку.
  const list = useQuery({ ...tasksQueryOptions(params), enabled: !board });
  const pages = useInfiniteQuery({ ...tasksBoardQueryOptions(params), enabled: board });

  /**
   * Последняя удачная страница таблицы. Отказ разбора запроса не должен опустошать
   * таблицу: человек правит запрос, глядя на то, что нашлось до опечатки.
   * `placeholderData` этого не делает — он держит прошлые строки только на время
   * ожидания, а на отказе отдаёт пустоту.
   */
  const lastLoaded = useRef<Page<Task> | null>(null);
  if (list.data !== undefined) lastLoaded.current = list.data;
  const page = list.data ?? lastLoaded.current;

  const active = board ? pages : list;

  // Отказ разбора относится к полю запроса только тогда, когда запрос отправляли мы
  // из этого поля; негодное значение в адресе — беда всей страницы, а не поля.
  const problem =
    filters.query.trim() === '' ? null : readQueryProblem(active.error, filters.query);

  const cursor = page?.meta?.next_cursor ?? null;
  const hasMore = page?.meta?.has_more === true && cursor !== null;

  const boardTasks = pages.data?.pages.flatMap((chunk) => chunk.items) ?? [];

  // Сколько строк показано сейчас: у доски это всё прочитанное, у таблицы — страница.
  const shown = board
    ? pages.data === undefined
      ? null
      : boardTasks.length
    : (page?.items.length ?? null);

  return (
    <main className={styles.screen}>
      {/*
       * Живой поток не перестраивает список сам: он копит изменения и предлагает их
       * полосой. Полоса стоит вне потока вёрстки — строки от её появления не двигаются.
       */}
      <UpdatesBar />

      {/*
       * Заголовок, отбор и переключатель режима — одной строкой. Тремя блоками друг
       * под другом они уводили первую строку таблицы на 415-й пиксель: из двадцати
       * одной задачи на экране оставалось семь.
       */}
      <div className={styles.top}>
        <h1 className={styles.heading}>
          Задачи
          {/*
           * Число выдачи стоит здесь, а не полосой над таблицей. Из имени заголовка оно
           * скрыто: то же число программа чтения с экрана берёт из подписи таблицы,
           * а «Задачи 21» вместо «Задачи» ломало бы навигацию по заголовкам.
           */}
          {shown === null ? null : (
            <span className={styles.count} aria-hidden="true">
              {shown}
            </span>
          )}
        </h1>
        <div className={styles.filters}>
          <TaskFiltersForm filters={filters} onApply={apply} onReset={reset} problem={problem} />
        </div>
        <ViewSwitch view={filters.view} onChange={(view) => apply({ view })} />
      </div>

      {/*
       * Смена отбора объявляется вслух: человек с программой чтения с экрана иначе
       * не узнаёт, что выдача пересобралась, — фокус остался на чипе или флажке, а
       * таблица под ним стала другой. Область постоянная: `aria-live` объявляет только
       * то, что появилось внутри уже существующего контейнера.
       */}
      <p aria-live="polite" className="sr-only">
        {shown === null ? '' : `Показано задач: ${shown}`}
      </p>

      {/*
       * Отказ разбора запроса объясняет форма, у самого поля: там же сказано и то,
       * что в таблице остались строки предыдущего отбора. Полосы над таблицей нет
       * намеренно — она сдвигала бы строки вниз ровно тогда, когда человек правит
       * запрос и сверяется с ними. Всё остальное — общее состояние запроса с повтором.
       */}
      {problem === null ? <QueryState query={active} loading="Загружаем задачи…" /> : null}

      {board ? (
        pages.data === undefined ? null : (
          <TasksBoard
            tasks={boardTasks}
            hasMore={pages.hasNextPage}
            loadingMore={pages.isFetchingNextPage}
            onMore={() => void pages.fetchNextPage()}
            collapsed={filters.collapsed}
            onToggle={(status, open) =>
              apply({
                collapsed: open
                  ? filters.collapsed.filter((value) => value !== status)
                  : [...filters.collapsed, status],
              })
            }
          />
        )
      ) : page === null ? null : page.items.length === 0 ? (
        <div className={styles.empty}>
          <Callout>Задач по этим условиям нет</Callout>
          <Button tone="quiet" onClick={reset} disabled={!hasConditions(filters)}>
            Сбросить фильтры
          </Button>
        </div>
      ) : (
        <>
          <TasksTable tasks={page.items} stale={list.isFetching || problem !== null} />

          <div className={styles.paging}>
            {hasMore ? <Button onClick={() => goToPage(cursor)}>Ещё</Button> : null}
            {filters.cursor === '' ? null : (
              <Button tone="quiet" onClick={() => apply({})}>
                В начало списка
              </Button>
            )}
            {hasMore ? null : <span className={styles.end}>Это последняя страница.</span>}
          </div>
        </>
      )}
    </main>
  );
}
