import type { TaskFeatures, TaskListRequest, TaskStatus } from '../api/tasks';

/*
 * «Ждёт ответа» — не хранимый статус, а вычисляемое положение (TRK-568, CONCEPT.md 3.3):
 * у задачи открыт вопрос с `blocking`. Хранимый статус `waiting` бэкенд снимает
 * (TRK-573), а пока он есть, интерфейс показывает по нему тоже — одной переходной
 * веткой, `LEGACY_WAITING` ниже. Условие «статус waiting» в интерфейсе живёт здесь и
 * больше нигде в отборах и тестах отбора.
 */

/** Столбец доски «Ждёт ответа» стоит на месте статуса `waiting` в перечислении. */
export const WAITING_COLUMN = 'waiting' satisfies TaskStatus;

/** Статусы, в которых открытый вопрос `blocking` переводит задачу в «Ждёт ответа». */
const HELD_STATUSES = ['backlog', 'open', 'in_progress'] as const satisfies readonly TaskStatus[];

const HAS_BLOCKING = 'open_blocking_questions: > 0';
const NO_BLOCKING = 'open_blocking_questions: 0';

/**
 * Переходная ветка: задача, у которой хранимый статус ещё `waiting`. Её убирает
 * задача бэкенда (TRK-573) вместе со статусом — одна правка здесь.
 */
export const LEGACY_WAITING = 'status: waiting';

/**
 * Условие столбца на языке запросов, поверх которого бэкенд сам фильтрует по `status`
 * для остальных столбцов. `null` — столбцу дополнительное условие не нужно.
 *
 * - «Ждёт ответа»: открытый вопрос `blocking` у задачи из работы — или старый статус;
 * - `backlog`, `open`, `in_progress`: такие задачи исключены, задача стоит в одном столбце;
 * - `done`, `cancelled`: вопросы им не мешают.
 */
export function columnCondition(status: TaskStatus): string | null {
  if (status === WAITING_COLUMN) {
    return `(status: in ${HELD_STATUSES.join(', ')} and ${HAS_BLOCKING}) or ${LEGACY_WAITING}`;
  }
  if ((HELD_STATUSES as readonly string[]).includes(status)) return NO_BLOCKING;
  return null;
}

/**
 * Отбор столбца доски: отбор человека плюс столбец. У «Ждёт ответа» статуса в отборе
 * нет вовсе — его целиком выражает условие; у прочих статус остаётся параметром.
 */
export function columnRequest(status: TaskStatus, params: TaskListRequest): TaskListRequest {
  return {
    ...params,
    status: status === WAITING_COLUMN ? undefined : [status],
    column: status,
  };
}

/** Ждёт ли задача ответа человека: открытый вопрос `blocking` или старый статус. */
export function isAwaitingAnswer(
  status: string | null | undefined,
  features: TaskFeatures | null | undefined,
): boolean {
  return (
    status === WAITING_COLUMN ||
    ((features?.open_blocking_questions ?? 0) > 0 &&
      (HELD_STATUSES as readonly string[]).includes(status ?? ''))
  );
}
