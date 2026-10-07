import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

type TaskRead = components['schemas']['TaskRead'];

export interface ChangeAreaInput {
  taskKey: string;
  /** Адрес области `TRK/promotion`: снять область нельзя (`area_required`). */
  area: string;
}

/**
 * Ставит задаче область или меняет её (TRK-557, TRK-677: снять нельзя): `PATCH /api/v1/tasks/{key}` с одним
 * полем `area` — единственная правка задачи, которую делает человек (TRK#16, ч. 4;
 * запись `decision` в деле TRK-557).
 *
 * Версию задачи правка не шлёт намеренно: агент, ведущий задачу, меняет её версию каждым
 * переходом, и сверка версии ловила бы не чужую правку области, а любой его шаг.
 * Область — значение «поставь это», и повтор того же значения ничего не меняет.
 *
 * Отказы называет бэкенд: чужой проект — `area_project_mismatch`, архивная —
 * `area_archived`, закрытая задача — `task_closed`; интерфейс их не предугадывает,
 * а объясняет словами из словаря.
 */
export function useChangeTaskArea() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskKey, area }: ChangeAreaInput): Promise<TaskRead> =>
      unwrap(
        apiClient.PATCH('/api/v1/tasks/{task_key}', {
          params: { path: { task_key: taskKey } },
          body: { area },
        }),
      ),
    onSuccess: (_task, { taskKey }) => {
      // Меняются карточка (поле и запись `field_changed` в деле) и выдача списка: строка
      // теперь отбирается другой областью. Пересчитывает бэкенд — интерфейс только
      // просит перечитать.
      void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}
