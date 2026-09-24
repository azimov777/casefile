import {
  TASK_PAGE_SIZE,
  TASK_PRIORITIES,
  TASK_STATUSES,
  type TaskListRequest,
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
  project: string;
  status: TaskStatus[];
  priority: TaskPriority[];
  assignee: string;
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
  /**
   * Открытая страница таблицы, с 1. В адресе стоит номером (`?page=3`), а в запрос
   * уезжает смещением: `offset = (page - 1) * TASK_PAGE_SIZE` (TRK-41). Номер, а не
   * смещение, потому что адрес списка пересылают человеку, и «страница 3» он
   * прочтёт, а «смещение 100» — нет.
   */
  page: number;
  /**
   * Свёрнутые столбцы доски. Живёт в адресе, как и всё, что меняет вид выдачи:
   * ссылка на доску должна открыться тем же самым, а не разворачивать столбцы,
   * которые отправитель свернул.
   */
  collapsed: TaskStatus[];
  /**
   * Показывать архив — закрытые задачи, в делах которых давно не писали (UI-97).
   *
   * По умолчанию архив скрыт, и это умолчание списка, а не условие отбора: выдачу
   * оно сужает, но чипом не значится и сбросом отбора не возвращается (см.
   * `hasConditions`, `useTaskFilters`). В адресе живёт так же, как всё, что меняет
   * состав выдачи: пересланная ссылка на архив обязана открыть архив.
   */
  showArchive: boolean;
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
 * (`../docs/CONCEPT.md`, 3.3). Свернув его, доска спрятала бы от человека
 * единственный столбец, адресованный лично ему, — и он узнавал бы о своём ходе
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
 * мимо дела — приоритет, исполнитель, разделы задания — видна только через них.
 */
export const TASK_SORTS = [
  '-last_entry_at',
  'last_entry_at',
  '-updated_at',
  'updated_at',
  '-priority',
  'priority',
  'key',
  '-key',
] as const;

/**
 * Значение порядка из тех, что предлагает интерфейс. Подпись к нему живёт в словаре
 * (`tasks.filters.sort`), а не рядом со значением: ключ словаря — само значение,
 * и забытый перевод роняет сборку, а не показывает человеку `-last_entry_at`.
 */
export type TaskSort = (typeof TASK_SORTS)[number];

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
 *
 * С запросом человека складывается одно правило архива (UI-97) — и не здесь, а в
 * момент чтения (`hideArchive` в `entities/task`): там же, где склейка, живёт и
 * возврат её отказа в строку человека.
 */
export const OPEN_QUESTIONS_CONDITION = 'open_questions: > 0';

/** То же для замечаний: структурный параметр берёт точное число, а нужен диапазон. */
export const OPEN_REMARKS_CONDITION = 'open_remarks: > 0';

export const EMPTY_FILTERS: TaskFilters = {
  view: 'table',
  project: '',
  status: [],
  priority: [],
  assignee: '',
  text: '',
  blocked: false,
  withQuestions: false,
  withRemarks: false,
  query: '',
  sort: DEFAULT_SORT,
  page: 1,
  collapsed: DEFAULT_COLLAPSED,
  showArchive: false,
};

/**
 * Значение параметра `archive`, которым адрес говорит «архив показан». Слово, а не
 * `true`: у соседних флажков `true` значит «только такие» (`blocked=true`), и
 * `archived=true` читалось бы «только архив» — ровно наоборот.
 */
const ARCHIVE_SHOWN = 'shown';

/** Адрес → отбор. Неизвестные значения отбрасываются: см. `keepKnown`. */
export function readFilters(params: URLSearchParams): TaskFilters {
  const sort = params.get('sort');

  return {
    view: params.get('view') === 'board' ? 'board' : 'table',
    project: params.get('project') ?? '',
    status: keepKnown(params.getAll('status'), TASK_STATUSES),
    priority: keepKnown(params.getAll('priority'), TASK_PRIORITIES),
    assignee: params.get('assignee') ?? '',
    text: params.get('text') ?? '',
    blocked: params.get('blocked') === 'true',
    withQuestions: params.get('questions') === 'true',
    withRemarks: params.get('remarks') === 'true',
    query: params.get('query') ?? '',
    sort: isTaskSort(sort) ? sort : DEFAULT_SORT,
    page: readPage(params.get('page')),
    collapsed: params.has('collapsed')
      ? keepKnown(params.getAll('collapsed'), TASK_STATUSES)
      : DEFAULT_COLLAPSED,
    // Любое другое значение — умолчание: архив скрыт. Опечатка в адресе не вправе
    // вывалить человеку всю историю проекта.
    showArchive: params.get('archive') === ARCHIVE_SHOWN,
  };
}

/** Отбор → адрес. Пустое и умолчания в адрес не пишутся: ссылка остаётся читаемой. */
export function writeFilters(filters: TaskFilters): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.view === 'board') params.set('view', 'board');
  if (filters.project !== '') params.set('project', filters.project);
  for (const status of filters.status) params.append('status', status);
  for (const priority of filters.priority) params.append('priority', priority);
  if (filters.assignee.trim() !== '') params.set('assignee', filters.assignee.trim());
  if (filters.text.trim() !== '') params.set('text', filters.text.trim());
  if (filters.blocked) params.set('blocked', 'true');
  if (filters.withQuestions) params.set('questions', 'true');
  if (filters.withRemarks) params.set('remarks', 'true');
  if (filters.query.trim() !== '') params.set('query', filters.query.trim());
  if (filters.sort !== DEFAULT_SORT) params.set('sort', filters.sort);
  if (filters.page > 1) params.set('page', String(filters.page));
  if (filters.showArchive) params.set('archive', ARCHIVE_SHOWN);

  // Умолчание в адрес не пишется, а «ничего не свёрнуто» пишется пустым значением:
  // без него это состояние не отличить от «параметра нет».
  if (!sameStatuses(filters.collapsed, DEFAULT_COLLAPSED)) {
    if (filters.collapsed.length === 0) params.set('collapsed', '');
    else for (const status of filters.collapsed) params.append('collapsed', status);
  }

  return params;
}

function isTaskSort(value: string | null): value is TaskSort {
  return value !== null && (TASK_SORTS as readonly string[]).includes(value);
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
export function filtersToListParams(filters: TaskFilters): TaskListRequest {
  const board = filters.view === 'board';

  /*
   * Правило архива ложится поверх любого отбора, и поверх запроса человека тоже: его
   * строка складывается с правилом по «и» в момент чтения (`fetchTasks`). Здесь стоит
   * только признак — дата порога в ключ запроса не попадает (UI-97#7).
   */
  const archive = filters.showArchive ? {} : { hideArchived: true };

  const paging = {
    /*
     * Порядок один на оба вида: на доске он упорядочивает карточки внутри каждого
     * столбца — столбец читает ту же выдачу со своим статусом (`tasksColumnQueryOptions`).
     * До UI-130 доска навязывала свой порядок (`DEFAULT_SORT`), и выбранный в таблице
     * пропадал на доске; владелец попросил тот же выбор и там (UI-130#10).
     */
    sort: [filters.sort],
    /*
     * Номер страницы уезжает смещением: `offset` — второй адрес страницы рядом с
     * курсором, и вместе с ним он не принимается (`422 cursor_with_offset`). Первая
     * страница не адресуется вовсе: `offset=0` означает ровно то же, что его
     * отсутствие, и в запросе он был бы шумом.
     *
     * Доска сюда не попадает: страницы там копятся, а положение чтения живёт в её
     * собственной подгрузке (`tasksBoardQueryOptions`), а не в адресе.
     */
    offset: board || filters.page <= 1 ? undefined : (filters.page - 1) * TASK_PAGE_SIZE,
  };

  const query = filters.query.trim();
  if (query !== '') return { query, ...paging, ...archive };

  return {
    project: filters.project === '' ? undefined : [filters.project],
    // Столбцы доски и есть отбор по статусу: отбирать ещё и параметром значило бы
    // показывать пустые столбцы рядом с непустыми и врать, что задач в них нет.
    status: !board && filters.status.length > 0 ? filters.status : undefined,
    priority: filters.priority.length > 0 ? filters.priority : undefined,
    assignee: filters.assignee.trim() === '' ? undefined : [filters.assignee.trim()],
    text: filters.text.trim() === '' ? undefined : filters.text.trim(),
    blocked: filters.blocked ? true : undefined,
    // Флажки признаков уезжают одной строкой языка запросов: структурные параметры
    // `open_questions` и `open_remarks` принимают точное число, а спрашивается
    // диапазон «больше нуля». Два флажка складываются через `and` — так же, как их
    // читает человек: «есть вопросы **и** есть замечания».
    query: conditionsOf(filters),
    ...paging,
    ...archive,
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
 * нашлось по вашим условиям» в «в проекте пусто».
 *
 * Проект условием не считается: он стал местом в интерфейсе (UI-38). Пустой проект
 * — это «здесь пока ничего нет», а не «ваши условия ничего не нашли», и предлагать
 * сброс, который вынесет человека из проекта, здесь нечего.
 *
 * Показ архива условием тоже не считается: он выдачу расширяет, а не сужает, и сброс
 * его не трогает (UI-97). Без условий и с показанным архивом пустота — это пустота
 * проекта.
 */
export function hasConditions(filters: TaskFilters): boolean {
  const conditions = writeFilters({
    ...filters,
    ...PLACE,
    sort: DEFAULT_SORT,
    page: 1,
    collapsed: DEFAULT_COLLAPSED,
    showArchive: false,
  });
  return [...conditions.keys()].length > 0;
}

/**
 * Что в адресе списка называет место, а не условие: проект и вид.
 *
 * Сброс отбора их не трогает — человек остаётся там, где стоял, и смотрит тем же
 * видом; «уйти из проекта» — отдельное действие, и делается оно в боковой панели.
 */
export const PLACE: Pick<TaskFilters, 'project' | 'view'> = { project: '', view: 'table' };

/**
 * Номер страницы из адреса. Всё, что не целое число больше нуля, читается как первая
 * страница: `?page=abc`, `?page=0` и `?page=-1` обязаны открыть список, а не отказ.
 *
 * Сюда же приходит и старая ссылка с `cursor=…`: параметра `page` в ней нет, и она
 * открывает начало списка — тем же правилом, каким после UI-41 отбрасывается `tags=`.
 * Курсор в адресе таблицы больше не значит ничего: страница адресуется смещением,
 * а прислать бэкенду оба адреса сразу — `422 cursor_with_offset`.
 */
function readPage(value: string | null): number {
  const page = Number(value);
  return Number.isInteger(page) && page > 1 ? page : 1;
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
