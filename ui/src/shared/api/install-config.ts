import { apiBaseUrl } from './base-url';
import type { components } from './openapi';
import { getInstallToken, isHeaderSafe, setInstallToken } from './token';

/**
 * Ключ, который вкладке отдаёт сама установка, не спрашивая человека ни о чём, — и как
 * она его отдаёт.
 *
 * Контракт: `GET /config.json` на своём источнике (`../docs/FRONTEND.md`, «Вход учётной
 * записью»). Ответов три:
 *
 * - `200 {"token"}` — своя машина: ключ администратора `owner@localhost`, без входа;
 * - `401 {"login": "password"}` — режим входа по учётным записям (`TRK-113`): общего
 *   ключа нет никому, и свой ключ вкладка берёт у сеанса — `GET /api/v1/session` по куке
 *   `HttpOnly`, которую поставил вход; сеанса нет — экран входа спрашивает почту и пароль;
 * - `404`, пустой объект, неразборчивый ответ — «ключа от установки нет»: вход токеном,
 *   а не ошибка на экране (`UI-73`).
 *
 * Токен сеанса в режиме входа — тоже «ключ от установки»: человек его не вводил, живёт он
 * в памяти вкладки, а после перезагрузки его снова отдаёт кука. В `localStorage` он не
 * попадает: там он пережил бы выход, сделанный в соседней вкладке.
 *
 * Кто кладёт файл рядом со статикой — дело контура (`UI-75`), не приложения.
 */
const CONFIG_URL = '/config.json';

/** Сеанс браузера: ресурс API, единственный, где токен не нужен. */
const SESSION_PATH = '/api/v1/session';

type SessionRead = components['schemas']['SessionRead'];

/**
 * Спросили ли уже установку.
 *
 * Различать «ключа нет» и «ещё не спросили» обязательно: страж маршрутов уводит
 * на вход по первому и ждёт по второму. Слив их в одно, локальный человек получал бы
 * вспышку экрана входа при каждой загрузке.
 */
export type ConfigState = 'unread' | 'reading' | 'read';

let state: ConfigState = 'unread';
let firstRead: Promise<string | null> | null = null;

/** Режим ли входа по учётным записям: так сказал последний разборчивый ответ. */
let locked = false;

/** Что сказал `/config.json`: ключ (или `null`) и режим ли это входа. */
interface InstallAnswer {
  token: string | null;
  /** `null` — ответ неразборчив или не дошёл: о режиме он ничего не сказал. */
  locked: boolean | null;
}

/** Ключ, ради которого установку уже переспрашивали после `401`. */
let rereadFor: string | null = null;
let reread: Promise<string | null> | null = null;

type Listener = () => void;

const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

/**
 * Ключ, годный для заголовка, или `null`.
 *
 * Ключ установки проходит ту же проверку, что и введённый руками: источник доверия не
 * отменяет того, что из испорченного значения браузер не соберёт заголовок. Такой ключ —
 * то же самое, что его отсутствие: человека встретит экран входа. Молчать при этом нельзя
 * — на локальной установке это единственный след поломки конфигурации.
 */
function usable(token: unknown, source: string): string | null {
  if (typeof token !== 'string') return null;
  const value = token.trim();
  if (value === '') return null;
  if (!isHeaderSafe(value)) {
    console.warn(`${source}: ключ установки не годится для заголовка и пропущен`);
    return null;
  }
  return value;
}

/**
 * Читает `/config.json` и достаёт из него ключ.
 *
 * Ни один исход не считается отказом: `404`, пустой объект, чужой формат, оборванная
 * сеть — всё это «ключа от установки нет». Показывать человеку ошибку здесь нельзя,
 * иначе установка без ключа встречала бы каждого красной плашкой.
 *
 * `cache: 'no-store'` не украшение: конфигурацию перечитывают после `401`, когда контур
 * переподняли с новым ключом, — и ответ из кэша вернул бы ровно тот, который только что
 * отказал.
 */
async function readConfig(): Promise<InstallAnswer> {
  let body: unknown;
  try {
    /*
     * Адрес собирается от адреса самой страницы, а не отправляется строкой `/config.json`:
     * «свой источник» — это и есть требование контракта, а `fetch` в jsdom приезжает
     * из Node и относительных адресов не понимает вовсе. Строкой модуль был бы
     * непроверяем.
     */
    const response = await globalThis.fetch(new URL(CONFIG_URL, window.location.href), {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    // `404` — файла нет: ключа установка не даёт, и режима входа нет. `401` разбирается
    // наравне с `200`: это ответ режима входа «ключ — у сеанса», и тело его говорит,
    // каким входом. Прочие отказы о режиме не говорят ничего.
    if (response.status === 404) return { token: null, locked: false };
    if (!response.ok && response.status !== 401) return { token: null, locked: null };
    body = await response.json();
  } catch {
    return { token: null, locked: null };
  }

  if (typeof body !== 'object' || body === null) return { token: null, locked: null };
  const fields = body as Record<string, unknown>;
  // Поля `login` в `200` больше нет (`TRK-113`): режим входа ключа не отдаёт вовсе.
  const answer = { locked: fields.login === 'password' };
  return { token: answer.locked ? null : usable(fields.token, CONFIG_URL), ...answer };
}

/**
 * Токен живого сеанса этого браузера: `GET /api/v1/session` по куке.
 *
 * Голым `fetch`, мимо клиента `openapi-fetch`: его перехватчик `401` объявил бы
 * истёкшим сеанс вкладки, а здесь `401` — обычный ответ «сеанса нет» (не входили,
 * вышли, сеанс кончился или его погасил сброс пароля), и дальше работает экран входа.
 * Кука `HttpOnly` едет с запросом сама: источник свой, `credentials` по умолчанию
 * `same-origin`. Любой другой исход — тоже «ключа нет»: ошибке на экране здесь не место.
 */
async function readSession(): Promise<string | null> {
  try {
    const response = await globalThis.fetch(
      new URL(`${apiBaseUrl}${SESSION_PATH}`, window.location.href),
      { cache: 'no-store', headers: { Accept: 'application/json' } },
    );
    if (!response.ok) return null;
    const body = (await response.json()) as { data?: Partial<SessionRead> } | null;
    return usable(body?.data?.token, SESSION_PATH);
  } catch {
    return null;
  }
}

/**
 * Ключ от установки; заодно запоминает, режим ли это входа.
 *
 * Неразборчивый ответ или оборванная сеть о режиме не говорят ничего, и прежнее знание
 * остаётся: иначе обрыв связи посреди работы превращал бы форму почты в поле токена.
 */
async function askInstallation(): Promise<string | null> {
  const answer = await readConfig();
  if (answer.locked !== null && answer.locked !== locked) {
    locked = answer.locked;
    notify();
  }
  return answer.locked === true ? readSession() : answer.token;
}

/**
 * Спрашивает установку про ключ. Один раз за загрузку вкладки: повторный вызов отдаёт
 * то же обещание.
 *
 * Зовётся до первой отрисовки (`src/main.tsx`), чтобы к моменту, когда страж маршрутов
 * решает, куда вести человека, ответ уже был.
 */
export function loadInstallToken(): Promise<string | null> {
  firstRead ??= (() => {
    state = 'reading';
    notify();
    return askInstallation().then((token) => {
      setInstallToken(token);
      state = 'read';
      notify();
      return token;
    });
  })();
  return firstRead;
}

/**
 * Принимает ключ, который отдал вход (`POST /api/v1/session`, поле `data.token`).
 *
 * Ключ берётся из ответа входа, а не у установки заново: `/config.json` в режиме входа
 * ключа не отдаёт никому, а `GET /api/v1/session` отдал бы тот же токен вторым запросом.
 * Память о переспрашивании после `401` забывается: она относилась к прежнему ключу.
 */
export function adoptSessionToken(token: string): void {
  firstRead = Promise.resolve(token);
  reread = null;
  rereadFor = null;
  setInstallToken(token);
  state = 'read';
  notify();
}

/** Режим ли входа по учётным записям: вход — почтой и паролем, и у ключа есть выход. */
export function installLocked(): boolean {
  return locked;
}

/**
 * Чем повторить запрос, которому ответили `401`, или `null`, если повторять нечем.
 *
 * Отвечает `null` сразу, если отказавший ключ пришёл не от установки: токен, введённый
 * человеком, отказом и кончается — это истёкший сеанс, и дальше работает экран входа.
 *
 * Ключ от установки — другое дело: контур могли переподнять, и вкладка держит
 * устаревшее значение; в режиме входа токен сеанса мог кончиться, а кука — ещё нет.
 * Тогда установка переспрашивается — **ровно один раз** на такой ключ. Сеанс,
 * закрытый выходом, сбросом пароля или отключением учётной записи, отвечает
 * «сеанса нет», и человека ведут на вход. Параллельные отказы ждут одного обещания и получают один ответ; тот же ключ
 * в ответе считается за «повторять нечем», и человека ведут на вход, как раньше.
 *
 * Отказ с ключом, который здесь уже сменили (опоздавший ответ давнего запроса или
 * живой поток, ещё не переоткрытый), получает действующий ключ без похода в сеть.
 */
export function refreshInstallToken(used: string): Promise<string | null> {
  const install = getInstallToken();
  if (install === null) return Promise.resolve(null);
  if (install !== used) return Promise.resolve(install);

  if (rereadFor !== used || reread === null) {
    rereadFor = used;
    reread = askInstallation().then((token) => {
      setInstallToken(token);
      return token === null || token === used ? null : token;
    });
  }
  return reread;
}

/** Спросили ли уже установку про ключ. */
export function installConfigState(): ConfigState {
  return state;
}

export function subscribeInstallConfig(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Считать конфигурацию прочитанной с этим ключом, не ходя в сеть.
 *
 * Только для оснастки тестов: страничному тесту, который про ключ установки ничего
 * не проверяет, незачем ждать лишний кадр и держать обработчик `/config.json`.
 */
export function seedInstallConfig(
  token: string | null,
  { signIn = false }: { signIn?: boolean } = {},
): void {
  firstRead = Promise.resolve(token);
  locked = signIn;
  setInstallToken(token);
  state = 'read';
  notify();
}

/** Забыть всё прочитанное. Только для оснастки тестов: состояние живёт в модуле. */
export function resetInstallConfig(): void {
  firstRead = null;
  reread = null;
  rereadFor = null;
  locked = false;
  state = 'unread';
  notify();
}
