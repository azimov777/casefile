import { useMutation, useQueryClient } from '@tanstack/react-query';
import { remarkKeys } from '@/entities/entry';
import { apiClient, unwrap, type components } from '@/shared/api';

type Entry = components['schemas']['EntryRead'];

export interface RemarkInput {
  taskKey: string;
  title: string;
  body: string;
  /** Ключ повтора: тот же на каждой попытке отправить это замечание. */
  idempotencyKey: string;
}

/**
 * Замечание к задаче — вторая запись, которую в трекере создаёт человек
 * (`../docs/CONCEPT.md`, 3.4).
 *
 * Заголовок обязателен: это строка описи, по которой замечание видно в ленте дела.
 * Собирает его форма из первой строки текста (`titleFromText`), а не спрашивает
 * вторым полем: два поля ради одного «вышло не то» — это форма, которую человек закроет.
 *
 * Ключ повтора приходит снаружи: если сеть оборвалась после отправки, повтор обязан
 * идти с тем же ключом — иначе бэкенд заведёт второе замечание, и разбирать агенту
 * придётся два одинаковых.
 */
export function useLeaveRemark() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskKey, title, body, idempotencyKey }: RemarkInput): Promise<Entry> =>
      unwrap(
        apiClient.POST('/api/v1/tasks/{task_key}/entries', {
          params: {
            path: { task_key: taskKey },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body: { type: 'remark', title, body },
        }),
      ),

    onSuccess: (_entry, { taskKey }) => {
      // Замечание меняет два экрана: карточку задачи (список неразобранных и признак)
      // и «что не разобрали» поперёк задач. Пересчитывает их бэкенд — интерфейс только
      // просит перечитать, а не правит кэш руками: признаки считаются из дела, и
      // «прибавить один» здесь было бы догадкой (`CONCEPT.md`, 6).
      void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
      void queryClient.invalidateQueries({ queryKey: remarkKeys.all });
    },
  });
}
