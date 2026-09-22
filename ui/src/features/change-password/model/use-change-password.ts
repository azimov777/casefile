import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sessionKeys } from '@/entities/session';
import { apiClient, unwrap } from '@/shared/api';

export interface PasswordChange {
  accountId: string;
  /** Пароль в силе сейчас; `null` у учётной записи без пароля — та задаёт первый. */
  current: string | null;
  next: string;
}

/**
 * Смена своего пароля: `PUT /api/v1/accounts/{id}/password`.
 *
 * Бэкенд гасит все прочие сеансы этого человека, а сеанс, из которого пароль сменили,
 * оставляет живым (`app/services/accounts.py`): вкладка работает дальше тем же ключом.
 * Чужой пароль так не сменить — `403` с `reason: not_own_account`; это делает
 * администратор сбросом.
 *
 * `gcTime: 0`: пароли лежат в `state.variables` мутации, и запись о ней не должна жить
 * дольше формы, которая её отправила.
 */
export function useChangePassword() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ accountId, current, next }: PasswordChange) =>
      unwrap(
        apiClient.PUT('/api/v1/accounts/{account_id}/password', {
          params: { path: { account_id: accountId } },
          body: { new_password: next, ...(current === null ? {} : { current_password: current }) },
        }),
      ),
    gcTime: 0,
    onSuccess: () => {
      // `has_password` в первом кадре мог смениться: учётная запись задала первый пароль.
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
    },
  });
}
