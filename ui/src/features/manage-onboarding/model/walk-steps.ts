import { HINT_KEYS, type HintKey } from './hint-keys';

/** Имя параметра адреса, в котором держится номер шага прохода: `/questions?walk=6` (TRK-364). */
export const WALK_PARAM = 'walk';

/** Что нужно шагу, чтобы он был: ничего, проект или задача проекта. */
type WalkNeed = 'none' | 'project' | 'task';

/** Проект и задача, по которым строятся адреса шагов; `null` — их нет. */
export interface WalkTarget {
  project: string | null;
  task: string | null;
}

interface WalkStepDef {
  hintKey: HintKey;
  needs: WalkNeed;
  /** Адрес экрана без параметра прохода; вызывается, только когда `needs` выполнено. */
  path: (target: { project: string; task: string }) => string;
}

/**
 * Порядок шагов прохода — единственное место в коде (TRK-364, `TRK-360#16`). Ключи —
 * те же, что у самих пояснений (`HINT_KEYS`): проход своих текстов не заводит и
 * показывает пояснения экранов по порядку. Шаг, которому нечего показать (нет проекта
 * или задачи), пропускается: `buildWalkSteps` отдаёт только те, что есть.
 */
const WALK_STEP_DEFS: readonly WalkStepDef[] = [
  {
    hintKey: HINT_KEYS.tasks,
    needs: 'project',
    path: ({ project }) => `/tasks?project=${project}`,
  },
  {
    hintKey: HINT_KEYS.board,
    needs: 'project',
    path: ({ project }) => `/tasks?project=${project}&view=board`,
  },
  { hintKey: HINT_KEYS.task, needs: 'task', path: ({ task }) => `/tasks/${task}` },
  { hintKey: HINT_KEYS.case, needs: 'task', path: ({ task }) => `/tasks/${task}/case` },
  { hintKey: HINT_KEYS.project, needs: 'project', path: ({ project }) => `/projects/${project}` },
  { hintKey: HINT_KEYS.questions, needs: 'none', path: () => '/questions' },
  { hintKey: HINT_KEYS.connect, needs: 'none', path: () => '/connect' },
  { hintKey: HINT_KEYS.access, needs: 'none', path: () => '/access' },
];

/** Один шаг прохода, каким он получился для этой установки. */
export interface WalkStep {
  hintKey: HintKey;
  /** Адрес экрана без параметра прохода. */
  path: string;
}

/**
 * Шаги прохода для этой установки по порядку. Номер шага — место в этом списке, с 1:
 * при всех восьми это номер строки таблицы задания, а пропущенные шаги счётчик не
 * считает («Шаг N из total» называет оставшееся число).
 */
export function buildWalkSteps({ project, task }: WalkTarget): WalkStep[] {
  const steps: WalkStep[] = [];
  for (const def of WALK_STEP_DEFS) {
    if (def.needs === 'project' && project === null) continue;
    if (def.needs === 'task' && (project === null || task === null)) continue;
    steps.push({
      hintKey: def.hintKey,
      path: def.path({
        project: encodeURIComponent(project ?? ''),
        task: encodeURIComponent(task ?? ''),
      }),
    });
  }
  return steps;
}

/** Адрес шага вместе с его номером в параметре `walk`. */
export function walkHref(step: WalkStep, n: number): string {
  return `${step.path}${step.path.includes('?') ? '&' : '?'}${WALK_PARAM}=${n}`;
}

/** Номер шага из значения параметра: целое от 1 до `total`, иначе `null`. */
export function parseWalk(value: string | null, total: number): number | null {
  if (value === null || !/^[1-9]\d{0,2}$/.test(value)) return null;
  const n = Number(value);
  return n <= total ? n : null;
}
