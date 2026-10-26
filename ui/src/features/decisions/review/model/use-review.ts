import { useMutation, useQueryClient } from '@tanstack/react-query';
import { areaKeys } from '@/entities/area';
import { decisionKeys, projectOfDecision, type DecisionPlace } from '@/entities/decision';
import { projectKeys } from '@/entities/project';
import { sessionKeys } from '@/entities/session';
import { useOnceKey } from '@/shared/lib';
import { reviewDecision, reviseDecision, type ReviewInput, type ReviseInput } from '../api/review';

type Input<TInput> = Omit<TInput, 'idempotencyKey'>;

/**
 * После проверки перечитывается всё, что говорит о решениях: списки, карточка проекта и
 * область решения (число «Не подтверждено», дело), первый кадр (число во Входящей). Что
 * изменилось и как, решает бэкенд, а не интерфейс (TRK#244).
 */
function useRefreshDecisions() {
  const queryClient = useQueryClient();
  return (place: DecisionPlace) => {
    const keys = [
      decisionKeys.all,
      projectKeys.detail(projectOfDecision(place)),
      sessionKeys.bootstrap,
      ...(place.owner.kind === 'area' ? [areaKeys.detail(place.owner.key)] : []),
    ];
    for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
  };
}

/** Подтвердить, отклонить или удалить решение. Повтор той же попытки — с тем же ключом. */
export function useReviewDecision() {
  const refresh = useRefreshDecisions();
  const once = useOnceKey<Input<ReviewInput>>();

  return useMutation({
    mutationFn: (input: Input<ReviewInput>) =>
      reviewDecision({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_entry, { place }) => {
      once.forget();
      refresh(place);
    },
  });
}

/** Исправить решение: новое с `supersedes` прежнего. */
export function useReviseDecision() {
  const refresh = useRefreshDecisions();
  const once = useOnceKey<Input<ReviseInput>>();

  return useMutation({
    mutationFn: (input: Input<ReviseInput>) =>
      reviseDecision({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_entry, { place }) => {
      once.forget();
      refresh(place);
    },
  });
}
