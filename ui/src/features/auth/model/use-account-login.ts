import { useMutation } from '@tanstack/react-query';
import { resetSessionExpiry } from '@/entities/session';
import { adoptSessionToken, apiClient, unwrap, type components } from '@/shared/api';

type Session = components['schemas']['SessionRead'];

export interface Credentials {
  email: string;
  password: string;
}

/**
 * Вход учётной записью — почтой и паролем (`TRK-113`, режим входа).
 *
 * `POST /api/v1/session` отвечает токеном сеанса, и вкладка сразу работает им
 * (`adoptSessionToken`): он живёт в памяти вкладки, а после перезагрузки его снова
 * отдаёт кука `HttpOnly`, которую поставил тот же ответ. Ни пароль, ни токен в
 * `localStorage` не оседают.
 *
 * `gcTime: 0`: мутация держит присланное в `state.variables`, то есть пароль. Форма
 * уходит с экрана сразу после входа, и запись мутации исчезает вместе с ней, а не
 * живёт в памяти ещё пять минут по умолчанию.
 */
export function useAccountLogin() {
  return useMutation<Session, Error, Credentials>({
    mutationFn: ({ email, password }) =>
      unwrap(apiClient.POST('/api/v1/session', { body: { email: email.trim(), password } })),
    gcTime: 0,
    onSuccess: (session) => {
      adoptSessionToken(session.token);
      resetSessionExpiry();
    },
  });
}
