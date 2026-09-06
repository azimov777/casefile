import { infiniteQueryOptions, keepPreviousData } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components, type operations } from '@/shared/api';

/** Замечание — запись дела типа `remark`, поэтому и живёт рядом с записями. */
export type Remark = components['schemas']['RemarkEntryRead'];

export type RemarkListParams = NonNullable<operations['list_remarks']['parameters']['query']>;

export const remarkKeys = {
  all: ['remarks'] as const,
  list: (params: RemarkListParams) => ['remarks', 'list', params] as const,
};

/** Сколько замечаний на странице. */
export const REMARK_PAGE_SIZE = 25;

/**
 * Неразобранные замечания поперёк задач (`../tracker/docs/FRONTEND.md`, «Экран „что не
 * разобрали"»).
 *
 * Умолчания «мои» у выдачи нет, в отличие от входящей вопросов: у замечания нет
 * адресата, оно ждёт того, кто ведёт задачу. «Мои» строится параметром `author`, и
 * подставляет его страница — она знает, кто вошёл.
 */
export function remarksQueryOptions(params: RemarkListParams) {
  return infiniteQueryOptions({
    queryKey: remarkKeys.list(params),
    queryFn: ({ pageParam }): Promise<Page<Remark>> =>
      unwrapPage(
        apiClient.GET('/api/v1/remarks', {
          params: {
            query: {
              open: true,
              limit: REMARK_PAGE_SIZE,
              ...params,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Remark>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    placeholderData: keepPreviousData,
  });
}
