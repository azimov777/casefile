import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sessionKeys } from '@/entities/session';
import { apiClient, unwrap, type components } from '@/shared/api';

export type OnboardingUpdate = components['schemas']['OnboardingUpdate'];

export interface OnboardingChange {
  accountId: string;
  update: OnboardingUpdate;
}

/**
 * Правка состояния знакомства своей учётной записи: `PATCH
 * /api/v1/accounts/{account_id}/onboarding` (`TRK-369`). Чужую запись бэкенд отклонит
 * `403 permission_denied` — экран «Начало» (`pages/start`) её и не предлагает, меняя
 * только запись за собственным токеном.
 *
 * `gcTime: 0` тем же поводом, что и у смены пароля (`features/change-password`):
 * запись о мутации не должна жить дольше самого действия.
 */
export function useUpdateOnboarding() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ accountId, update }: OnboardingChange) =>
      unwrap(
        apiClient.PATCH('/api/v1/accounts/{account_id}/onboarding', {
          params: { path: { account_id: accountId } },
          body: update,
        }),
      ),
    gcTime: 0,
    onSuccess: () => {
      // Статус в `bootstrap.account.onboarding` изменился: экран «Начало» и панель
      // читают его оттуда же.
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
    },
  });
}
