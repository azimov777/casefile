import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { readFilters, writeFilters, type TaskFilters } from './filters';

export interface TaskFiltersControl {
  filters: TaskFilters;
  /** Меняет условия. Курсор сбрасывается: страница чужого отбора ничего не значит. */
  apply: (changes: Partial<TaskFilters>) => void;
  /** Следующая страница по `meta.next_cursor`. */
  goToPage: (cursor: string) => void;
  reset: () => void;
}

/**
 * Отбор как состояние адреса. Своего состояния у списка нет вовсе: перезагрузка
 * страницы и открытая по ссылке вкладка обязаны показать одно и то же.
 *
 * Правка условий заменяет запись в истории, а «ещё» добавляет новую. Иначе одно
 * нажатие «назад» после трёх страниц выдачи уводило бы со списка вовсе, а каждая
 * буква, набранная в поле текста, оставляла бы в истории свой след.
 */
export function useTaskFilters(): TaskFiltersControl {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const apply = useCallback(
    (changes: Partial<TaskFilters>) => {
      setSearchParams(
        (previous) => writeFilters({ ...readFilters(previous), ...changes, cursor: '' }),
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const goToPage = useCallback(
    (cursor: string) => {
      setSearchParams((previous) => writeFilters({ ...readFilters(previous), cursor }));
    },
    [setSearchParams],
  );

  const reset = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  return { filters, apply, goToPage, reset };
}
