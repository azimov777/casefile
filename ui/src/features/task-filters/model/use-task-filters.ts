import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { EMPTY_FILTERS, readFilters, writeFilters, type TaskFilters } from './filters';

export interface TaskFiltersControl {
  filters: TaskFilters;
  /** Меняет условия. Номер страницы сбрасывается: страница чужого отбора ничего не значит. */
  apply: (changes: Partial<TaskFilters>) => void;
  reset: () => void;
}

/**
 * Отбор как состояние адреса. Своего состояния у списка нет вовсе: перезагрузка
 * страницы и открытая по ссылке вкладка обязаны показать одно и то же.
 *
 * Правка условий заменяет запись в истории. Иначе каждая буква, набранная в поле
 * текста, оставляла бы в истории свой след. Переход по страницам запись добавляет,
 * и делает это сам браузер: страницы — обычные ссылки (`src/pages/tasks/ui/tasks-pagination.tsx`),
 * и «назад» после них возвращает на прежнюю страницу выдачи.
 */
export function useTaskFilters(): TaskFiltersControl {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const apply = useCallback(
    (changes: Partial<TaskFilters>) => {
      setSearchParams(
        (previous) => writeFilters({ ...readFilters(previous), page: 1, ...changes }),
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /**
   * Сброс снимает условия, но не место: очередь и вид остаются. Человек просил
   * показать всё, а не унести себя из очереди, в которую он пришёл (UI-38).
   *
   * Показ архива тоже остаётся (UI-97): «сбросить» значит «показать больше», а
   * вернуть умолчание архива значило бы, нажав его, увидеть меньше.
   */
  const reset = useCallback(() => {
    setSearchParams(
      (previous) => {
        const { queue, view, showArchive } = readFilters(previous);
        return writeFilters({ ...EMPTY_FILTERS, queue, view, showArchive });
      },
      { replace: true },
    );
  }, [setSearchParams]);

  return { filters, apply, reset };
}
