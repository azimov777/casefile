import { infiniteQueryOptions, keepPreviousData } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components, type operations } from '@/shared/api';

/**
 * Вопрос — запись дела типа `question`, поэтому и живёт рядом с записями. В выдаче
 * поперёк задач он едет с ответами на него (`answers`, TRK-120): у открытого вопроса
 * их нет, у отвеченного первый ответ его закрыл.
 */
export type Question = components['schemas']['AnsweredQuestionRead'];

/** Ответ под вопросом в выдаче: та же запись `answer`, что и в деле задачи. */
export type QuestionAnswer = components['schemas']['AnswerEntryRead'];

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

/**
 * История вопросов: все вопросы, с ответом и без, от свежих к старым.
 *
 * Та же выдача, что у входящей, и тот же ключ запроса: ответ во входящей
 * инвалидирует `questions` целиком, и история видит его без отдельной подписки.
 * Порядок считает бэкенд (`order=newest`), а не клиент переворотом страницы: курсор
 * листает выдачу в её порядке, и перевёрнутая на месте страница поставила бы
 * вторую страницу выше первой.
 */
export function questionHistoryQueryOptions(params: QuestionListParams) {
  return questionsQueryOptions({ ...params, open: false, order: 'newest' });
}
