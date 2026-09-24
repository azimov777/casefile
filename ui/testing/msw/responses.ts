import { HttpResponse } from 'msw';
import type { components } from '@/shared/api';

/** Источник, на который ходит приложение в тестах (см. `env` в vite.config.ts). */
export const API = 'http://localhost:3000';

/**
 * Конфигурация установки. Тот же источник, что и у API, не случайно: и статику,
 * и `/api` приложение спрашивает у своего источника, а в jsdom им служит адрес
 * страницы.
 */
export const CONFIG = `${API}/config.json`;

type Bootstrap = components['schemas']['BootstrapRead'];
type Task = components['schemas']['TaskSearchRead'];
type PageMeta = components['schemas']['PageMeta'];
type TaskPackage = components['schemas']['TaskPackageRead'];
type TaskDetails = components['schemas']['TaskRead'];
type Entry = components['schemas']['EntryRead'];
type EntryHeading = components['schemas']['EntryHeadingRead'];
type Summary = components['schemas']['SummaryEntryRead'];
type Question = components['schemas']['QuestionEntryRead'];
type Remark = components['schemas']['RemarkEntryRead'];
type AccessToken = components['schemas']['TokenRead'];
type Participant = components['schemas']['ParticipantRead'];

/** Ответ-ресурс в оболочке контракта. */
export function data<T>(payload: T, status = 200) {
  return HttpResponse.json({ data: payload }, { status });
}

/** Отказ в оболочке контракта. */
export function failure(
  code: string,
  status: number,
  message = 'Error',
  details: Record<string, unknown> = {},
) {
  return HttpResponse.json({ error: { code, message, details } }, { status });
}

const AUTHOR = { kind: 'tracker', signature: null } as const;
const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-01T10:00:00Z' };

/**
 * Первый кадр. Токен сеанса по умолчанию набора `task`, у которого запись закрыта:
 * тест, которому нужна запись, называет `main` явно через `overrides`.
 */
export function bootstrap(overrides: Partial<Bootstrap> = {}): Bootstrap {
  return {
    participant: {
      id: '11111111-1111-1111-1111-111111111111',
      kind: 'human',
      name: 'owner',
      description: 'Владелец установки',
      created_by: AUTHOR,
      ...STAMPS,
    },
    token: { id: '33333333-3333-3333-3333-333333333333', scope: 'task' },
    projects: [
      {
        id: '22222222-2222-2222-2222-222222222222',
        key: 'DEMO',
        title: 'Демонстрация',
        description: '',
        last_task_number: 7,
        created_by: AUTHOR,
        ...STAMPS,
      },
    ],
    open_questions: 2,
    ...overrides,
  };
}

/**
 * Страница коллекции в оболочке контракта: `data` плюс `meta` с курсором.
 *
 * `total` здесь нет намеренно: из всех коллекций API его считает только список задач
 * (TRK-41), у прочих в нём `null` — «не считали». Страницу списка задач поэтому
 * собирают `taskPage`, а не этим.
 */
export function collection<T>(items: T[], meta: Partial<PageMeta> = {}) {
  return HttpResponse.json({
    data: items,
    meta: { has_more: false, next_cursor: null, ...meta },
  });
}

/**
 * Страница `GET /api/v1/tasks`. Отличается от прочих коллекций общим числом выдачи:
 * список задач заполняет `meta.total` всегда, и по нему интерфейс считает страницы.
 * Умолчание — длина отданного куска: столько задач и нашлось, если страница одна.
 */
export function taskPage(items: Task[], meta: Partial<PageMeta> = {}) {
  return collection(items, { total: items.length, ...meta });
}

/**
 * Ответ списка задач по параметрам самого запроса: отбор по статусу, размер страницы
 * и курсор.
 *
 * Нужен там, где выдачу читают столбцами доски: шесть запросов одного прогона
 * различаются только `status`, и общий ответ на все шесть показал бы одну и ту же
 * задачу в каждом столбце. Курсор здесь — смещение строкой: тесту важно, что второй
 * запрос приносит продолжение, а не то, как курсор устроен у бэкенда.
 */
export function taskListing(url: URL, items: Task[]) {
  const wanted = url.searchParams.getAll('status');
  const matched =
    wanted.length === 0 ? items : items.filter((row) => wanted.includes(row.status ?? ''));

  const from = Number(url.searchParams.get('cursor') ?? 0);
  const limit = Number(url.searchParams.get('limit') ?? matched.length);
  const next = from + limit;

  return collection(matched.slice(from, next), {
    total: matched.length,
    has_more: next < matched.length,
    next_cursor: next < matched.length ? String(next) : null,
  });
}

/**
 * Доступ так, как его отдаёт `GET /api/v1/tokens`: без секрета — его нет ни в списке,
 * ни в базе. Умолчание — живой ключ участника `owner` набора `task`.
 */
export function accessToken(overrides: Partial<AccessToken> = {}): AccessToken {
  return {
    id: '55555555-5555-5555-5555-555555555555',
    name: 'local-ui',
    scope: 'task',
    participant: 'owner',
    created_by: AUTHOR,
    created_at: '2026-09-01T10:00:00Z',
    last_used_at: null,
    revoked_at: null,
    ...overrides,
  };
}

/** Участник реестра: из него собран выбор «кому выпускать токен». */
export function participant(name: string, overrides: Partial<Participant> = {}): Participant {
  return {
    id: `participant-${name}`,
    kind: 'agent',
    name,
    description: '',
    created_by: AUTHOR,
    ...STAMPS,
    ...overrides,
  };
}

/**
 * Строка выдачи со всеми полями, которые просит список. Признаки заданы явно:
 * ради них строка и приходит целиком, без запроса на задачу.
 *
 * Родителя по умолчанию нет — `null`, как у задачи верхнего уровня в ответе бэкенда
 * (TRK-95, одним значением с TRK-135), а не отсутствие поля: список его просит, и
 * бэкенд его отдаёт всегда.
 */
export function task(key: string, overrides: Partial<Task> = {}): Task {
  return {
    key,
    title: `Задача ${key}`,
    status: 'open',
    assignee: null,
    priority: 'normal',
    updated_at: '2026-09-01T10:00:00Z',
    features: {
      blocked: false,
      open_questions: 0,
      open_blocking_questions: 0,
      open_remarks: 0,
      last_summary_at: null,
      last_entry_at: '2026-09-01T10:00:00Z',
    },
    parent: null,
    ...overrides,
  };
}

const AGENT = { kind: 'agent', signature: 'demo_agent' } as const;

/** Поля задачи целиком: карточка просит их все, в отличие от строки списка. */
export function taskDetails(key: string, overrides: Partial<TaskDetails> = {}): TaskDetails {
  return {
    id: '33333333-3333-3333-3333-333333333333',
    key,
    project: {
      key: key.split('-')[0] ?? 'DEMO',
      title: 'Демонстрация',
      description: 'Демонстрационный проект: на нём видно каждый экран интерфейса.',
    },
    title: `Задача ${key}`,
    description: 'Отказ разбора запроса приходит без списка допустимых полей.',
    goal: 'Отказ поиска чинится с первой попытки',
    context: 'Разбор живёт в `query_language.py`',
    constraints: 'Коды ошибок не переименовывать',
    output: 'Поля `details.allowed` у отказов разбора',
    checks: [
      'Незнакомое поле отвечает списком допустимых',
      'Неприменимый оператор отвечает списком',
    ],
    status: 'in_progress',
    assignee: 'nightly_agent',
    priority: 'normal',
    version: 4,
    created_by: AGENT,
    ...STAMPS,
    ...overrides,
  };
}

/**
 * Строка описи: заголовок записи без тела.
 *
 * Тип строки берётся из фактов, а не задаётся рядом с ними: факты размечены по `type`,
 * и строка, у которой `type` не совпал бы с разметкой фактов, — не тот ответ, который
 * бэкенд умеет дать. У записей агента и человека факты состоят из одной разметки.
 */
export function heading(
  no: number,
  facts: EntryHeading['facts'],
  title: string,
  overrides: Partial<EntryHeading> = {},
): EntryHeading {
  return {
    no,
    type: facts.type,
    author: AGENT,
    created_at: '2026-09-01T10:00:00Z',
    title,
    facts,
    ...overrides,
  };
}

/** Общие поля любой записи: то, что есть у всех типов до нагрузки. */
function entryBase(no: number, taskKey: string, title: string, body: string) {
  return {
    id: `44444444-4444-4444-4444-00000000000${no}`,
    seq: 100 + no,
    no,
    task_key: taskKey,
    // Запись задачи: ключ проекта у неё всегда `null` (TRK-156).
    project_key: null,
    author: AGENT,
    title,
    body,
    created_at: '2026-09-01T10:00:00Z',
  };
}

export function summaryEntry(no: number, taskKey: string): Summary {
  return {
    ...entryBase(no, taskKey, 'Дособрать `details.allowed` и подшить новый вердикт', ''),
    type: 'summary',
    payload: {
      done: 'Первая проверка пройдена, вторая провалена',
      remaining: 'Собрать список операторов для сравнимых полей',
      blockers: 'Задача блокера ещё не закрыта',
      next_step: 'Дособрать `details.allowed` и подшить новый вердикт',
    },
  };
}

export function questionEntry(no: number, taskKey: string, blocking = true): Question {
  return {
    ...entryBase(
      no,
      taskKey,
      'Удалять ли записи отменённых задач через год',
      'Хранение стоит денег, но дело неизменяемо.',
    ),
    type: 'question',
    payload: { addressees: ['owner'], blocking },
  };
}

/** Ответ человека так, как его возвращает `POST /entries`: с присвоенным номером. */
export function answerEntry(no: number, taskKey: string, questionNo: number, body: string): Entry {
  return {
    ...entryBase(no, taskKey, '', body),
    author: { kind: 'human', signature: 'owner' },
    type: 'answer',
    payload: { question_no: questionNo },
  };
}

/** Замечание человека: то, что видно в пакете задачи и во входящей. */
export function remarkEntry(no: number, taskKey: string, title = 'Вышло не то'): Remark {
  return {
    ...entryBase(no, taskKey, title, 'В списке это выглядит как потерянные задачи.'),
    author: { kind: 'human', signature: 'owner' },
    type: 'remark',
  };
}

/** Разбор замечания агентом: исход и, при `accepted`, ключ задачи-продолжения. */
export function resolutionEntry(
  no: number,
  taskKey: string,
  remarkNo: number,
  overrides: Partial<Extract<Entry, { type: 'resolution' }>['payload']> = {},
): Entry {
  return {
    ...entryBase(no, taskKey, '', 'Согласен, работа ушла в отдельную задачу.'),
    type: 'resolution',
    payload: { remark_no: remarkNo, outcome: 'accepted', task: 'DEMO-2', ...overrides },
  };
}

export function verdictEntry(no: number, taskKey: string): Entry {
  return {
    ...entryBase(
      no,
      taskKey,
      'Verdict on check 2: failed',
      '`query=priority > high` отвечает отказом, но `details.allowed` пуст. См. DEMO-2 и DEMO-6#4.',
    ),
    type: 'verdict',
    payload: { check_no: 2, outcome: 'failed' },
  };
}

/** Пакет карточки: всё, чем экран рисуется, одним ответом. */
export function taskPackage(key: string, overrides: Partial<TaskPackage> = {}): TaskPackage {
  return {
    task: taskDetails(key),
    parent: null,
    children: [],
    links: [
      {
        kind: 'blocked_by',
        other: { key: 'DEMO-2', title: 'Лента журнала теряет записи', status: 'in_progress' },
        author: AGENT,
        created_at: '2026-09-01T10:00:00Z',
      },
    ],
    features: {
      blocked: true,
      open_questions: 0,
      open_blocking_questions: 0,
      open_remarks: 0,
      last_summary_at: '2026-09-01T10:00:00Z',
    },
    summary: summaryEntry(7, key),
    questions: [],
    remarks: [],
    transitions: ['done', 'open', 'cancelled'],
    index: [
      heading(1, { type: 'created' }, 'Task created'),
      heading(
        2,
        { type: 'status_changed', from_status: 'backlog', to_status: 'open', has_reason: false },
        'Status changed: backlog -> open',
      ),
      heading(
        3,
        {
          type: 'status_changed',
          from_status: 'open',
          to_status: 'in_progress',
          has_reason: false,
        },
        'Status changed: open -> in_progress',
      ),
      heading(4, { type: 'decision' }, 'Список допустимого собирается по типу поля'),
      heading(5, { type: 'verdict', check_no: 1, outcome: 'passed' }, 'Verdict on check 1: passed'),
      heading(6, { type: 'verdict', check_no: 2, outcome: 'failed' }, 'Verdict on check 2: failed'),
      heading(7, { type: 'summary' }, 'Дособрать `details.allowed` и подшить новый вердикт'),
    ],
    ...overrides,
  };
}

/**
 * Запись любого типа с осмысленной нагрузкой. Тип выбирается параметром, поэтому тест
 * может пройти по всему перечислению контракта и проверить каждое представление,
 * не выписывая пятнадцать фикстур руками.
 */
export function entryOfType(no: number, taskKey: string, type: Entry['type']): Entry {
  const base = entryBase(no, taskKey, `Запись типа ${type}`, 'Тело записи со ссылкой на DEMO-2.');

  switch (type) {
    case 'summary':
      return summaryEntry(no, taskKey);
    case 'question':
      return questionEntry(no, taskKey);
    case 'answer':
      return { ...base, type, payload: { question_no: 1 } };
    case 'verdict':
      return verdictEntry(no, taskKey);
    case 'status_changed':
      return {
        ...base,
        type,
        payload: { from: 'in_progress', to: 'open', reason: 'Задан блокирующий вопрос' },
      };
    case 'section_changed':
      return {
        ...base,
        body: '',
        type,
        payload: { field: 'goal', before: 'Старая цель', after: 'Новая цель' },
      };
    case 'field_changed':
      return {
        ...base,
        body: '',
        type,
        payload: { field: 'priority', before: 'normal', after: 'critical' },
      };
    case 'assignee_changed':
      return { ...base, body: '', type, payload: { before: null, after: 'demo_agent' } };
    case 'link_added':
    case 'link_removed':
      return { ...base, body: '', type, payload: { kind: 'blocked_by', other: 'DEMO-2' } };
    case 'resolution':
      return { ...base, type, payload: { remark_no: 1, outcome: 'accepted', task: 'DEMO-2' } };
    // Записи об атрибутах бывают только в деле проекта (TRK-157): владелец — проект.
    case 'attribute_created':
      return {
        ...base,
        task_key: null,
        project_key: 'DEMO',
        body: '',
        type,
        payload: { name: 'repo', after: 'github.com/demo', reason: null },
      };
    case 'attribute_changed':
      return {
        ...base,
        task_key: null,
        project_key: 'DEMO',
        body: '',
        type,
        payload: {
          name: 'repo',
          before: 'github.com/old',
          after: 'github.com/demo',
          reason: 'Репозиторий переехал',
        },
      };
    case 'attribute_removed':
      return {
        ...base,
        task_key: null,
        project_key: 'DEMO',
        body: '',
        type,
        payload: { name: 'repo', before: 'github.com/demo', reason: 'Репозиторий закрыт' },
      };
    default:
      // `created`, `decision`, `attempt`, `finding`, `artifact`, `remark`, `note`:
      // общая форма.
      return { ...base, type, refs: ['DEMO-2', 'https://example.test/build/42'] };
  }
}
