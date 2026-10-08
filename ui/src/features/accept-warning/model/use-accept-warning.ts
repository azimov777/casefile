import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sessionKeys } from '@/entities/session';
import { taskKeys } from '@/entities/task';
import { apiClient, unwrap, type components } from '@/shared/api';

type Entry = components['schemas']['EntryRead'];

export interface AcceptanceInput {
  taskKey: string;
  /** Строка описи. Человек её не пишет: принятие — одно нажатие, а не форма. */
  title: string;
  /** Ключ повтора: тот же на каждой попытке принять это предупреждение. */
  idempotencyKey: string;
}

/**
 * Принятие открытого предупреждения задачи — запись `acceptance` (TRK-561).
 *
 * Запись человека в его деле, как замечание, но без формы: недостаток уже назван
 * вердиктами `partial` и `unverifiable`, и сказать «принимаю» — одно действие. Отказ
 * приходит кодом (`warning_not_open`, `acceptance_by_closer`) и показывается словами
 * вызывающим.
 */
export function useAcceptWarning() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskKey, title, idempotencyKey }: AcceptanceInput): Promise<Entry> =>
      unwrap(
        apiClient.POST('/api/v1/tasks/{task_key}/entries', {
          params: {
            path: { task_key: taskKey },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body: { type: 'acceptance', title, body: '' },
        }),
      ),

    onSuccess: (_entry, { taskKey }) => {
      // Принятие снимает предупреждение: устаревают карточка задачи, раздел «Требуют
      // внимания» и число в значке входящей. Пересчитывает их бэкенд — интерфейс
      // только просит перечитать (TRK#207).
      void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
      void queryClient.invalidateQueries({ queryKey: taskKeys.attention });
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
    },
  });
}
