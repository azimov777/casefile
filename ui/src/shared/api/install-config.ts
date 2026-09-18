import { getInstallToken, isHeaderSafe, setInstallToken } from './token';

/**
 * Конфигурация, которую отдаёт сама установка: как интерфейс узнаёт ключ, не спрашивая
 * человека.
 *
 * Контракт: `GET /config.json` на своём источнике, объект с необязательными полями
 * `token` и `login`. Отсутствие файла, пустой объект и неразборчивый ответ — один и тот
 * же нормальный случай «ключа от установки нет», а не ошибка на экране: тот же образ
 * поднимают там, где людей несколько, и там ключ у каждого свой (`UI-73`).
 *
 * `login: "password"` — установка закрыта паролем владельца (`TRK-90`, бэкенд
 * `docs/CONCEPT.md`, 5.4). Без входа она отвечает `401` с этим полем и без ключа, после
 * входа — `200` с ключом и тем же полем. По нему экран входа спрашивает пароль, а не
 * токен, и выход появляется там, где ключ пришёл от установки.
 *
 * Кто кладёт файл рядом со статикой — дело контура (`UI-75`), не приложения.
 */
const CONFIG_URL = '/config.json';

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

/** Закрыта ли установка паролем владельца: так сказал последний разборчивый ответ. */
let locked = false;

/** Что сказала установка: ключ (или `null`) и закрыта ли она паролем. */
interface InstallAnswer {
  token: string | null;
  /** `null` — ответ неразборчив или не дошёл: о замке он ничего не сказал. */
  locked: boolean | null;
}

/** Ключ, ради которого конфигурацию уже перечитывали после `401`. */
let rereadFor: string | null = null;
let reread: Promise<string | null> | null = null;

type Listener = () => void;

const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

/**
 * Читает `/config.json` и достаёт из него ключ.
 *
 * Ни один исход не считается отказом: `404`, пустой объект, чужой формат, оборванная
 * сеть — всё это «ключа от установки нет». Показывать человеку ошибку здесь нельзя,
 * иначе установка с несколькими людьми встречала бы каждого красной плашкой.
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
     *
     * Кука сеанса входа по паролю едет с этим запросом сама: источник свой, а
     * `credentials` по умолчанию — `same-origin`.
     */
    const response = await globalThis.fetch(new URL(CONFIG_URL, window.location.href), {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    // `404` — файла нет: ключа установка не даёт и паролем не закрыта. `401`
    // разбирается наравне с `200`: это ответ закрытой установки «ключ — после входа»,
    // и тело его говорит, каким входом. Прочие отказы о замке не говорят ничего.
    if (response.status === 404) return { token: null, locked: false };
    if (!response.ok && response.status !== 401) return { token: null, locked: null };
    body = await response.json();
  } catch {
    return { token: null, locked: null };
  }

  if (typeof body !== 'object' || body === null) return { token: null, locked: null };
  const fields = body as Record<string, unknown>;
  const answer = { locked: fields.login === 'password' };
  const token: unknown = fields.token;
  if (typeof token !== 'string') return { token: null, ...answer };

  const value = token.trim();
  if (value === '') return { token: null, ...answer };
  /*
   * Ключ установки проходит ту же проверку, что и введённый руками: источник доверия
   * не отменяет того, что из испорченного значения браузер не соберёт заголовок.
   * Такой ключ — то же самое, что его отсутствие: человека встретит экран входа. Молчать
   * при этом нельзя — на локальной установке это единственный след поломки конфигурации.
   */
  if (!isHeaderSafe(value)) {
    console.warn(`${CONFIG_URL}: ключ установки не годится для заголовка и пропущен`);
    return { token: null, ...answer };
  }
  return { token: value, ...answer };
}

/**
 * Ключ из ответа установки; заодно запоминает, закрыта ли она паролем.
 *
 * Неразборчивый ответ или оборванная сеть о замке не говорят ничего, и прежнее знание
 * остаётся: иначе обрыв связи посреди работы превращал бы форму пароля в поле токена.
 */
async function askInstallation(): Promise<string | null> {
  const answer = await readConfig();
  if (answer.locked !== null && answer.locked !== locked) {
    locked = answer.locked;
    notify();
  }
  return answer.token;
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
 * Спрашивает установку заново — после входа по паролю, когда сеанс уже открыт.
 *
 * Не `loadInstallToken`: тот отвечает один раз за загрузку вкладки, а здесь ответ
 * меняется посреди неё — до входа установка ключа не давала, после отдаёт. Память о
 * перечитывании после `401` забывается: она относилась к прежнему ключу.
 */
export async function reloadInstallToken(): Promise<string | null> {
  const token = await askInstallation();
  firstRead = Promise.resolve(token);
  reread = null;
  rereadFor = null;
  setInstallToken(token);
  state = 'read';
  notify();
  return token;
}

/** Закрыта ли установка паролем владельца: вход — паролем, и выход у ключа установки есть. */
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
 * устаревшее значение. Тогда конфигурация перечитывается — **ровно один раз** на такой
 * ключ. Параллельные отказы ждут одного обещания и получают один ответ; тот же ключ
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
  { password = false }: { password?: boolean } = {},
): void {
  firstRead = Promise.resolve(token);
  locked = password;
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
