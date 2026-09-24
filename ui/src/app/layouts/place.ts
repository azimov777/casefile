import { projectOfKey } from '@/shared/lib';

/** Раздел, в котором человек находится. Совпадает с таблицей экранов `CONCEPT.md`, 3. */
export type Section =
  'tasks' | 'task' | 'case' | 'questions' | 'connect' | 'access' | 'people' | 'account' | 'other';

export interface Place {
  section: Section;
  /**
   * Проект, в котором человек работает: на списке — из отбора, внутри задачи —
   * из её ключа. `null` — проект не выбран (все задачи) или к месту не относится.
   */
  project: string | null;
  /** Ключ задачи, если человек внутри неё. */
  taskKey: string | null;
}

/**
 * Где человек находится — по адресу и только по нему.
 *
 * Оболочке это нужно дважды: подсветить проект и раздел в боковой панели и назвать
 * место в верхней полосе. Считается в одном месте, потому что иначе панель и полоса
 * однажды разойдутся в том, что считать текущим, — и человек увидит подсвеченным одно,
 * а прочитает другое.
 */
export function readPlace(pathname: string, params: URLSearchParams): Place {
  if (pathname === '/questions') {
    return { section: 'questions', project: null, taskKey: null };
  }

  if (pathname === '/connect') {
    return { section: 'connect', project: null, taskKey: null };
  }

  if (pathname === '/access') {
    return { section: 'access', project: null, taskKey: null };
  }

  if (pathname === '/people') {
    return { section: 'people', project: null, taskKey: null };
  }

  if (pathname === '/account') {
    return { section: 'account', project: null, taskKey: null };
  }

  if (pathname === '/tasks') {
    const project = params.get('project') ?? '';
    return { section: 'tasks', project: project === '' ? null : project, taskKey: null };
  }

  // `/tasks/UI-38` и `/tasks/UI-38/case`: проект читается из ключа задачи, а не
  // спрашивается у бэкенда отдельным запросом.
  const inside = /^\/tasks\/([^/]+)(\/case)?$/.exec(pathname);
  if (inside?.[1] !== undefined) {
    const taskKey = decodeURIComponent(inside[1]);
    return {
      section: inside[2] === undefined ? 'task' : 'case',
      project: projectOfKey(taskKey),
      taskKey,
    };
  }

  return { section: 'other', project: null, taskKey: null };
}
