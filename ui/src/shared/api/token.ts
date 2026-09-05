/**
 * Токен участника: единственное место, где он хранится и откуда его берут.
 *
 * В адрес страницы токен не попадает никогда — только `localStorage` и заголовок
 * `Authorization`. Значение продублировано в памяти, чтобы `getToken` годился
 * снимком для `useSyncExternalStore`: снимок обязан быть стабильным между
 * отрисовками, а чтение хранилища таким не является.
 */
const STORAGE_KEY = 'tracker.token';

type Listener = () => void;

const listeners = new Set<Listener>();

function readStorage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Приватный режим и запрет на хранилище: приложение работает, но забудет токен.
    return null;
  }
}

let cached: string | null = readStorage();

function notify(): void {
  for (const listener of listeners) listener();
}

/** Токен для заголовка или `null`, если человек не входил. */
export function getToken(): string | null {
  return cached;
}

export function setToken(value: string): void {
  cached = value;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // См. readStorage: без хранилища токен живёт до перезагрузки вкладки.
  }
  notify();
}

export function clearToken(): void {
  cached = null;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // См. readStorage.
  }
  notify();
}

/**
 * Подписка на смену токена. Слушает и соседние вкладки: вышли в одной — вышли везде.
 */
export function subscribeToken(listener: Listener): () => void {
  if (listeners.size === 0) window.addEventListener('storage', onStorageEvent);
  listeners.add(listener);

  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener('storage', onStorageEvent);
  };
}

function onStorageEvent(event: StorageEvent): void {
  if (event.key !== null && event.key !== STORAGE_KEY) return;
  const next = readStorage();
  if (next === cached) return;
  cached = next;
  notify();
}
