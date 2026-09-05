import {
  TASK_PRIORITIES,
  TASK_STATUSES,
  type TaskListParams,
  type TaskPriority,
  type TaskStatus,
} from '@/entities/task';

/**
 * Состояние отбора. Живёт в адресе страницы целиком (`CONCEPT.md`, 3): ссылку можно
 * переслать, и другой человек увидит ровно то же самое.
 *
 * Отсутствие значения выражается пустой строкой и пустым списком, а не `null`: это
 * же состояние приходит из полей формы, и второй способ сказать «ничего не выбрано»
 * пришлось бы приводить к первому в каждом обработчике.
 */
export interface TaskFilters {
  queue: string;
  status: TaskStatus[];
  priority: TaskPriority[];
  assignee: string;
  tags: string[];
  text: string;
  /** Только заблокированные: у структурного фильтра это `blocked=true`. */
  blocked: boolean;
  /** Только с открытыми вопросами; см. `OPEN_QUESTIONS_CONDITION`. */
  withQuestions: boolean;
  /** Строка на языке запросов бэкенда. Клиент её не разбирает. */
  query: string;
  sort: string;
  cursor: string;
}

/** Порядок по умолчанию: человек приходит смотреть, что изменилось. */
export const DEFAULT_SORT = '-updated_at';

/**
 * Порядки, которые предлагает интерфейс. Ключи сортировки — из контракта (`key`,
 * `updated_at`, `priority`), минус впереди означает по убыванию.
 */
export const TASK_SORTS: { value: string; label: string }[] = [
  { value: '-updated_at', label: 'сначала недавно обновлённые' },
  { value: 'updated_at', label: 'сначала давно не тронутые' },
  { value: '-priority', label: 'сначала важные' },
  { value: 'priority', label: 'сначала неважные' },
  { value: 'key', label: 'по ключу' },
  { value: '-key', label: 'по ключу, с конца' },
];

/**
 * «Есть открытые вопросы» — единственное условие интерфейса, которое структурным
 * параметром не выражается: `open_questions` принимает точное число, а не сравнение.
 * Оно уезжает готовой строкой в `query`, где бэкенд складывает её с остальными
 * условиями по «и».
 *
 * Склейки с тем, что человек напечатал сам, не происходит никогда: заполненное поле
 * запроса отменяет структурный отбор целиком (см. `filtersToListParams`). Иначе
 * клиенту пришлось бы разбирать чужой запрос, чтобы дописать в него условие,
 * — ровно то, чего задача запрещает.
 */
export const OPEN_QUESTIONS_CONDITION = 'open_questions: > 0';

export const EMPTY_FILTERS: TaskFilters = {
  queue: '',
  status: [],
  priority: [],
  assignee: '',
  tags: [],
  text: '',
  blocked: false,
  withQuestions: false,
  query: '',
  sort: DEFAULT_SORT,
  cursor: '',
};

/** Адрес → отбор. Неизвестные значения отбрасываются: см. `keepKnown`. */
export function readFilters(params: URLSearchParams): TaskFilters {
  const sort = params.get('sort');

  return {
    queue: params.get('queue') ?? '',
    status: keepKnown(params.getAll('status'), TASK_STATUSES),
    priority: keepKnown(params.getAll('priority'), TASK_PRIORITIES),
    assignee: params.get('assignee') ?? '',
    tags: params.getAll('tags').flatMap(splitTags),
    text: params.get('text') ?? '',
    blocked: params.get('blocked') === 'true',
    withQuestions: params.get('questions') === 'true',
    query: params.get('query') ?? '',
    sort: TASK_SORTS.some((option) => option.value === sort) && sort !== null ? sort : DEFAULT_SORT,
    cursor: params.get('cursor') ?? '',
  };
}

/** Отбор → адрес. Пустое и умолчания в адрес не пишутся: ссылка остаётся читаемой. */
export function writeFilters(filters: TaskFilters): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.queue !== '') params.set('queue', filters.queue);
  for (const status of filters.status) params.append('status', status);
  for (const priority of filters.priority) params.append('priority', priority);
  if (filters.assignee.trim() !== '') params.set('assignee', filters.assignee.trim());
  for (const tag of filters.tags) params.append('tags', tag);
  if (filters.text.trim() !== '') params.set('text', filters.text.trim());
  if (filters.blocked) params.set('blocked', 'true');
  if (filters.withQuestions) params.set('questions', 'true');
  if (filters.query.trim() !== '') params.set('query', filters.query.trim());
  if (filters.sort !== DEFAULT_SORT) params.set('sort', filters.sort);
  if (filters.cursor !== '') params.set('cursor', filters.cursor);

  return params;
}

/**
 * Отбор → параметры `GET /api/v1/tasks`.
 *
 * Заполненное поле запроса имеет приоритет: оно уходит одно, без структурных
 * параметров. Смешивать их бэкенд умеет, но человек, видящий и то и другое,
 * не смог бы объяснить себе выдачу — а спрятать поля формы, пока в запросе
 * что-то написано, значит потерять их значения.
 */
export function filtersToListParams(filters: TaskFilters): TaskListParams {
  const paging = {
    sort: [filters.sort],
    cursor: filters.cursor === '' ? undefined : filters.cursor,
  };

  const query = filters.query.trim();
  if (query !== '') return { query, ...paging };

  return {
    queue: filters.queue === '' ? undefined : [filters.queue],
    status: filters.status.length > 0 ? filters.status : undefined,
    priority: filters.priority.length > 0 ? filters.priority : undefined,
    assignee: filters.assignee.trim() === '' ? undefined : [filters.assignee.trim()],
    tags: filters.tags.length > 0 ? filters.tags : undefined,
    text: filters.text.trim() === '' ? undefined : filters.text.trim(),
    blocked: filters.blocked ? true : undefined,
    query: filters.withQuestions ? OPEN_QUESTIONS_CONDITION : undefined,
    ...paging,
  };
}

/**
 * Есть ли хоть одно условие: по этому пустая выдача выбирает себе подсказку.
 *
 * Считается через запись в адрес, а не своим перечислением полей: новый фильтр иначе
 * пришлось бы вспомнить в двух местах, и забытый здесь тихо превратил бы «ничего не
 * нашлось по вашим условиям» в «в очереди пусто».
 */
export function hasConditions(filters: TaskFilters): boolean {
  const conditions = writeFilters({ ...filters, sort: DEFAULT_SORT, cursor: '' });
  return [...conditions.keys()].length > 0;
}

/** Теги принимаются и повтором параметра, и перечислением через запятую. */
export function splitTags(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '');
}

/**
 * Оставляет только значения, которые есть в контракте.
 *
 * Опечатка в адресе (`status=opne`) не должна ни уезжать на бэкенд структурным
 * параметром — типы фильтра перестали бы что-то значить, — ни рисовать в форме
 * флажок, которого нет. Язык запросов это не затрагивает: там опечатку разбирает
 * и объясняет бэкенд.
 */
function keepKnown<T extends string>(values: string[], known: T[]): T[] {
  return values.filter((value): value is T => (known as string[]).includes(value));
}
