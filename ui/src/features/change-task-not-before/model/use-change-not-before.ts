import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

type TaskRead = components['schemas']['TaskRead'];

export interface ChangeNotBeforeInput {
  taskKey: string;
  /** Момент ISO 8601 со смещением пояса или `null` — снять. */
  notBefore: string | null;
}

/**
 * Ставит, меняет или снимает момент «можно взять с …» (TRK-593, TRK#47, п. 2):
 * `PATCH /api/v1/tasks/{key}` с одним полем `not_before`, по образцу правки области.
 *
 * Версию задачи правка не шлёт: агент, ведущий задачу, меняет её каждым переходом, и
 * сверка версии ловила бы не чужую правку момента, а любой его шаг. Отказы называет
 * бэкенд (`task_closed`, `task_fields_invalid`), интерфейс их не предугадывает.
 */
export function useChangeTaskNotBefore() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskKey, notBefore }: ChangeNotBeforeInput): Promise<TaskRead> =>
      unwrap(
        apiClient.PATCH('/api/v1/tasks/{task_key}', {
          params: { path: { task_key: taskKey } },
          body: { not_before: notBefore },
        }),
      ),
    onSuccess: (_task, { taskKey }) => {
      // Меняются карточка (поле, признак `deferred`, `field_changed` в деле) и списки:
      // значок на строке и карточке доски считает бэкенд, интерфейс просит перечитать.
      void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}
