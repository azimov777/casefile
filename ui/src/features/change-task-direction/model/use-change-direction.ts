import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

type TaskRead = components['schemas']['TaskRead'];

export interface ChangeDirectionInput {
  taskKey: string;
  /** Адрес направления `TRK/promotion` или `null` — «без направления». */
  direction: string | null;
}

/**
 * Ставит задаче направление или снимает его (TRK-557): `PATCH /api/v1/tasks/{key}` с одним
 * полем `direction` — единственная правка задачи, которую делает человек (TRK#16, ч. 4;
 * запись `decision` в деле TRK-557).
 *
 * Версию задачи правка не шлёт намеренно: агент, ведущий задачу, меняет её версию каждым
 * переходом, и сверка версии ловила бы не чужую правку направления, а любой его шаг.
 * Направление — значение «поставь это», и повтор того же значения ничего не меняет.
 *
 * Отказы называет бэкенд: чужой проект — `direction_project_mismatch`, архивное —
 * `direction_archived`, закрытая задача — `task_closed`; интерфейс их не предугадывает,
 * а объясняет словами из словаря.
 */
export function useChangeTaskDirection() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskKey, direction }: ChangeDirectionInput): Promise<TaskRead> =>
      unwrap(
        apiClient.PATCH('/api/v1/tasks/{task_key}', {
          params: { path: { task_key: taskKey } },
          body: { direction },
        }),
      ),
    onSuccess: (_task, { taskKey }) => {
      // Меняются карточка (поле и запись `field_changed` в деле) и выдача списка: строка
      // теперь отбирается другим направлением. Пересчитывает бэкенд — интерфейс только
      // просит перечитать.
      void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}
