/**
 * Владелец дела: задача или проект (TRK-156, `../docs/CONCEPT.md`, 3.4).
 *
 * Механика у обоих дел одна — опись, тела по номеру, адрес записи, — и различаются они
 * только путём в API и в браузере. Поэтому владелец едет одним значением, а не парой
 * `taskKey`/`projectKey`, где одна половина всегда пуста.
 */
export interface EntryOwner {
  kind: 'task' | 'project';
  key: string;
}

/** Ссылка на запись словами трекера: `TRK-42#12` у задачи, `TRK#7` у проекта — одна форма. */
export function entryReference(owner: EntryOwner, no: number): string {
  return `${owner.key}#${no}`;
}

/** Владелец записи по её ключам: у записи непуст ровно один из `task_key` и `project_key`. */
export function ownerOfEntry(entry: {
  task_key?: string | null;
  project_key?: string | null;
}): EntryOwner {
  return entry.task_key != null
    ? { kind: 'task', key: entry.task_key }
    : { kind: 'project', key: entry.project_key ?? '' };
}
