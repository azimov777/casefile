import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { resetSessionExpiry } from '@/entities/session';
import { apiClient, clearToken, installLocked, unwrapEmpty } from '@/shared/api';

/**
 * Выход: токен из хранилища и весь серверный кэш. Кэш чистится обязательно —
 * иначе следующий вошедший увидит чужие задачи до первого ответа сервера.
 *
 * На установке, закрытой паролем, сначала закрывается сеанс на сервере
 * (`DELETE /api/v1/session`): иначе живая кука отдала бы ключ снова при первой же
 * перезагрузке, и «выйти» ничего бы не значило. Не дошёл выход до сервера — вкладка
 * всё равно забывает ключ, а в журнал браузера уходит предупреждение: молчать о
 * живом сеансе нельзя, а держать человека внутри из-за обрыва связи — незачем.
 */
export function useLogout(): () => void {
  const queryClient = useQueryClient();

  return useCallback(() => {
    const forget = () => {
      clearToken();
      resetSessionExpiry();
      queryClient.clear();
    };
    if (!installLocked()) {
      forget();
      return;
    }
    void unwrapEmpty(apiClient.DELETE('/api/v1/session'))
      .catch((error: unknown) => {
        console.warn('Выход не дошёл до сервера: сеанс в этом браузере ещё жив', error);
      })
      .finally(forget);
  }, [queryClient]);
}
