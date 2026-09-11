import { queueOfKey } from '@/shared/lib';

/** Раздел, в котором человек находится. Совпадает с таблицей экранов `CONCEPT.md`, 3. */
export type Section = 'tasks' | 'task' | 'case' | 'questions' | 'connect' | 'access' | 'other';

export interface Place {
  section: Section;
  /**
   * Очередь, в которой человек работает: на списке — из отбора, внутри задачи —
   * из её ключа. `null` — очередь не выбрана (все задачи) или к месту не относится.
   */
  queue: string | null;
  /** Ключ задачи, если человек внутри неё. */
  taskKey: string | null;
}

/**
 * Где человек находится — по адресу и только по нему.
 *
 * Оболочке это нужно дважды: подсветить очередь и раздел в боковой панели и назвать
 * место в верхней полосе. Считается в одном месте, потому что иначе панель и полоса
 * однажды разойдутся в том, что считать текущим, — и человек увидит подсвеченным одно,
 * а прочитает другое.
 */
export function readPlace(pathname: string, params: URLSearchParams): Place {
  if (pathname === '/questions') {
    return { section: 'questions', queue: null, taskKey: null };
  }

  if (pathname === '/connect') {
    return { section: 'connect', queue: null, taskKey: null };
  }

  if (pathname === '/access') {
    return { section: 'access', queue: null, taskKey: null };
  }

  if (pathname === '/tasks') {
    const queue = params.get('queue') ?? '';
    return { section: 'tasks', queue: queue === '' ? null : queue, taskKey: null };
  }

  // `/tasks/UI-38` и `/tasks/UI-38/case`: очередь читается из ключа задачи, а не
  // спрашивается у бэкенда отдельным запросом.
  const inside = /^\/tasks\/([^/]+)(\/case)?$/.exec(pathname);
  if (inside?.[1] !== undefined) {
    const taskKey = decodeURIComponent(inside[1]);
    return {
      section: inside[2] === undefined ? 'task' : 'case',
      queue: queueOfKey(taskKey),
      taskKey,
    };
  }

  return { section: 'other', queue: null, taskKey: null };
}
