import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { accountKeys } from '@/entities/account';
import {
  createAccount,
  resetPassword,
  setDisabled,
  type AccountWithPassword,
  type CreateInput,
} from '../api/people';

/** Что знает окно о действии с паролем в ответе: идёт ли оно и чем кончилось. */
export interface PasswordAction<TInput> {
  pending: boolean;
  error: unknown;
  /** Отдаёт ответ с паролем вызывающему и `null`, если отказано. */
  submit: (input: TInput) => Promise<AccountWithPassword | null>;
}

/**
 * Действие, в ответе которого бывает пароль, — **мимо кэша запросов**.
 *
 * `useMutation` здесь не годится: ответ мутации ложится в `MutationCache`
 * (`state.data`) и переживает закрытие окна вместе с паролем. Поэтому состояние
 * отправки держится здесь, а ответ уезжает вызывающему и живёт в состоянии экрана ровно
 * до закрытия окна — так же, как секрет токена (`features/manage-access`, `UI-106#18`).
 */
function usePasswordAction<TInput>(
  send: (input: TInput) => Promise<AccountWithPassword>,
): PasswordAction<TInput> {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  return {
    pending,
    error,
    async submit(input) {
      setPending(true);
      setError(null);
      try {
        const answer = await send(input);
        // Список перечитывается без пароля: там его нет и быть не может.
        void queryClient.invalidateQueries({ queryKey: accountKeys.all });
        return answer;
      } catch (cause) {
        setError(cause);
        return null;
      } finally {
        setPending(false);
      }
    },
  };
}

/** Заводит учётную запись; сгенерированный пароль приходит один раз. */
export function useCreateAccount(): PasswordAction<CreateInput> {
  return usePasswordAction(createAccount);
}

/** Сбрасывает пароль учётной записи; сгенерированный пароль приходит один раз. */
export function useResetPassword(): PasswordAction<{
  accountId: string;
  password: string | null;
}> {
  return usePasswordAction(({ accountId, password }) => resetPassword(accountId, password));
}

/** Отключает или включает учётную запись. Пароля в ответе нет — обычная мутация. */
export function useSetDisabled() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ accountId, disabled }: { accountId: string; disabled: boolean }) =>
      setDisabled(accountId, disabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: accountKeys.all });
    },
  });
}
