import { useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { tasksQueryOptions, type Task } from '@/entities/task';
import {
  TaskFiltersForm,
  filtersToListParams,
  hasConditions,
  readQueryProblem,
  useTaskFilters,
} from '@/features/task-filters';
import { ApiError, type Page } from '@/shared/api';
import { errorText } from '@/shared/errors';
import { Button, Callout } from '@/shared/ui';
import { TasksTable } from './tasks-table';
import styles from './tasks-page.module.css';

/**
 * Список задач: один запрос на страницу выдачи и ни одного на строку — признаки
 * приезжают в самой строке (`../tracker/docs/FRONTEND.md`, «Строка списка»).
 *
 * Своего состояния у экрана нет: отбор, порядок и курсор живут в адресе.
 */
export function TasksPage() {
  const { filters, apply, goToPage, reset } = useTaskFilters();
  const params = useMemo(() => filtersToListParams(filters), [filters]);
  const list = useQuery(tasksQueryOptions(params));

  /**
   * Последняя удачная страница. Отказ разбора запроса не должен опустошать таблицу:
   * человек правит запрос, глядя на то, что нашлось до опечатки. `placeholderData`
   * этого не делает — он держит прошлые строки только на время ожидания, а на отказе
   * отдаёт пустоту.
   */
  const lastLoaded = useRef<Page<Task> | null>(null);
  if (list.data !== undefined) lastLoaded.current = list.data;
  const page = list.data ?? lastLoaded.current;

  // Отказ разбора относится к полю запроса только тогда, когда запрос отправляли мы
  // из этого поля; негодное значение в адресе — беда всей страницы, а не поля.
  const problem = filters.query.trim() === '' ? null : readQueryProblem(list.error, filters.query);
  const failure = list.error !== null && problem === null ? describe(list.error) : null;

  const cursor = page?.meta?.next_cursor ?? null;
  const hasMore = page?.meta?.has_more === true && cursor !== null;

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Задачи</h1>

      <TaskFiltersForm filters={filters} onApply={apply} onReset={reset} problem={problem} />

      {failure === null ? null : <Callout tone="danger">{failure}</Callout>}

      {problem === null || page === null ? null : (
        <Callout>Показаны строки предыдущего отбора: последний запрос отклонён.</Callout>
      )}

      {page === null ? (
        list.isPending ? (
          <Callout>Загружаем задачи…</Callout>
        ) : null
      ) : page.items.length === 0 ? (
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

function describe(error: unknown): string {
  if (error instanceof ApiError) return errorText(error.code, error.message);
  return error instanceof Error ? error.message : 'Неизвестная ошибка.';
}
