import { useCallback, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  releaseRequested,
  requestedIsVague,
  requestedTaskCount,
  subscribeDeferred,
} from './deferred';

export interface DeferredList {
  /** Сколько задач изменилось с прошлого показа. */
  count: number;
  /** Известно только то, что список устарел: так приходит переподключение. */
  vague: boolean;
  /** Показать накопленное: список перечитывается здесь и только здесь. */
  show: () => void;
}

/**
 * Накопленные изменения списка и способ их показать.
 *
 * Состояние живёт в модуле, а не в React: поток поднят в оболочке приложения, а полоса
 * рисуется страницей списка — общего предка, через который можно было бы передать это
 * пропсами, у них нет. Переход между таблицей и доской перемонтирует страницу, и
 * накопленное обязано это пережить.
 */
export function useDeferredList(): DeferredList {
  const queryClient = useQueryClient();
  // Два снимка вместо одного объекта: `useSyncExternalStore` сравнивает снимок по
  // ссылке, и собранный на лету объект давал бы бесконечную перерисовку.
  const count = useSyncExternalStore(subscribeDeferred, requestedTaskCount);
  const vague = useSyncExternalStore(subscribeDeferred, requestedIsVague);

  const show = useCallback(() => {
    for (const key of releaseRequested()) void queryClient.invalidateQueries({ queryKey: key });
  }, [queryClient]);

  return { count, vague, show };
}
