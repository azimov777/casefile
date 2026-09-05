import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { resetSessionExpiry } from '@/entities/session';
import { clearToken } from '@/shared/api';

/**
 * Выход: токен из хранилища и весь серверный кэш. Кэш чистится обязательно —
 * иначе следующий вошедший увидит чужие задачи до первого ответа сервера.
 */
export function useLogout(): () => void {
  const queryClient = useQueryClient();

  return useCallback(() => {
    clearToken();
    resetSessionExpiry();
    queryClient.clear();
  }, [queryClient]);
}
