import { useEffect, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { markSessionExpired } from '@/entities/session';
import { onSessionExpired } from '@/shared/api';

/**
 * Мост между клиентом API и приложением: `401` на любом запросе означает, что
 * сохранённый токен больше не годится. Токен к этому моменту уже сброшен
 * перехватчиком — здесь снимается кэш (чужие данные не должны пережить сеанс)
 * и поднимается признак, которым экран входа объяснит человеку, что произошло.
 */
export function SessionWatcher({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  useEffect(
    () =>
      onSessionExpired(() => {
        markSessionExpired();
        queryClient.clear();
      }),
    [queryClient],
  );

  return children;
}
