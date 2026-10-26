import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

/** Решение в списке поперёк проектов и областей (`GET /api/v1/decisions`, TRK-756). */
export type DecisionRow = components['schemas']['DecisionListRead'];

/** Исход проверки человеком: подтвердил, отклонил, удалил (значение контракта). */
export type ReviewOutcome = components['schemas']['ReviewOutcome'];

/** Проверено ли решение человеком (значение контракта). */
export type ReviewState = components['schemas']['ReviewState'];

/** Страница списка решений: строки, число непроверенных и курсор следующей. */
export interface DecisionList {
  rows: DecisionRow[];
  /** Сколько действующих решений не проверено во всей области списка: отборы его не меняют. */
  unconfirmed: number;
}

/**
 * Ключи запросов списка решений. Корень `['decisions']` накрывает все списки: проверка
 * решения и запись нового решения человеком перечитывают их разом, а какие строки
 * попадут в какой список, решает бэкенд.
 */
export const decisionKeys = {
  all: ['decisions'] as const,
  /** `project` — ключ проекта; `null` — решения всех проектов (Входящая, TRK-759). */
  list: (project: string | null) => ['decisions', project ?? 'all'] as const,
};

/** Страниц списка не больше: потолок, а не ожидаемый размер (200 строк на страницу). */
const MAX_PAGES = 25;
const PAGE_SIZE = 200;

/**
 * Все решения проекта и его активных областей (или всех проектов), старые первыми, со
 * статусом и состоянием проверки от бэкенда. Читается целиком страница за страницей:
 * экрану нужны отбор «Не подтверждены», число на вкладке и «Показать снятые», а для них
 * пришлось бы знать все строки. Отборы `status` и `review_state` бэкенда не используются —
 * они складываются по «и», а экрану нужны «или»; раскладка по трём видам — на клиенте,
 * по готовым полям строки.
 */
export function decisionsQueryOptions(project: string | null) {
  return queryOptions({
    queryKey: decisionKeys.list(project),
    queryFn: async (): Promise<DecisionList> => {
      const rows: DecisionRow[] = [];
      let unconfirmed = 0;
      let cursor: string | undefined;
      for (let page = 0; page < MAX_PAGES; page += 1) {
        const response = await readPage(project, cursor);
        rows.push(...response.data);
        unconfirmed = response.unconfirmed;
        const meta = response.meta;
        if (meta?.has_more !== true || meta.next_cursor == null) break;
        cursor = meta.next_cursor;
      }
      return { rows, unconfirmed };
    },
  });
}

/**
 * Страница целиком, вместе с полем `unconfirmed` рядом с `data`: `unwrap` снимает оболочку
 * `{ data }`, и число непроверенных пропало бы вместе с ней, поэтому ответ кладётся в
 * новую оболочку, а отказ бэкенда по-прежнему приходит `ApiError`.
 */
function readPage(project: string | null, cursor: string | undefined) {
  return unwrap(
    apiClient
      .GET('/api/v1/decisions', {
        params: {
          query: {
            limit: PAGE_SIZE,
            ...(project === null ? {} : { project }),
            ...(cursor === undefined ? {} : { cursor }),
          },
        },
      })
      .then((result) => ({
        ...result,
        data: result.data === undefined ? undefined : { data: result.data },
      })),
  );
}

/** Сколько ждущих проверки решений читает Входящая за раз; дальше — «Ещё». */
const INBOX_PAGE_SIZE = 20;

/**
 * Решения, которые ждут человека, — раздел «Решения ждут проверки» Входящей (TRK-759): только
 * действующие и непроверенные, старые первыми, всех проектов или одного. Страницами по
 * кнопке «Ещё»: после выпуска их сотни, и читать все ради двадцати строк не нужно. Отбор —
 * `status=in_force` вместе с `review_state=unconfirmed`, как называет контракт. Ключ под
 * корнем `['decisions']`: проверка любого решения перечитывает и этот список.
 */
export function unconfirmedDecisionsQueryOptions(project: string) {
  return infiniteQueryOptions({
    queryKey: [...decisionKeys.list(project === '' ? null : project), 'unconfirmed'] as const,
    queryFn: ({ pageParam }) =>
      unwrap(
        apiClient
          .GET('/api/v1/decisions', {
            params: {
              query: {
                limit: INBOX_PAGE_SIZE,
                status: 'in_force',
                review_state: 'unconfirmed',
                ...(project === '' ? {} : { project }),
                ...(pageParam === '' ? {} : { cursor: pageParam }),
              },
            },
          })
          .then((result) => ({
            ...result,
            data: result.data === undefined ? undefined : { data: result.data },
          })),
      ),
    initialPageParam: '',
    getNextPageParam: (last) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
  });
}
