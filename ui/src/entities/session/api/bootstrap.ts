import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

export type Bootstrap = components['schemas']['BootstrapRead'];
export type Participant = components['schemas']['ParticipantRead'];
export type Queue = components['schemas']['QueueRead'];

export const sessionKeys = {
  bootstrap: ['bootstrap'] as const,
};

/**
 * Первый кадр интерфейса одним запросом: участник за токеном, очереди установки,
 * число адресованных ему открытых вопросов.
 *
 * `token` передаётся явно только на входе — когда его ещё не сохранили и проверяют.
 * Во всех остальных случаях заголовок подставляет перехватчик клиента.
 */
export function fetchBootstrap(token?: string): Promise<Bootstrap> {
  return unwrap(
    apiClient.GET('/api/v1/bootstrap', {
      headers: token === undefined ? undefined : { Authorization: `Bearer ${token}` },
    }),
  );
}

export function bootstrapQueryOptions() {
  return queryOptions({
    queryKey: sessionKeys.bootstrap,
    queryFn: () => fetchBootstrap(),
    // Имя участника и число вопросов приезжают ещё и кадрами живого потока (задача 07),
    // поэтому фонового перечитывания по фокусу окна здесь не нужно.
    staleTime: 60_000,
  });
}
