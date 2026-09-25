import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { tokenKeys } from '@/entities/token';
import { useOnceKey } from '@/shared/lib';
import {
  issueToken,
  participantKeys,
  registerAgent,
  revokeToken,
  type AgentInput,
  type IssueInput,
  type IssuedToken,
  type Participant,
} from '../api/access';

type Input<TInput> = Omit<TInput, 'idempotencyKey'>;

/**
 * Заводит агента-участника: обычная мутация, потому что в её ответе нет секрета —
 * токен участнику выпускается отдельным действием.
 */
export function useRegisterAgent() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<AgentInput>>();

  return useMutation({
    mutationFn: (input: Input<AgentInput>): Promise<Participant> =>
      registerAgent({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: () => {
      once.forget();
      // Новый участник обязан появиться в выборе формы выпуска — сейчас, а не после
      // перезагрузки вкладки.
      void queryClient.invalidateQueries({ queryKey: participantKeys.all });
    },
  });
}

/** Что знает экран о выпуске: идёт ли он и чем кончилась последняя попытка. */
export interface Issuing {
  pending: boolean;
  error: unknown;
  /** Выпускает токен. Отдаёт секрет вызывающему и `null`, если отказано. */
  submit: (input: Input<IssueInput>) => Promise<IssuedToken | null>;
  /** Забыть отказ: форму открыли заново. */
  reset: () => void;
}

/**
 * Выпускает токен — **мимо кэша запросов**.
 *
 * `useMutation` здесь не годится: ответ мутации ложится в `MutationCache`
 * (`state.data`) и переживает закрытие окна секрета вместе с самим секретом. Поэтому
 * состояние отправки держится здесь, а секрет уезжает вызывающему и живёт в состоянии
 * экрана ровно до закрытия окна (`UI-106#18`).
 *
 * Ключ повтора приходит из `useOnceKey`: повторная отправка того же выпуска идёт с тем
 * же ключом и второго токена не заводит.
 */
export function useIssueToken(): Issuing {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<IssueInput>>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  return {
    pending,
    error,
    reset: () => setError(null),

    async submit(input) {
      setPending(true);
      setError(null);
      try {
        const issued = await issueToken({ ...input, idempotencyKey: once.keyFor(input) });
        once.forget();
        // В списке появилась строка — без секрета: его в списке нет и быть не может.
        void queryClient.invalidateQueries({ queryKey: tokenKeys.all });
        return issued;
      } catch (cause) {
        setError(cause);
        return null;
      } finally {
        setPending(false);
      }
    },
  };
}

/**
 * Отзывает токен. Ключа повтора у отзыва нет намеренно: он идемпотентен сам —
 * повторный отзыв ничего не меняет и ошибкой не считается (`app/services/tokens.py`).
 */
export function useRevokeToken() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (tokenId: string): Promise<void> => revokeToken(tokenId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tokenKeys.all });
    },
  });
}
