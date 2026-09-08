import { infiniteQueryOptions, queryOptions, keepPreviousData } from '@tanstack/react-query';
import { apiClient, unwrapPage, type Page, type components, type operations } from '@/shared/api';

export type Task = components['schemas']['TaskSearchRead'];
export type TaskFeatures = components['schemas']['TaskFeaturesRead'];
export type TaskStatus = components['schemas']['TaskStatus'];
export type TaskPriority = components['schemas']['TaskPriority'];

/**
 * Параметры отбора — из контракта, а не свои: имя фильтра переименуют на бэкенде,
 * и это упадёт сборкой, а не пустой выдачей.
 */
export type TaskListParams = NonNullable<operations['list_tasks']['parameters']['query']>;

/**
 * Статусы и приоритеты списком для фильтров.
 *
 * Перечислены ключами объекта, а не массивом: `satisfies Record<...>` требует все члены
 * объединения и не терпит лишних, поэтому значение, добавленное в контракт, роняет
 * сборку — а не тихо пропадает из селектора, где его никто не хватится.
 */
const STATUS_SET = {
  backlog: true,
  open: true,
  in_progress: true,
  waiting: true,
  done: true,
  cancelled: true,
} satisfies Record<TaskStatus, true>;

const PRIORITY_SET = {
  low: true,
  normal: true,
  high: true,
  critical: true,
} satisfies Record<TaskPriority, true>;

export const TASK_STATUSES = Object.keys(STATUS_SET) as TaskStatus[];
export const TASK_PRIORITIES = Object.keys(PRIORITY_SET) as TaskPriority[];

/**
 * Что просить в строке. Полная задача тащит пять разделов и `checks`; таблице они не
 * нужны, а весят больше всего остального вместе взятого. `features` выбирается целиком
 * одним именем — иначе `422 search_field_unknown` (`../tracker/docs/FRONTEND.md`).
 */
export const TASK_LIST_FIELDS = ['title', 'status', 'assignee', 'priority', 'features'];

/** Сколько строк на странице: столько помещается на экран без прокрутки шапки. */
export const TASK_PAGE_SIZE = 50;

export const taskKeys = {
  all: ['tasks'] as const,
  list: (params: TaskListParams) => ['tasks', 'list', params] as const,
  /** Тот же отбор, но страницы накапливаются: доска показывает их разом. */
  board: (params: TaskListParams) => ['tasks', 'board', params] as const,
};

export function fetchTasks(params: TaskListParams): Promise<Page<Task>> {
  return unwrapPage(
    apiClient.GET('/api/v1/tasks', {
      // Набор полей и размер страницы — умолчания списка: вызывающий вправе их
      // переназначить, поэтому его параметры идут последними.
      params: { query: { fields: TASK_LIST_FIELDS, limit: TASK_PAGE_SIZE, ...params } },
    }),
  );
}

export function tasksQueryOptions(params: TaskListParams) {
  return queryOptions({
    queryKey: taskKeys.list(params),
    queryFn: () => fetchTasks(params),
    // Смена фильтра меняет ключ запроса: без этого таблица на каждую правку буквы
    // в поле текста мигала бы пустотой. Строки предыдущего отбора держатся, пока
    // не придут новые.
    placeholderData: keepPreviousData,
  });
}

/**
 * Тот же список, но страницами, которые копятся: доска раскладывает по столбцам всё
 * прочитанное сразу, и «ещё» дочитывает следующую страницу, а не заменяет текущую.
 *
 * Курсор здесь не из адреса: у доски он не состояние экрана, а положение чтения —
 * переслать ссылку «на вторую страницу доски» бессмысленно, столбцы соберутся другие.
 */
export function tasksBoardQueryOptions(params: TaskListParams) {
  return infiniteQueryOptions({
    queryKey: taskKeys.board(params),
    queryFn: ({ pageParam }) =>
      fetchTasks({ ...params, cursor: pageParam === '' ? undefined : pageParam }),
    initialPageParam: '',
    getNextPageParam: (last: Page<Task>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    placeholderData: keepPreviousData,
  });
}
