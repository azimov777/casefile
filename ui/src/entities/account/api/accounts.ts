import { infiniteQueryOptions } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components } from '@/shared/api';

/**
 * Учётная запись человека (`TRK-113`): почта входа, участник, чьим именем подписаны его
 * записи, флаг администратора. Пароля здесь нет — ни в каком виде: сгенерированный
 * приходит один раз ответом на заведение или сброс (`features/manage-people`).
 */
export type Account = components['schemas']['AccountRead'];

/**
 * Отключена ли учётная запись. Признака в контракте нет — есть время отключения, и
 * вопрос «пускает ли она» это вопрос о нём (`app/api/schemas/accounts.py`).
 */
export function isDisabled(account: Account): boolean {
  return account.disabled_at !== null && account.disabled_at !== undefined;
}

export const accountKeys = {
  all: ['accounts'] as const,
  list: ['accounts', 'list'] as const,
};

/** Сколько учётных записей на странице. Столько же берёт по умолчанию и бэкенд. */
export const ACCOUNT_PAGE_SIZE = 50;

/**
 * Все учётные записи установки, отключённые тоже: отключение не удаляет человека —
 * его подписи в делах остаются. Только администратору: у остальных `403 admin_required`,
 * поэтому экран спрашивает список, лишь убедившись во флаге (`bootstrap.account`).
 *
 * Выдача листается курсором: `meta.total` здесь `null`, как у всех коллекций, кроме
 * списка задач.
 */
export function accountsQueryOptions() {
  return infiniteQueryOptions({
    queryKey: accountKeys.list,
    queryFn: ({ pageParam }): Promise<Page<Account>> =>
      unwrapPage(
        apiClient.GET('/api/v1/accounts', {
          params: {
            query: {
              limit: ACCOUNT_PAGE_SIZE,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Account>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
  });
}
