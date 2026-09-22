import { useSyncExternalStore } from 'react';
import { installLocked, subscribeInstallConfig } from '@/shared/api';

/**
 * Режим ли входа по учётным записям (`TRK-113`): `/config.json` ответил `401 {"login":"password"}`.
 *
 * Тогда экран входа спрашивает почту и пароль, а не токен; у ключа, который вкладке
 * отдал вход, появляется выход — закрыть сеанс, а не забыть ключ до следующей загрузки;
 * а в панели — своя учётная запись и, администратору, люди. На своей машине этого нет.
 */
export function useInstallLocked(): boolean {
  return useSyncExternalStore(subscribeInstallConfig, installLocked, () => false);
}
