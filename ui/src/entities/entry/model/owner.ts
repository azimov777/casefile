/**
 * Владелец дела: задача, проект (TRK-156, `../docs/CONCEPT.md`, 3.4) или область
 * проекта (TRK-557, 3.7).
 *
 * Механика у всех дел одна — опись, тела по номеру, адрес записи, — и различаются они
 * только путём в API и в браузере. Поэтому владелец едет одним значением, а не тройкой
 * ключей, где две трети всегда пусты. Ключ области — её адрес `TRK/promotion`.
 */
export interface EntryOwner {
  kind: 'task' | 'project' | 'area' | 'discussion';
  key: string;
}

/**
 * Ссылка на запись словами трекера: `TRK-42#12` у задачи, `TRK#7` у проекта,
 * `TRK/promotion#3` у области — одна форма.
 */
export function entryReference(owner: EntryOwner, no: number): string {
  return `${owner.key}#${no}`;
}

/**
 * Владелец записи по её ключам: у записи непуст ровно один из `task_key`, `project_key`,
 * `area` и `discussion`.
 */
export function ownerOfEntry(entry: {
  task_key?: string | null;
  project_key?: string | null;
  area?: string | null;
  discussion?: string | null;
}): EntryOwner {
  if (entry.task_key != null) return { kind: 'task', key: entry.task_key };
  if (entry.discussion != null) return { kind: 'discussion', key: entry.discussion };
  if (entry.area != null) return { kind: 'area', key: entry.area };
  return { kind: 'project', key: entry.project_key ?? '' };
}
