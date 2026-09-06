/**
 * Токен участника: единственное место, где он хранится и откуда его берут.
 *
 * В адрес страницы токен не попадает никогда — только `localStorage` и заголовок
 * `Authorization`. Значение продублировано в памяти, чтобы `getToken` годился
 * снимком для `useSyncExternalStore`: снимок обязан быть стабильным между
 * отрисовками, а чтение хранилища таким не является.
 */
const STORAGE_KEY = 'tracker.token';

/**
 * Годится ли значение для заголовка `Authorization`.
 *
 * Проверяется ровно одно и только одно: сможет ли браузер собрать из него заголовок.
 * Ни префикса `trk_`, ни длины, ни набора символов, ни контрольной суммы — годен ли
 * токен по существу, решает только сервер. `trk_` остаётся подсказкой в поле ввода,
 * а не проверкой.
 *
 * Правило названо явно, а не сведено к попытке собрать `Headers`, потому что среды
 * расходятся: `undici` в Node пропускает управляющий символ `\u0001`, а Chrome его
 * отвергает. Проверка, которая ведёт себя по-разному в тесте и в браузере, хуже, чем
 * её отсутствие. Попытка собрать заголовок стоит следом — как страховка на случай,
 * если среда запрещает что-то ещё.
 */
export function isHeaderSafe(value: string): boolean {
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0;
    // Вне latin-1 значение не превращается в `ByteString` — заголовка не будет.
    if (code > 0xff) return false;
    // Управляющие символы и `DEL` в значении заголовка недопустимы; табуляция можно.
    if ((code < 0x20 && code !== 0x09) || code === 0x7f) return false;
  }

  try {
    new Headers({ Authorization: `Bearer ${value}` });
    return true;
  } catch {
    return false;
  }
}

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

/**
 * Значение заголовка `Authorization` из токена — единственный способ его туда положить.
 *
 * Одно место на все три пути: вход, восстановление сеанса из хранилища и открытие
 * живого потока. Собирать заголовок строкой мимо этой функции нельзя — тогда проверка
 * появится в трёх копиях, и однажды они разойдутся.
 */
export function authorizationHeader(token: string): string | null {
  return isHeaderSafe(token) ? `Bearer ${token}` : null;
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
