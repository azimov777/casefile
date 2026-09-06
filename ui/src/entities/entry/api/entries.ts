import { infiniteQueryOptions, keepPreviousData, queryOptions } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components, type operations } from '@/shared/api';

/** Запись дела с телом и нагрузкой: объединение, размеченное полем `type`. */
export type Entry = components['schemas']['EntryRead'];

/** Строка описи: заголовок записи без тела. */
export type EntryHeading = components['schemas']['EntryHeadingRead'];

export type EntryType = components['schemas']['EntryType'];
export type Author = components['schemas']['AuthorRead'];

/** Параметры чтения дела — из контракта, а не свои. */
export type EntryListParams = NonNullable<operations['list_task_entries']['parameters']['query']>;

/**
 * Типы записей списком.
 *
 * Перечислены ключами объекта: `satisfies Record<EntryType, true>` требует все члены
 * объединения, поэтому новый тип записи на бэкенде роняет сборку — а не появляется
 * в ленте без своего представления (та же причина, что у `TASK_STATUSES`).
 */
const ENTRY_TYPE_SET = {
  summary: true,
  decision: true,
  attempt: true,
  finding: true,
  artifact: true,
  question: true,
  answer: true,
  verdict: true,
  note: true,
  created: true,
  status_changed: true,
  section_changed: true,
  field_changed: true,
  assignee_changed: true,
  link_added: true,
  link_removed: true,
} satisfies Record<EntryType, true>;

export const ENTRY_TYPES = Object.keys(ENTRY_TYPE_SET) as EntryType[];

/**
 * Служебные типы: их подшивает сам трекер, а не агент (`../tracker/docs/CONCEPT.md`, 3.4).
 *
 * Словарь по значению, а не список: тип, добавленный в контракт, окажется среди записей
 * агента — это верное умолчание, потому что трекер свои записи заводит редко, а разбор
 * по типам всё равно упадёт сборкой в представлении записи.
 */
const SERVICE_TYPES: Partial<Record<EntryType, true>> = {
  created: true,
  status_changed: true,
  section_changed: true,
  field_changed: true,
  assignee_changed: true,
  link_added: true,
  link_removed: true,
};

export function isServiceEntry(type: EntryType): boolean {
  return SERVICE_TYPES[type] === true;
}

/** Сколько записей на странице ленты. */
export const ENTRY_PAGE_SIZE = 25;

export const entryKeys = {
  /** Ключ пакета карточки живёт в `entities/task`; здесь только тела. */
  bodies: (taskKey: string, nos: number[]) => ['task', taskKey, 'entries', nos] as const,
  /** Лента дела: страницы копятся, поэтому свой ключ, а не ключ тел записей. */
  feed: (taskKey: string, params: EntryListParams) => ['task', taskKey, 'case', params] as const,
};

/**
 * Тела названных записей одним запросом.
 *
 * Номера — часть ключа запроса, поэтому раскрытая запись читается один раз и живёт
 * в кэше: закрыть и открыть её снова второго запроса не стоит.
 */
export function entryQueryOptions(taskKey: string, no: number) {
  return queryOptions({
    queryKey: entryKeys.bodies(taskKey, [no]),
    queryFn: (): Promise<Page<Entry>> =>
      unwrapPage(
        apiClient.GET('/api/v1/tasks/{task_key}/entries', {
          params: { path: { task_key: taskKey }, query: { nos: [no] } },
        }),
      ),
    select: (page: Page<Entry>) => page.items[0] ?? null,
  });
}

/**
 * Лента дела страницами по курсору бэкенда: дело целиком не читается никогда — оно
 * растёт, и «показать всё» однажды перестанет помещаться в ответ.
 */
export function caseFeedQueryOptions(taskKey: string, params: EntryListParams) {
  return infiniteQueryOptions({
    queryKey: entryKeys.feed(taskKey, params),
    queryFn: ({ pageParam }): Promise<Page<Entry>> =>
      unwrapPage(
        apiClient.GET('/api/v1/tasks/{task_key}/entries', {
          params: {
            path: { task_key: taskKey },
            query: {
              limit: ENTRY_PAGE_SIZE,
              ...params,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Entry>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    placeholderData: keepPreviousData,
  });
}
