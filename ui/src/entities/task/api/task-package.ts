import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

/** Пакет преемника: всё, чем рисуется карточка, одним ответом. */
export type TaskPackage = components['schemas']['TaskPackageRead'];
export type TaskDetails = components['schemas']['TaskRead'];
export type TaskLink = components['schemas']['TaskLinkRead'];
export type LinkKind = components['schemas']['LinkKind'];

export const taskPackageKeys = {
  package: (key: string) => ['task', key] as const,
};

/**
 * Один запрос на открытие карточки: карточка, связи, признаки, последняя сводка,
 * открытые вопросы, опись и переходы (`../tracker/docs/FRONTEND.md`, «Карточка задачи
 * одним запросом»). Тела остальных записей подгружаются по клику, в `entities/entry`.
 */
export function taskPackageQueryOptions(key: string) {
  return queryOptions({
    queryKey: taskPackageKeys.package(key),
    queryFn: (): Promise<TaskPackage> =>
      unwrap(apiClient.GET('/api/v1/tasks/{task_key}', { params: { path: { task_key: key } } })),
  });
}
