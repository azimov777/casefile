import type { TaskFeatures, TaskListRequest, TaskStatus } from '../api/tasks';

/*
 * «Ждёт ответа» — не статус, а вычисляемое положение (TRK-568, CONCEPT.md 3.3): у
 * задачи открыт вопрос с `blocking`. Хранимого статуса ожидания у бэкенда нет (TRK-573),
 * а у доски есть столбец, который это положение показывает. Условие столбца в интерфейсе
 * живёт здесь и больше нигде в отборах и тестах отбора.
 */

/**
 * Ключ столбца доски «Ждёт ответа». Не статус: в перечислении статуса контракта его нет,
 * и в запрос он уходит условием (`columnCondition`), а не значением `status`. Ключ —
 * прежнее имя статуса, чтобы адреса со свёрнутым столбцом (`collapsed=waiting`) и
 * сквозные сценарии, находящие столбец по ключу, пережили снятие статуса.
 */
export const WAITING_COLUMN = 'waiting';

/** Столбец доски: статус из контракта или вычисляемое «Ждёт ответа». */
export type BoardColumn = TaskStatus | typeof WAITING_COLUMN;

/** Статусы, в которых открытый вопрос `blocking` переводит задачу в «Ждёт ответа». */
const HELD_STATUSES = ['backlog', 'open', 'in_progress'] as const satisfies readonly TaskStatus[];

const HAS_BLOCKING = 'open_blocking_questions: > 0';
const NO_BLOCKING = 'open_blocking_questions: 0';

/**
 * Столбцы доски по порядку: статусы из перечисления контракта, а «Ждёт ответа» — сразу
 * за последним из статусов, чьи задачи он забирает. Статусы берутся из контракта, а не
 * своим списком (`docs/FRONTEND.md`, «Доска без доски»): статус, добавленный или снятый
 * на бэкенде, приходит на доску перегенерацией клиента.
 */
export function boardColumns(statuses: readonly TaskStatus[]): BoardColumn[] {
  const last = Math.max(...HELD_STATUSES.map((status) => statuses.indexOf(status)));
  return [...statuses.slice(0, last + 1), WAITING_COLUMN, ...statuses.slice(last + 1)];
}

/**
 * Условие столбца на языке запросов, поверх которого бэкенд сам фильтрует по `status`
 * для остальных столбцов. `null` — столбцу дополнительное условие не нужно.
 *
 * - «Ждёт ответа»: открытый вопрос `blocking` у задачи из работы;
 * - `backlog`, `open`, `in_progress`: такие задачи исключены, задача стоит в одном столбце;
 * - `done`, `cancelled`: вопросы им не мешают.
 */
export function columnCondition(column: BoardColumn): string | null {
  if (column === WAITING_COLUMN) {
    return `status: in ${HELD_STATUSES.join(', ')} and ${HAS_BLOCKING}`;
  }
  if ((HELD_STATUSES as readonly string[]).includes(column)) return NO_BLOCKING;
  return null;
}

/**
 * Отбор столбца доски: отбор человека плюс столбец. У «Ждёт ответа» статуса в отборе
 * нет вовсе — его целиком выражает условие; у прочих статус остаётся параметром.
 */
export function columnRequest(column: BoardColumn, params: TaskListRequest): TaskListRequest {
  return {
    ...params,
    status: column === WAITING_COLUMN ? undefined : [column],
    column,
  };
}

/** Ждёт ли задача ответа человека: открытый вопрос `blocking` у задачи из работы. */
export function isAwaitingAnswer(
  status: string | null | undefined,
  features: TaskFeatures | null | undefined,
): boolean {
  return (
    (features?.open_blocking_questions ?? 0) > 0 &&
    (HELD_STATUSES as readonly string[]).includes(status ?? '')
  );
}
