import type { BadgeTone } from '@/shared/ui';
import type { TaskPriority, TaskStatus } from '../api/tasks';

/**
 * Соответствие «статус → тон» и «приоритет → тон».
 *
 * Перечислено ключами объекта через `satisfies Record<...>` — тем же приёмом, что
 * списки для фильтров (`api/tasks.ts`): статус, добавленный в контракт, обязан
 * уронить сборку, а не тихо остаться серым в списке, где его никто не хватится.
 *
 * Правило выбора тона: тон получает только то, что меняет решение человека.
 * Поэтому `open` нейтрален, хотя формально это «ждёт исполнителя»: открытых задач
 * большинство, и покрасив их, янтарный перестал бы значить что-либо. Взгляд
 * цепляется за то, что не серое, — и серым остаётся всё обычное.
 */
export const TASK_STATUS_TONE = {
  backlog: 'neutral',
  open: 'neutral',
  in_progress: 'progress',
  done: 'positive',
  cancelled: 'dropped',
} satisfies Record<TaskStatus, BadgeTone>;

/**
 * Приоритет красится только выше `normal`: `low` и `normal` — обычный ход дел,
 * а «важно» и «горит» человек обязан увидеть, не читая колонку.
 */
export const TASK_PRIORITY_TONE = {
  low: 'neutral',
  normal: 'neutral',
  high: 'attention',
  critical: 'danger',
} satisfies Record<TaskPriority, BadgeTone>;

/**
 * Тон статуса, пришедшего из выдачи списка. В строке списка статус необязателен:
 * набор полей задаётся запросом, и поля может не быть вовсе — тогда плашки нет,
 * и звать это некому. Здесь же нейтральный на случай значения вне контракта:
 * упасть на отрисовке списка из-за незнакомого статуса хуже, чем показать серым.
 */
export function statusTone(status: string | null | undefined): BadgeTone {
  if (status === null || status === undefined) return 'neutral';
  return TASK_STATUS_TONE[status as TaskStatus] ?? 'neutral';
}

export function priorityTone(priority: string | null | undefined): BadgeTone {
  if (priority === null || priority === undefined) return 'neutral';
  return TASK_PRIORITY_TONE[priority as TaskPriority] ?? 'neutral';
}
