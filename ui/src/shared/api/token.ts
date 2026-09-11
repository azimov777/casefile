/**
 * Токен участника: единственное место, где он хранится и откуда его берут.
 *
 * Источников у него два. Первый — сама установка: она отдаёт ключ конфигурацией
 * на своём источнике (`install-config.ts`), и человек его не видит вовсе. Второй —
 * человек, который ввёл токен на экране входа; так работает установка, где людей
 * несколько и ключ у каждого свой.
 *
 * Ключ установки старше сохранённого: если установка ключ отдала, работают им, чем бы
 * ни кончился прошлый вход. Иначе человек, однажды вошедший руками, навсегда остался бы
 * со своим значением и не заметил бы, что установка перевыпустила ключ.
 *
 * В адрес страницы токен не попадает никогда — только `localStorage` и заголовок
 * `Authorization`. Ключ установки не попадает и в `localStorage`: он перевыпускается
 * при потере файла на хосте, и сохранённая копия пережила бы отозванный секрет —
 * человек увидел бы `401` там, где всё настроено верно.
 *
 * Действующее значение продублировано отдельным полем, чтобы `getToken` годился
 * снимком для `useSyncExternalStore`: снимок обязан быть стабильным между отрисовками,
 * а ни чтение хранилища, ни выражение поверх двух источников таким не является.
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

/** Что ввёл человек: пережило перезагрузку вкладки. */
let stored: string | null = readStorage();
/** Что отдала установка: живёт только в памяти вкладки. */
let install: string | null = null;
/** Чем подписываются запросы прямо сейчас. Поле, а не выражение: это снимок. */
let effective: string | null = stored;

function notify(): void {
  for (const listener of listeners) listener();
}

/**
 * Пересчитывает действующий ключ и будит подписчиков, только если он сменился.
 *
 * Молчание при неизменившемся значении здесь не оптимизация, а поведение: правка
 * одного источника при старшем другом ничего для запросов не меняет, и страж
 * маршрутов не должен узнавать о «смене», которой не было.
 */
function settle(): void {
  const next = install ?? stored;
  if (next === effective) return;
  effective = next;
  notify();
}

/** Токен для заголовка или `null`, если ключа нет ни от установки, ни от человека. */
export function getToken(): string | null {
  return effective;
}

/**
 * Ключ, отданный установкой, или `null`. Им отличают два пути там, где они расходятся:
 * выйти некуда, если входить было некуда, а `401` с таким ключом стоит перепроверить
 * конфигурацией, прежде чем вести человека на вход.
 */
export function getInstallToken(): string | null {
  return install;
}

/**
 * Значение заголовка `Authorization` из токена — единственный способ его туда положить.
 *
 * Одно место на все пути: вход, восстановление сеанса из хранилища, ключ от установки
 * и открытие живого потока. Собирать заголовок строкой мимо этой функции нельзя —
 * тогда проверка появится в нескольких копиях, и однажды они разойдутся.
 */
export function authorizationHeader(token: string): string | null {
  return isHeaderSafe(token) ? `Bearer ${token}` : null;
}

export function setToken(value: string): void {
  stored = value;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // См. readStorage: без хранилища токен живёт до перезагрузки вкладки.
  }
  settle();
}

/**
 * Ключ от установки. В хранилище не уезжает никогда — только в память вкладки.
 * `null` означает «установка ключа не дала»: дальше работает экран входа.
 */
export function setInstallToken(value: string | null): void {
  install = value;
  settle();
}

/** Забыть ключ обоих источников: человек вышел сам или ключ перестал годиться. */
export function clearToken(): void {
  stored = null;
  install = null;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // См. readStorage.
  }
  settle();
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
  stored = readStorage();
  settle();
}
