import { createContext, useContext } from 'react';

/**
 * Узел в низу области содержания, куда полоса обновлений кладёт себя порталом. Ставит
 * его `FloatDock` (`ui/float-dock.tsx`), читает `UpdatesBar`.
 *
 * `null` — низа ещё нет (он встаёт в разметку в первой же отрисовке оболочки) или нет
 * вовсе: страница, нарисованная вне оболочки, полосы не покажет — стоять ей негде.
 */
export const BarSlot = createContext<HTMLElement | null>(null);

/** Место полосы обновлений в низу области содержания; `null`, пока его нет. */
export function useBarSlot(): HTMLElement | null {
  return useContext(BarSlot);
}
