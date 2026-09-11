import { useCallback, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { requestedIsVague, requestedTaskCount, subscribeDeferred } from './deferred';
import { readTable } from './table-reads';

export interface DeferredList {
  /**
   * Сколько задач изменилось с начала последнего чтения таблицы — кто бы его ни
   * вызвал: приход на экран, смена отбора или нажатие «Показать» (UI-95).
   */
  count: number;
  /** Известно только то, что таблица устарела: так приходит переподключение. */
  vague: boolean;
  /**
   * Показать накопленное: перечитать таблицу по просьбе человека. Это единственный путь,
   * которым срез живого потока трогает таблицу, — по кадру он её не перечитывает никогда.
   */
  show: () => void;
}

/**
 * Накопленные изменения таблицы и способ их показать.
 *
 * Доски это не касается вовсе: она перечитывается сама, окном склейки (UI-72), и
 * копить ей нечего.
 *
 * Снимает накопленное не нажатие, а чтение таблицы (`table-reads.ts`): таблица
 * перечитывается и мимо полосы, и полоса над только что прочитанными строками врала бы
 * про состояние экрана.
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

  const show = useCallback(() => readTable(queryClient), [queryClient]);

  return { count, vague, show };
}
