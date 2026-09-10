import { useSyncExternalStore } from 'react';
import { getInstallToken, subscribeToken } from '@/shared/api';

/**
 * Работает ли вкладка ключом, который отдала сама установка.
 *
 * Этим отличают локальную установку на одного человека от установки, где людей
 * несколько: в первой человек ключа не вводил, и выходить ему некуда — кнопка выхода
 * вернула бы его на тот же экран через секунду.
 */
export function useInstallKey(): boolean {
  return useSyncExternalStore(
    subscribeToken,
    () => getInstallToken() !== null,
    () => false,
  );
}
