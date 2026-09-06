import { useMutation, useQueryClient } from '@tanstack/react-query';
import { questionKeys } from '@/entities/entry';
import { sessionKeys } from '@/entities/session';
import { apiClient, unwrap, type components } from '@/shared/api';

type Entry = components['schemas']['EntryRead'];

export interface AnswerInput {
  taskKey: string;
  questionNo: number;
  body: string;
  /** Ключ повтора: тот же на каждой попытке отправить этот ответ. */
  idempotencyKey: string;
}

/**
 * Ответ на вопрос — единственная запись, которую в трекере создаёт человек
 * (`CONCEPT.md`, 1).
 *
 * Ключ повтора приходит снаружи, а не рождается здесь: если сеть оборвалась после
 * отправки, повтор обязан идти с тем же ключом — иначе бэкенд заведёт второй ответ
 * на тот же вопрос, и человек об этом даже не узнает.
 */
export function useAnswerQuestion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskKey, questionNo, body, idempotencyKey }: AnswerInput): Promise<Entry> =>
      unwrap(
        apiClient.POST('/api/v1/tasks/{task_key}/entries', {
          params: {
            path: { task_key: taskKey },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body: { type: 'answer', body, payload: { question_no: questionNo } },
        }),
      ),

    onSuccess: (_entry, { taskKey }) => {
      // Ответ меняет три экрана сразу: входящую, карточку задачи и счётчик в шапке.
      // Пересчитывает их бэкенд — интерфейс только просит перечитать, а не правит
      // кэш руками: признаки задачи вычисляются из дела, и «уменьшить на один»
      // здесь было бы догадкой (`CONCEPT.md`, 6).
      void queryClient.invalidateQueries({ queryKey: questionKeys.all });
      void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
    },
  });
}
