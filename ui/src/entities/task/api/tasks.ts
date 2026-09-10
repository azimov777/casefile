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
 * одним именем — иначе `422 search_field_unknown` (`docs/FRONTEND.md`).
 */
export const TASK_LIST_FIELDS = ['title', 'status', 'assignee', 'priority', 'features'];

/** Сколько строк на странице: столько помещается на экран без прокрутки шапки. */
export const TASK_PAGE_SIZE = 50;

/**
 * Сколько карточек читает столбец доски за раз.
 *
 * Меньше страницы таблицы намеренно: столбцу после UI-68 достаётся не экран целиком,
 * а его часть — 674 px из 900, то есть около шести карточек, — и страница в полсотни
 * означала бы прочитанные наперёд пять экранов ради одного. Десять — видимая часть
 * и запас, чтобы сторож в конце столбца не срабатывал сразу вслед за первой страницей.
 */
export const TASK_COLUMN_PAGE_SIZE = 10;

/**
 * Ключи запросов, разложенные по двум экранам списка.
 *
 * Разложены они так не для порядка, а потому, что живой поток обновляет эти экраны
 * по-разному: доска перечитывается сама, таблица ждёт просьбы человека (UI-72).
 * Правило это выражается ровно двумя префиксами — `table` и `board`, — и общего
 * корня над ними больше нет: единый `['tasks']` накрывал оба экрана, и всякий, кто
 * брал его, отменял деление, сам того не заметив.
 *
 * Числа в заголовках столбцов стоят под `board` вместе со страницами: спрашивает их
 * доска и только доска — таблица своё число берёт из меты собственной страницы.
 */
export const taskKeys = {
  /** Всё, что читает таблица: страница выдачи целиком. */
  table: ['tasks', 'table'] as const,
  list: (params: TaskListParams) => ['tasks', 'table', params] as const,
  /** Всё, что читает доска: страницы столбцов и числа над ними. */
  board: ['tasks', 'board'] as const,
  /** Столбец доски: свой отбор по статусу, свой курсор, свои копящиеся страницы. */
  column: (params: TaskListParams) => ['tasks', 'board', 'column', params] as const,
  /** Сколько задач в отборе — без самих задач. */
  total: (params: TaskListParams) => ['tasks', 'board', 'total', params] as const,
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
 * Один столбец доски: тот же отбор плюс свой статус, страницами, которые копятся.
 *
 * Отбор по статусу здесь не противоречит тому, что доска снимает его с формы
 * (`filtersToListParams`): там снимается условие человека, а здесь стоит сам
 * столбец. Прокрутка `done` дочитывает `done` и никого больше — ради этого
 * запросов и стало столько, сколько столбцов.
 *
 * Курсор не из адреса: у столбца он не состояние экрана, а положение чтения —
 * переслать ссылку «на вторую страницу столбца» бессмысленно.
 */
export function tasksColumnQueryOptions(status: TaskStatus, params: TaskListParams) {
  const column = { ...params, status: [status], limit: TASK_COLUMN_PAGE_SIZE };

  return infiniteQueryOptions({
    queryKey: taskKeys.column(column),
    queryFn: ({ pageParam }) =>
      fetchTasks({ ...column, cursor: pageParam === '' ? undefined : pageParam }),
    initialPageParam: '',
    getNextPageParam: (last: Page<Task>) =>
      last.meta?.has_more === true ? (last.meta.next_cursor ?? undefined) : undefined,
    // Смена отбора меняет ключ: без этого столбец мигал бы пустотой на каждую правку
    // условий. Прочитанное держится, пока не придёт новое.
    placeholderData: keepPreviousData,
  });
}

/**
 * Сколько задач в отборе — числом, без самих задач.
 *
 * Общее число выдачи считает бэкенд (`meta.total`, TRK-41), поэтому спрашивается
 * страница в одну строку и с одним полем: строка выбрасывается, число остаётся.
 * Отсюда своё число берут заголовок экрана (весь отбор) и заголовок свёрнутого
 * столбца (отбор плюс его статус) — тот карточек не читает вовсе, а число показывать
 * обязан.
 *
 * `null` в ответе означает «коллекция не считала»: у списка задач такого не бывает,
 * но врать точным числом при нём нельзя — показывающий разбирает этот случай сам.
 */
export function tasksTotalQueryOptions(params: TaskListParams) {
  const counted = { ...params, limit: 1, fields: ['status'] };

  return queryOptions({
    queryKey: taskKeys.total(counted),
    queryFn: () => fetchTasks(counted),
    select: (page: Page<Task>) => page.meta?.total ?? null,
    placeholderData: keepPreviousData,
  });
}
