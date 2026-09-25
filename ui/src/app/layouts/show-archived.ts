import { useCallback, useSyncExternalStore } from 'react';

/*
 * Показывать ли в панели архивные проекты (`UI-176`). Выбор — удобство этого браузера,
 * а не состояние экрана, и потому живёт в `localStorage`, а не в адресе:
 *
 * - панель стоит на каждом экране, а адрес принадлежит экрану — параметр пришлось бы
 *   тащить через каждый переход и каждую ссылку;
 * - у списка задач в адресе уже есть `archive=shown` — архив *задач* (UI-97), совсем
 *   другое правило; второй «архив» в том же адресе их путал бы.
 *
 * Панелей на странице бывает две (колонка на столе и шторка на телефоне), и обе обязаны
 * показывать одно и то же: выбор — внешнее хранилище с подпиской, а не `useState`
 * каждой. Хранилище недоступно (частный режим) — выбор живёт до перезагрузки.
 */

const STORAGE_KEY = 'tracker.side.archived';
const SHOWN = 'shown';

const listeners = new Set<() => void>();
let fallback = false;

function read(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === SHOWN;
  } catch {
    return fallback;
  }
}

function write(shown: boolean): void {
  fallback = shown;
  try {
    if (shown) window.localStorage.setItem(STORAGE_KEY, SHOWN);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Хранилище закрыто — остаётся `fallback`.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useShowArchived(): [boolean, (shown: boolean) => void] {
  const shown = useSyncExternalStore(subscribe, read, () => false);
  const set = useCallback((next: boolean) => write(next), []);
  return [shown, set];
}
