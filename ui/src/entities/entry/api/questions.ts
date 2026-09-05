import { infiniteQueryOptions, keepPreviousData } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components, type operations } from '@/shared/api';

/** Вопрос — запись дела типа `question`, поэтому и живёт рядом с записями. */
export type Question = components['schemas']['QuestionEntryRead'];

export type QuestionListParams = NonNullable<operations['list_questions']['parameters']['query']>;

export const questionKeys = {
  all: ['questions'] as const,
  list: (params: QuestionListParams) => ['questions', 'list', params] as const,
};

/** Сколько вопросов на странице входящей. */
export const QUESTION_PAGE_SIZE = 25;

/**
 * Открытые вопросы, адресованные текущему участнику: адресат по умолчанию — тот,
 * чьим токеном сделан запрос, поэтому «моя входящая» не требует знать своё имя.
 */
export function questionsQueryOptions(params: QuestionListParams) {
  return infiniteQueryOptions({
    queryKey: questionKeys.list(params),
    queryFn: ({ pageParam }): Promise<Page<Question>> =>
      unwrapPage(
        apiClient.GET('/api/v1/questions', {
          params: {
            query: {
              open: true,
              limit: QUESTION_PAGE_SIZE,
              ...params,
              cursor: pageParam === '' ? undefined : pageParam,
            },
          },
        }),
      ),
    initialPageParam: '',
    getNextPageParam: (last: Page<Question>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    placeholderData: keepPreviousData,
  });
}
