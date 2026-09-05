import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components } from '@/shared/api';

/** Запись дела с телом и нагрузкой: объединение, размеченное полем `type`. */
export type Entry = components['schemas']['EntryRead'];

/** Строка описи: заголовок записи без тела. */
export type EntryHeading = components['schemas']['EntryHeadingRead'];

export type EntryType = components['schemas']['EntryType'];
export type Author = components['schemas']['AuthorRead'];

export const entryKeys = {
  /** Ключ пакета карточки живёт в `entities/task`; здесь только тела. */
  bodies: (taskKey: string, nos: number[]) => ['task', taskKey, 'entries', nos] as const,
};

/**
 * Тела названных записей одним запросом.
 *
 * Номера — часть ключа запроса, поэтому раскрытая запись читается один раз и живёт
 * в кэше: закрыть и открыть её снова второго запроса не стоит.
 */
export function entryQueryOptions(taskKey: string, no: number) {
  return queryOptions({
    queryKey: entryKeys.bodies(taskKey, [no]),
    queryFn: (): Promise<Page<Entry>> =>
      unwrapPage(
        apiClient.GET('/api/v1/tasks/{task_key}/entries', {
          params: { path: { task_key: taskKey }, query: { nos: [no] } },
        }),
      ),
    select: (page: Page<Entry>) => page.items[0] ?? null,
  });
}
