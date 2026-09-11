import type { Entry, EntryType } from '@/entities/entry';

/**
 * Кадр живого потока: та же запись дела, что и в ленте, плюс её сквозной номер `seq`.
 *
 * `seq` — курсор ленты: с него поток продолжается после обрыва
 * (`../docs/DEVELOPMENT.md`, «Лента журнала»).
 */
export interface JournalFrame {
  seq: number;
  type: EntryType;
  taskKey: string;
  entry: Entry;
}

/**
 * Разбирает кадр SSE. Негодный кадр — не повод рвать поток: следующая запись может
 * быть в порядке, а мы просто не знаем, что делать с этой.
 */
export function parseFrame(data: string): JournalFrame | null {
  try {
    const entry = JSON.parse(data) as Entry;
    if (typeof entry.seq !== 'number' || typeof entry.task_key !== 'string') return null;
    return { seq: entry.seq, type: entry.type, taskKey: entry.task_key, entry };
  } catch {
    return null;
  }
}
