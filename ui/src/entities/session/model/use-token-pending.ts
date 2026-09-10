import { useSyncExternalStore } from 'react';
import { installConfigState, subscribeInstallConfig } from '@/shared/api';

/**
 * Выясняется ли ещё ключ: установку про него уже спросили, но ответа нет.
 *
 * «Ключа нет» и «ещё не спросили» — разные состояния, и путать их нельзя: по первому
 * человека уводят на вход, по второму ждут. Слив их в одно, локальный человек получал
 * бы вспышку экрана входа при каждой загрузке — ровно на то время, пока идёт запрос
 * конфигурации.
 */
export function useTokenPending(): boolean {
  return useSyncExternalStore(
    subscribeInstallConfig,
    () => installConfigState() !== 'read',
    () => true,
  );
}
