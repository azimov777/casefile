import { useSyncExternalStore } from 'react';
import { getSessionExpired, subscribeSessionExpiry } from './expiry';

export function useSessionExpired(): boolean {
  return useSyncExternalStore(subscribeSessionExpiry, getSessionExpired, () => false);
}
