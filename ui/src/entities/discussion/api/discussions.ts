import { infiniteQueryOptions, keepPreviousData, queryOptions } from '@tanstack/react-query';
import {
  apiClient,
  unwrap,
  unwrapPage,
  type Page,
  type components,
  type operations,
} from '@/shared/api';

/** Запись дела обсуждения: тот же размеченный `type` тип, что в деле задачи (`EntryRead`). */
export type DiscussionEntry = components['schemas']['EntryRead'];

/** Обсуждение в списке: адрес, название, чей ход, число открытых вопросов (`DiscussionRead`). */
export type Discussion = components['schemas']['DiscussionRead'];

/** Обсуждение для своего экрана: плюс привязанные задачи и последний итог. */
export type DiscussionDetail = components['schemas']['DiscussionDetailRead'];

/** Привязанная задача: ключ, название, статус и кто привязал. */
export type DiscussionTask = components['schemas']['DiscussionTaskRead'];

/** Последний итог обсуждения: что решено, что заменено, что открыто. */
export type Conclusion = components['schemas']['ConclusionEntryRead'];

export type DiscussionTurn = components['schemas']['DiscussionTurn'];
export type DiscussionStatus = components['schemas']['DiscussionStatus'];

/** Отбор списка — из контракта, а не свой. */
export type DiscussionListParams = NonNullable<
  operations['list_discussions']['parameters']['query']
>;

/**
 * Ключи запросов обсуждений.
 *
 * Карточка и лента — под префиксом `['discussion', адрес]`: одно перечитывание по кадру
 * живого потока накрывает и карточку, и ленту, и тела записей (`entities/entry`,
 * `entryKeys.discussionBody`), как `['task', key]` у задачи. Списки — под `['discussions']`:
 * входящая, история и блок в карточке задачи устаревают от любой записи обсуждения.
 */
export const discussionKeys = {
  all: ['discussions'] as const,
  list: (params: DiscussionListParams) => ['discussions', 'list', params] as const,
  detail: (address: string) => ['discussion', address] as const,
  feed: (address: string) => ['discussion', address, 'feed'] as const,
};

/** Сколько обсуждений на странице входящей и истории. */
export const DISCUSSION_PAGE_SIZE = 25;

/** Сколько записей дела обсуждения за раз: предел контракта общий с делом задачи. */
export const DISCUSSION_ENTRY_PAGE_SIZE = 200;

/**
 * Обсуждения по отбору, страницами по курсору бэкенда. Порядок считает бэкенд (`order`):
 * курсор листает выдачу в её порядке, и перевёрнутая на месте страница поставила бы вторую
 * страницу выше первой.
 */
export function discussionsQueryOptions(params: DiscussionListParams = {}) {
  return infiniteQueryOptions({
    queryKey: discussionKeys.list(params),
    queryFn: ({ pageParam }): Promise<Page<Discussion>> =>
      unwrapPage(
        apiClient.GET('/api/v1/discussions', {
          params: {
            query: {
              limit: DISCUSSION_PAGE_SIZE,
              ...params,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Discussion>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    placeholderData: keepPreviousData,
  });
}

/** Входящая по обсуждениям: незакрытые, где ход за человеком, от давнишних (TRK#51, п. 8). */
export function inboxDiscussionsQueryOptions(project: string) {
  return discussionsQueryOptions({
    status: 'open',
    turn: 'human',
    order: 'oldest',
    ...(project === '' ? {} : { project }),
  });
}

/** История: все обсуждения, открытые и закрытые, от свежих. */
export function discussionHistoryQueryOptions(project: string) {
  return discussionsQueryOptions({ order: 'newest', ...(project === '' ? {} : { project }) });
}

/** Обсуждения задачи, к которым она привязана, — блок в её карточке. */
export function taskDiscussionsQueryOptions(taskKey: string) {
  return discussionsQueryOptions({ task: taskKey, order: 'newest' });
}

/** Одно обсуждение по адресу `TRK~7`. */
export function discussionQueryOptions(address: string) {
  return queryOptions({
    queryKey: discussionKeys.detail(address),
    queryFn: (): Promise<DiscussionDetail> =>
      unwrap(
        apiClient.GET('/api/v1/discussions/{discussion}', {
          params: { path: { discussion: address } },
        }),
      ),
  });
}

/** Лента дела обсуждения: записи с телами, от старых к новым, страницами по курсору. */
export function discussionFeedQueryOptions(address: string) {
  return infiniteQueryOptions({
    queryKey: discussionKeys.feed(address),
    queryFn: ({ pageParam }): Promise<Page<DiscussionEntry>> =>
      unwrapPage(
        apiClient.GET('/api/v1/discussions/{discussion}/entries', {
          params: {
            path: { discussion: address },
            query: {
              limit: DISCUSSION_ENTRY_PAGE_SIZE,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<DiscussionEntry>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
  });
}
