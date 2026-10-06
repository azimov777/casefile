import type { Entry, EntryType } from '@/entities/entry';

/**
 * Кадр живого потока: та же запись дела, что и в ленте, плюс её сквозной номер `seq`.
 *
 * Владелец записи — задача, проект или направление (`CONCEPT.md`, 3.4, 3.7), и назван
 * ровно один из трёх: `taskKey` у записи дела задачи, `projectKey` у записи дела проекта
 * (TRK-156), `direction` — адрес `TRK/promotion` у записи дела направления (TRK-557).
 *
 * `seq` — курсор ленты: с него поток продолжается после обрыва
 * (`../docs/DEVELOPMENT.md`, «Лента журнала»).
 */
export interface JournalFrame {
  seq: number;
  type: EntryType;
  taskKey: string | null;
  projectKey: string | null;
  direction: string | null;
  entry: Entry;
}

/**
 * Разбирает кадр SSE. Негодный кадр — не повод рвать поток: следующая запись может
 * быть в порядке, а мы просто не знаем, что делать с этой.
 */
export function parseFrame(data: string): JournalFrame | null {
  try {
    const entry = JSON.parse(data) as Entry;
    if (typeof entry.seq !== 'number') return null;
    const taskKey = typeof entry.task_key === 'string' ? entry.task_key : null;
    const projectKey = typeof entry.project_key === 'string' ? entry.project_key : null;
    const direction = typeof entry.direction === 'string' ? entry.direction : null;
    // Владелец не назван вовсе — кадр негодный, а не «ничей»: у настоящей записи он
    // есть всегда.
    if (taskKey === null && projectKey === null && direction === null) return null;
    return { seq: entry.seq, type: entry.type, taskKey, projectKey, direction, entry };
  } catch {
    return null;
  }
}
