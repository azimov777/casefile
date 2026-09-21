import { useSyncExternalStore } from 'react';
import { installLocked, subscribeInstallConfig } from '@/shared/api';

/**
 * Закрыта ли установка паролем владельца (`TRK-90`).
 *
 * Тогда экран входа спрашивает пароль, а не токен, и у ключа, который отдала установка,
 * появляется выход: человек его не вводил, но получил его за паролем, и выйти — значит
 * закрыть сеанс, а не забыть ключ до следующей загрузки.
 */
export function useInstallLocked(): boolean {
  return useSyncExternalStore(subscribeInstallConfig, installLocked, () => false);
}
