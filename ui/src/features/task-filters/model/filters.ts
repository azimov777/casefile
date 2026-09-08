import {
  TASK_PRIORITIES,
  TASK_STATUSES,
  type TaskListParams,
  type TaskPriority,
  type TaskStatus,
} from '@/entities/task';

/** Как показываем то же самое: таблицей или доской по столбцам статусов. */
export type TaskView = 'table' | 'board';

/**
 * Состояние отбора. Живёт в адресе страницы целиком (`CONCEPT.md`, 3): ссылку можно
 * переслать, и другой человек увидит ровно то же самое.
 *
 * Отсутствие значения выражается пустой строкой и пустым списком, а не `null`: это
 * же состояние приходит из полей формы, и второй способ сказать «ничего не выбрано»
 * пришлось бы приводить к первому в каждом обработчике.
 */
export interface TaskFilters {
  /** Режим отображения. Живёт в адресе, как и отбор: ссылка на доску открывает доску. */
  view: TaskView;
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
  /** Только с неразобранными замечаниями; см. `OPEN_REMARKS_CONDITION`. */
  withRemarks: boolean;
  /** Строка на языке запросов бэкенда. Клиент её не разбирает. */
  query: string;
  sort: string;
  cursor: string;
  /**
   * Свёрнутые столбцы доски. Живёт в адресе, как и всё, что меняет вид выдачи:
   * ссылка на доску должна открыться тем же самым, а не разворачивать столбцы,
   * которые отправитель свернул.
   */
  collapsed: TaskStatus[];
}

/**
 * Что свёрнуто, пока человек не сказал иначе: закрытая и отменённая задача интересны
 * реже остальных, а места занимают столько же.
 *
 * Отсутствие параметра в адресе означает это умолчание, а `collapsed=` без значения —
 * «ничего не свёрнуто». Иначе развернувший всё не смог бы переслать это ссылкой:
 * пустой список и отсутствующий были бы неразличимы.
 *
 * `waiting` сюда не входит, хотя работа в нём не идёт. Свёрнуто здесь то, что **уже
 * не в работе**, а ждущее из работы не вышло — оно ждёт хода, и ход этот человеческий
 * (`../tracker/docs/CONCEPT.md`, 3.3). Свернув его, доска спрятала бы от человека
 * единственный столбец, адресованный лично ему, — и он узнавал бы о своей очереди
 * только отбором, ради отмены которого статус и заводился.
 */
export const DEFAULT_COLLAPSED: TaskStatus[] = ['done', 'cancelled'];

/**
 * Порядок по умолчанию: где агенты работают прямо сейчас. Считается по
 * `features.last_entry_at` — когда в дело последний раз что-то подшивали.
 *
 * Не `-updated_at`, как было: `updated_at` двигает и правка карточки, и в строке его
 * больше нет — единственная колонка времени показывает активность. Порядок, который
 * нечем проверить глазами, человек не может себе объяснить.
 *
 * Задачи без записей в деле при этом порядке уходят вниз, а не всплывают наверх
 * пустотой: бэкенд сортирует с `NULLS LAST` в обе стороны.
 */
export const DEFAULT_SORT = '-last_entry_at';

/**
 * Порядки, которые предлагает интерфейс. Ключи сортировки — из контракта (`key`,
 * `last_entry_at`, `updated_at`, `priority`), минус впереди означает по убыванию.
 *
 * Порядки по `updated_at` остаются, хотя этой колонки в строке нет: правка карточки
 * мимо дела — приоритет, теги, разделы задания — видна только через них.
 */
export const TASK_SORTS: { value: string; label: string }[] = [
  { value: '-last_entry_at', label: 'сначала живые в деле' },
  { value: 'last_entry_at', label: 'сначала затихшие' },
  { value: '-updated_at', label: 'сначала недавно правленные' },
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

/** То же для замечаний: структурный параметр берёт точное число, а нужен диапазон. */
export const OPEN_REMARKS_CONDITION = 'open_remarks: > 0';

export const EMPTY_FILTERS: TaskFilters = {
  view: 'table',
  queue: '',
  status: [],
  priority: [],
  assignee: '',
  tags: [],
  text: '',
  blocked: false,
  withQuestions: false,
  withRemarks: false,
  query: '',
  sort: DEFAULT_SORT,
  cursor: '',
  collapsed: DEFAULT_COLLAPSED,
};

/** Адрес → отбор. Неизвестные значения отбрасываются: см. `keepKnown`. */
export function readFilters(params: URLSearchParams): TaskFilters {
  const sort = params.get('sort');

  return {
    view: params.get('view') === 'board' ? 'board' : 'table',
    queue: params.get('queue') ?? '',
    status: keepKnown(params.getAll('status'), TASK_STATUSES),
    priority: keepKnown(params.getAll('priority'), TASK_PRIORITIES),
    assignee: params.get('assignee') ?? '',
    tags: params.getAll('tags').flatMap(splitTags),
    text: params.get('text') ?? '',
    blocked: params.get('blocked') === 'true',
    withQuestions: params.get('questions') === 'true',
    withRemarks: params.get('remarks') === 'true',
    query: params.get('query') ?? '',
    sort: TASK_SORTS.some((option) => option.value === sort) && sort !== null ? sort : DEFAULT_SORT,
    cursor: params.get('cursor') ?? '',
    collapsed: params.has('collapsed')
      ? keepKnown(params.getAll('collapsed'), TASK_STATUSES)
      : DEFAULT_COLLAPSED,
  };
}

/** Отбор → адрес. Пустое и умолчания в адрес не пишутся: ссылка остаётся читаемой. */
export function writeFilters(filters: TaskFilters): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.view === 'board') params.set('view', 'board');
  if (filters.queue !== '') params.set('queue', filters.queue);
  for (const status of filters.status) params.append('status', status);
  for (const priority of filters.priority) params.append('priority', priority);
  if (filters.assignee.trim() !== '') params.set('assignee', filters.assignee.trim());
  for (const tag of filters.tags) params.append('tags', tag);
  if (filters.text.trim() !== '') params.set('text', filters.text.trim());
  if (filters.blocked) params.set('blocked', 'true');
  if (filters.withQuestions) params.set('questions', 'true');
  if (filters.withRemarks) params.set('remarks', 'true');
  if (filters.query.trim() !== '') params.set('query', filters.query.trim());
  if (filters.sort !== DEFAULT_SORT) params.set('sort', filters.sort);
  if (filters.cursor !== '') params.set('cursor', filters.cursor);

  // Умолчание в адрес не пишется, а «ничего не свёрнуто» пишется пустым значением:
  // без него это состояние не отличить от «параметра нет».
  if (!sameStatuses(filters.collapsed, DEFAULT_COLLAPSED)) {
    if (filters.collapsed.length === 0) params.set('collapsed', '');
    else for (const status of filters.collapsed) params.append('collapsed', status);
  }

  return params;
}

/** Одинаковы ли наборы статусов: порядок в них ничего не значит. */
function sameStatuses(left: TaskStatus[], right: TaskStatus[]): boolean {
  return left.length === right.length && left.every((status) => right.includes(status));
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
  const board = filters.view === 'board';

  const paging = {
    // На доске порядок задан её устройством: столбец — это статус, а внутри столбца
    // свежие сверху. Чужая сортировка перемешала бы карточки внутри столбцов, и человек
    // не смог бы объяснить себе порядок.
    sort: [board ? DEFAULT_SORT : filters.sort],
    // Курсор доски живёт в её собственной подгрузке, а не в адресе: страницы там
    // накапливаются, а не заменяют друг друга.
    cursor: board || filters.cursor === '' ? undefined : filters.cursor,
  };

  const query = filters.query.trim();
  if (query !== '') return { query, ...paging };

  return {
    queue: filters.queue === '' ? undefined : [filters.queue],
    // Столбцы доски и есть отбор по статусу: отбирать ещё и параметром значило бы
    // показывать пустые столбцы рядом с непустыми и врать, что задач в них нет.
    status: !board && filters.status.length > 0 ? filters.status : undefined,
    priority: filters.priority.length > 0 ? filters.priority : undefined,
    assignee: filters.assignee.trim() === '' ? undefined : [filters.assignee.trim()],
    tags: filters.tags.length > 0 ? filters.tags : undefined,
    text: filters.text.trim() === '' ? undefined : filters.text.trim(),
    blocked: filters.blocked ? true : undefined,
    // Флажки признаков уезжают одной строкой языка запросов: структурные параметры
    // `open_questions` и `open_remarks` принимают точное число, а спрашивается
    // диапазон «больше нуля». Два флажка складываются через `and` — так же, как их
    // читает человек: «есть вопросы **и** есть замечания».
    query: conditionsOf(filters),
    ...paging,
  };
}

/** Условия-флажки одной строкой языка запросов; `undefined`, если не отмечено ничего. */
function conditionsOf(filters: TaskFilters): string | undefined {
  const conditions = [
    filters.withQuestions ? OPEN_QUESTIONS_CONDITION : null,
    filters.withRemarks ? OPEN_REMARKS_CONDITION : null,
  ].filter((condition) => condition !== null);

  return conditions.length === 0 ? undefined : conditions.join(' and ');
}

/**
 * Есть ли хоть одно условие: по этому пустая выдача выбирает себе подсказку.
 *
 * Считается через запись в адрес, а не своим перечислением полей: новый фильтр иначе
 * пришлось бы вспомнить в двух местах, и забытый здесь тихо превратил бы «ничего не
 * нашлось по вашим условиям» в «в очереди пусто».
 *
 * Очередь условием не считается: она стала местом в интерфейсе (UI-38). Пустая очередь
 * — это «здесь пока ничего нет», а не «ваши условия ничего не нашли», и предлагать
 * сброс, который вынесет человека из очереди, здесь нечего.
 */
export function hasConditions(filters: TaskFilters): boolean {
  const conditions = writeFilters({
    ...filters,
    ...PLACE,
    sort: DEFAULT_SORT,
    cursor: '',
    collapsed: DEFAULT_COLLAPSED,
  });
  return [...conditions.keys()].length > 0;
}

/**
 * Что в адресе списка называет место, а не условие: очередь и вид.
 *
 * Сброс отбора их не трогает — человек остаётся там, где стоял, и смотрит тем же
 * видом; «уйти из очереди» — отдельное действие, и делается оно в боковой панели.
 */
export const PLACE: Pick<TaskFilters, 'queue' | 'view'> = { queue: '', view: 'table' };

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
