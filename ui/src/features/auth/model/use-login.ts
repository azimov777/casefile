import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchBootstrap,
  resetSessionExpiry,
  sessionKeys,
  type Bootstrap,
} from '@/entities/session';
import { ApiError, CLIENT_ERROR_CODES, setToken } from '@/shared/api';

/**
 * Вход: токен проверяется запросом `bootstrap` и сохраняется только после удачи.
 * Неверный токен не должен оседать в хранилище — иначе следующая загрузка страницы
 * начнётся с отказа вместо экрана входа.
 *
 * Токен без участника (общий агентский) до интерфейса не допускается: весь интерфейс
 * построен вокруг участника — имя в шапке, счётчик адресованных вопросов, входящая, —
 * и без него человек увидел бы пустоту без объяснения причины.
 */
export function useLogin() {
  const queryClient = useQueryClient();

  return useMutation<Bootstrap, Error, string>({
    mutationFn: async (candidate: string) => {
      const token = candidate.trim();
      const bootstrap = await fetchBootstrap(token);

      if (bootstrap.participant === null || bootstrap.participant === undefined) {
        throw new ApiError(
          CLIENT_ERROR_CODES.participantRequired,
          'Token has no participant behind it',
          200,
          {},
        );
      }

      setToken(token);
      return bootstrap;
    },
    onSuccess: (bootstrap) => {
      resetSessionExpiry();
      // Первый кадр уже получен проверкой: класть его в кэш, а не запрашивать снова.
      queryClient.setQueryData(sessionKeys.bootstrap, bootstrap);
    },
  });
}
