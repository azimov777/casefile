import type { Entry, EntryType } from '@/entities/entry';

/**
 * Кадр живого потока: та же запись дела, что и в ленте, плюс её сквозной номер `seq`.
 *
 * Владелец записи — задача, проект или область (TRK#128), и назван
 * ровно один из четырёх: `taskKey` у записи дела задачи, `projectKey` у записи дела проекта
 * (TRK-156), `area` — адрес `TRK/promotion` у записи дела области (TRK-557), `discussion` —
 * адрес `TRK~7` у записи дела обсуждения (TRK-669, TRK-672).
 *
 * `seq` — курсор ленты: с него поток продолжается после обрыва
 * (трекер: заметка области `TRK/journal#5`).
 */
export interface JournalFrame {
  seq: number;
  type: EntryType;
  taskKey: string | null;
  projectKey: string | null;
  area: string | null;
  discussion: string | null;
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
    const area = typeof entry.area === 'string' ? entry.area : null;
    // Владелец не назван вовсе — кадр негодный, а не «ничей»: у настоящей записи он
    // есть всегда.
    const discussion = typeof entry.discussion === 'string' ? entry.discussion : null;
    if (taskKey === null && projectKey === null && area === null && discussion === null) {
      return null;
    }
    return { seq: entry.seq, type: entry.type, taskKey, projectKey, area, discussion, entry };
  } catch {
    return null;
  }
}
