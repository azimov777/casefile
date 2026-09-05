import { useSyncExternalStore } from 'react';
import { getToken, subscribeToken } from '@/shared/api';

/**
 * Токен текущего сеанса как состояние React.
 *
 * `useSyncExternalStore`, а не `useState` с копией: токен живёт вне React —
 * его сбрасывает перехватчик `401` и меняет соседняя вкладка. Подписка на источник
 * избавляет от рассинхронизации между хранилищем и отрисованным экраном.
 */
export function useSessionToken(): string | null {
  return useSyncExternalStore(subscribeToken, getToken, () => null);
}
