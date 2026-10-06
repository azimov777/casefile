/**
 * Владелец дела: задача, проект (TRK-156, `../docs/CONCEPT.md`, 3.4) или направление
 * проекта (TRK-557, 3.7).
 *
 * Механика у всех дел одна — опись, тела по номеру, адрес записи, — и различаются они
 * только путём в API и в браузере. Поэтому владелец едет одним значением, а не тройкой
 * ключей, где две трети всегда пусты. Ключ направления — его адрес `TRK/promotion`.
 */
export interface EntryOwner {
  kind: 'task' | 'project' | 'direction';
  key: string;
}

/**
 * Ссылка на запись словами трекера: `TRK-42#12` у задачи, `TRK#7` у проекта,
 * `TRK/promotion#3` у направления — одна форма.
 */
export function entryReference(owner: EntryOwner, no: number): string {
  return `${owner.key}#${no}`;
}

/**
 * Владелец записи по её ключам: у записи непуст ровно один из `task_key`, `project_key`
 * и `direction`.
 */
export function ownerOfEntry(entry: {
  task_key?: string | null;
  project_key?: string | null;
  direction?: string | null;
}): EntryOwner {
  if (entry.task_key != null) return { kind: 'task', key: entry.task_key };
  if (entry.direction != null) return { kind: 'direction', key: entry.direction };
  return { kind: 'project', key: entry.project_key ?? '' };
}
