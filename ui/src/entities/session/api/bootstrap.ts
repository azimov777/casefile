import { queryOptions } from '@tanstack/react-query';
import {
  ApiError,
  CLIENT_ERROR_CODES,
  apiClient,
  authorizationHeader,
  unwrap,
  type components,
} from '@/shared/api';

export type Bootstrap = components['schemas']['BootstrapRead'];
export type Participant = components['schemas']['ParticipantRead'];
export type Project = components['schemas']['ProjectRead'];

export const sessionKeys = {
  bootstrap: ['bootstrap'] as const,
  /**
   * Первый кадр вместе с архивными проектами (`include_archived`, TRK-160). Ключ стоит
   * под префиксом `bootstrap`: всё, что перечитывает первый кадр, перечитывает и его.
   */
  bootstrapWithArchived: ['bootstrap', 'with-archived'] as const,
};

/**
 * Первый кадр интерфейса одним запросом: участник за токеном, проекты установки,
 * число адресованных ему открытых вопросов.
 *
 * `token` передаётся явно только на входе — когда его ещё не сохранили и проверяют.
 * Во всех остальных случаях заголовок подставляет перехватчик клиента.
 */
export function fetchBootstrap(
  token?: string,
  { includeArchived = false }: { includeArchived?: boolean } = {},
): Promise<Bootstrap> {
  // Заголовок собирается одной общей функцией, а не строкой по месту: проверка
  // «можно ли это положить в заголовок» обязана быть одна на все пути (`shared/api`).
  const header = token === undefined ? undefined : authorizationHeader(token);

  if (header === null) {
    return Promise.reject(
      new ApiError(
        CLIENT_ERROR_CODES.tokenNotHeaderSafe,
        'Token cannot be put into a header',
        0,
        {},
      ),
    );
  }

  return unwrap(
    apiClient.GET('/api/v1/bootstrap', {
      headers: header === undefined ? undefined : { Authorization: header },
      params: includeArchived ? { query: { include_archived: true } } : undefined,
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

/**
 * Первый кадр с архивными проектами — для панели, когда человек попросил их показать
 * (`UI-176`). Прочий интерфейс читает обычный кадр: архивный проект скрыт по умолчанию
 * бэкендом (`../docs/CONCEPT.md`, 3.2), и интерфейс не прячет и не добавляет его сам.
 */
export function bootstrapWithArchivedQueryOptions() {
  return queryOptions({
    queryKey: sessionKeys.bootstrapWithArchived,
    queryFn: () => fetchBootstrap(undefined, { includeArchived: true }),
    staleTime: 60_000,
  });
}
