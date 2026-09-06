import { HttpResponse } from 'msw';
import type { components } from '@/shared/api';

/** Источник, на который ходит приложение в тестах (см. `env` в vite.config.ts). */
export const API = 'http://localhost:3000';

type Bootstrap = components['schemas']['BootstrapRead'];
type Task = components['schemas']['TaskSearchRead'];
type PageMeta = components['schemas']['PageMeta'];
type TaskPackage = components['schemas']['TaskPackageRead'];
type TaskDetails = components['schemas']['TaskRead'];
type Entry = components['schemas']['EntryRead'];
type EntryHeading = components['schemas']['EntryHeadingRead'];
type Summary = components['schemas']['SummaryEntryRead'];
type Question = components['schemas']['QuestionEntryRead'];

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
    queues: [
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

/** Страница коллекции в оболочке контракта: `data` плюс `meta` с курсором. */
export function collection<T>(items: T[], meta: Partial<PageMeta> = {}) {
  return HttpResponse.json({
    data: items,
    meta: { has_more: false, next_cursor: null, ...meta },
  });
}

/**
 * Строка выдачи со всеми полями, которые просит список. Признаки заданы явно:
 * ради них строка и приходит целиком, без запроса на задачу.
 */
export function task(key: string, overrides: Partial<Task> = {}): Task {
  return {
    key,
    title: `Задача ${key}`,
    status: 'open',
    assignee: null,
    tags: [],
    priority: 'normal',
    updated_at: '2026-09-01T10:00:00Z',
    features: {
      blocked: false,
      open_questions: 0,
      open_blocking_questions: 0,
      last_summary_at: null,
    },
    ...overrides,
  };
}

const AGENT = { kind: 'agent', signature: 'demo_agent' } as const;

/** Поля задачи целиком: карточка просит их все, в отличие от строки списка. */
export function taskDetails(key: string, overrides: Partial<TaskDetails> = {}): TaskDetails {
  return {
    id: '33333333-3333-3333-3333-333333333333',
    key,
    queue: { key: key.split('-')[0] ?? 'DEMO', title: 'Демонстрация' },
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
    tags: ['backend', 'search'],
    priority: 'normal',
    version: 4,
    created_by: AGENT,
    ...STAMPS,
    ...overrides,
  };
}

/** Строка описи: заголовок записи без тела. */
export function heading(
  no: number,
  type: EntryHeading['type'],
  title: string,
  overrides: Partial<EntryHeading> = {},
): EntryHeading {
  return {
    no,
    type,
    author: AGENT,
    created_at: '2026-09-01T10:00:00Z',
    title,
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
      last_summary_at: '2026-09-01T10:00:00Z',
    },
    summary: summaryEntry(7, key),
    questions: [],
    transitions: ['done', 'open', 'cancelled'],
    index: [
      heading(1, 'created', 'Task created'),
      heading(2, 'status_changed', 'Status changed: backlog -> open'),
      heading(3, 'status_changed', 'Status changed: open -> in_progress'),
      heading(4, 'decision', 'Список допустимого собирается по типу поля'),
      heading(5, 'verdict', 'Verdict on check 1: passed'),
      heading(6, 'verdict', 'Verdict on check 2: failed'),
      heading(7, 'summary', 'Дособрать `details.allowed` и подшить новый вердикт'),
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
    default:
      // `created`, `decision`, `attempt`, `finding`, `artifact`, `note`: общая форма.
      return { ...base, type, refs: ['DEMO-2', 'https://example.test/build/42'] };
  }
}
