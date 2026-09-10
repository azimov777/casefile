import { getInstallToken, isHeaderSafe, setInstallToken } from './token';

/**
 * Конфигурация, которую отдаёт сама установка: как интерфейс узнаёт ключ, не спрашивая
 * человека.
 *
 * Контракт: `GET /config.json` на своём источнике, объект с необязательным полем
 * `token`. Отсутствие файла, пустой объект и неразборчивый ответ — один и тот же
 * нормальный случай «ключа от установки нет», а не ошибка на экране: тот же образ
 * поднимают там, где людей несколько, и там ключ у каждого свой (`UI-73`).
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
async function readConfig(): Promise<string | null> {
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
    if (!response.ok) return null;
    body = await response.json();
  } catch {
    return null;
  }

  if (typeof body !== 'object' || body === null) return null;
  const token: unknown = (body as Record<string, unknown>).token;
  if (typeof token !== 'string') return null;

  const value = token.trim();
  if (value === '') return null;
  /*
   * Ключ установки проходит ту же проверку, что и введённый руками: источник доверия
   * не отменяет того, что из испорченного значения браузер не соберёт заголовок.
   * Такой ключ — то же самое, что его отсутствие: человека встретит экран входа. Молчать
   * при этом нельзя — на локальной установке это единственный след поломки конфигурации.
   */
  if (!isHeaderSafe(value)) {
    console.warn(`${CONFIG_URL}: ключ установки не годится для заголовка и пропущен`);
    return null;
  }
  return value;
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
    return readConfig().then((token) => {
      setInstallToken(token);
      state = 'read';
      notify();
      return token;
    });
  })();
  return firstRead;
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
    reread = readConfig().then((token) => {
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
export function seedInstallConfig(token: string | null): void {
  firstRead = Promise.resolve(token);
  setInstallToken(token);
  state = 'read';
  notify();
}

/** Забыть всё прочитанное. Только для оснастки тестов: состояние живёт в модуле. */
export function resetInstallConfig(): void {
  firstRead = null;
  reread = null;
  rereadFor = null;
  state = 'unread';
  notify();
}
