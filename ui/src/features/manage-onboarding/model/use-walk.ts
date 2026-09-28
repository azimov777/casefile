import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { bootstrapQueryOptions } from '@/entities/session';
import { tasksQueryOptions } from '@/entities/task';
import {
  WALK_PARAM,
  WALK_PROJECT_KEY,
  buildWalkSteps,
  parseWalk,
  type WalkStep,
} from './walk-steps';

export interface WalkPlan {
  /** Проект и первая задача прочитаны: шаги известны, счётчик не соврёт. */
  ready: boolean;
  steps: WalkStep[];
}

/**
 * План прохода для этой установки (TRK-364): проект — `START`, если он есть среди
 * активных проектов `bootstrap`, иначе первый из них; задача — первая задача проекта по
 * `GET /api/v1/tasks` с `project` и `limit=1`, архив показан (правила `hideArchived`
 * нет). Отказ запроса задач значит «задач нет»: шаги 3 и 4 пропускаются.
 */
export function useWalkPlan(enabled = true): WalkPlan {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const active = (bootstrap.data?.projects ?? []).filter((item) => item.archived_at == null);
  const project = (active.find((item) => item.key === WALK_PROJECT_KEY) ?? active[0])?.key ?? null;

  const first = useQuery({
    // Без `keepPreviousData` списка: задача чужого проекта на время загрузки —
    // неверный адрес шага.
    ...tasksQueryOptions({
      project: project === null ? [] : [project],
      limit: 1,
      fields: ['status'],
    }),
    placeholderData: undefined,
    enabled: enabled && project !== null,
    retry: false,
  });
  const task = first.data?.items[0]?.key ?? null;

  return {
    ready: bootstrap.isSuccess && (project === null || !enabled || !first.isPending),
    steps: buildWalkSteps({ project, task }),
  };
}

export interface WalkState {
  /** Номер шага с 1 или `null`, когда прохода нет (параметра нет, он неверен или план не прочитан). */
  step: number | null;
  steps: WalkStep[];
}

/** Состояние прохода по адресу: номер шага держится параметром `walk` (TRK-364). */
export function useWalk(): WalkState {
  const [searchParams] = useSearchParams();
  const raw = searchParams.get(WALK_PARAM);
  // Запрос задачи идёт только когда параметр есть: обычному экрану он не нужен.
  const plan = useWalkPlan(raw !== null);
  return {
    step: plan.ready ? parseWalk(raw, plan.steps.length) : null,
    steps: plan.steps,
  };
}
