import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

/** Пакет преемника: всё, чем рисуется карточка, одним ответом. */
export type TaskPackage = components['schemas']['TaskPackageRead'];
/** Блок «Сейчас» пакета: считается при чтении, не хранится (`state`, TRK-579). */
export type TaskState = components['schemas']['TaskStateRead'];
export type TaskDetails = components['schemas']['TaskRead'];
export type TaskLink = components['schemas']['TaskLinkRead'];
export type LinkKind = components['schemas']['LinkKind'];
/** Задача на другом конце связи: ключ, название, статус. Так приходят `parent` и `children`. */
export type LinkedTask = components['schemas']['LinkTaskRead'];
/**
 * Решение проекта, на которое опирается задача (`decisions` пакета, TRK-554): ссылка,
 * заголовок, статус от бэкенда и, у заменённого, преемник со своим статусом.
 */
export type CitedDecision = components['schemas']['CitedDecisionRead'];

export const taskPackageKeys = {
  package: (key: string) => ['task', key] as const,
};

/**
 * Один запрос на открытие карточки: карточка, связи, признаки, последняя сводка,
 * открытые вопросы, опись и переходы (`docs/FRONTEND.md`, «Карточка задачи
 * одним запросом»). Тела остальных записей подгружаются по клику, в `entities/entry`.
 */
export function taskPackageQueryOptions(key: string) {
  return queryOptions({
    queryKey: taskPackageKeys.package(key),
    // Без `brief` бэкенд отдаёт полный пакет; контракт описывает оба ответа объединением,
    // и краткий (`TaskBriefRead`) экрану карточки не нужен (TRK-579).
    queryFn: async (): Promise<TaskPackage> =>
      (await unwrap(
        apiClient.GET('/api/v1/tasks/{task_key}', { params: { path: { task_key: key } } }),
      )) as TaskPackage,
  });
}
