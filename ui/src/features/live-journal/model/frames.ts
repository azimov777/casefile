import type { Entry, EntryType } from '@/entities/entry';

/**
 * Кадр живого потока: та же запись дела, что и в ленте, плюс её сквозной номер `seq`.
 *
 * Владелец записи — задача или проект (`CONCEPT.md`, 3.4), и назван ровно один из двух
 * ключей: `taskKey` у записи дела задачи, `projectKey` у записи дела проекта (TRK-156).
 *
 * `seq` — курсор ленты: с него поток продолжается после обрыва
 * (`../docs/DEVELOPMENT.md`, «Лента журнала»).
 */
export interface JournalFrame {
  seq: number;
  type: EntryType;
  taskKey: string | null;
  projectKey: string | null;
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
    // Владелец не назван вовсе — кадр негодный, а не «ничей»: у настоящей записи он
    // есть всегда.
    if (taskKey === null && projectKey === null) return null;
    return { seq: entry.seq, type: entry.type, taskKey, projectKey, entry };
  } catch {
    return null;
  }
}
