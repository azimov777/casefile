import { infiniteQueryOptions } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components } from '@/shared/api';

/** Токен доступа без секрета: секрет живёт только в ответе на выпуск. */
export type Token = components['schemas']['TokenRead'];
export type TokenScope = components['schemas']['TokenScope'];

/**
 * Отозван ли доступ. Признака «отозван» в контракте нет — есть время отзыва, и
 * вопрос «жив ли ключ» это вопрос о нём (`app/api/schemas/tokens.py`).
 */
export function isRevoked(token: Token): boolean {
  return token.revoked_at !== null && token.revoked_at !== undefined;
}

export const tokenKeys = {
  all: ['tokens'] as const,
  list: ['tokens', 'list'] as const,
};

/** Сколько доступов на странице. Столько же берёт по умолчанию и бэкенд. */
export const TOKEN_PAGE_SIZE = 50;

/**
 * Все токены установки, включая отозванные: отзыв — часть истории, а не удаление
 * (`../docs/CONCEPT.md`, 3.1). Чтение открыто любому набору, в том числе `task`, —
 * поэтому список виден и тому, кому запись закрыта.
 *
 * Выдача листается курсором, как все коллекции, кроме списка задач: `meta.total`
 * здесь `null`, и «сколько всего доступов» экран не знает, пока не дочитает.
 */
export function tokensQueryOptions() {
  return infiniteQueryOptions({
    queryKey: tokenKeys.list,
    queryFn: ({ pageParam }): Promise<Page<Token>> =>
      unwrapPage(
        apiClient.GET('/api/v1/tokens', {
          params: {
            query: {
              limit: TOKEN_PAGE_SIZE,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Token>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
  });
}
