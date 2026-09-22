import { HttpResponse, http } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { API, CONFIG, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import {
  adoptSessionToken,
  installLocked,
  loadInstallToken,
  refreshInstallToken,
} from './install-config';
import { getInstallToken, getToken, setToken } from './token';

const INSTALL = 'trk_from_the_installation';

/** Сколько раз спрашивали конфигурацию: перечитывание считается именно так. */
let asked = 0;

beforeEach(() => {
  asked = 0;
});

/** Установка отдаёт эти тела по очереди; последнее повторяется. */
function answers(...bodies: (Record<string, unknown> | null)[]) {
  server.use(
    http.get(CONFIG, () => {
      const body = bodies[Math.min(asked, bodies.length - 1)] ?? null;
      asked += 1;
      if (body === null) return new HttpResponse(null, { status: 404 });
      return HttpResponse.json(body);
    }),
  );
}

describe('ключ от установки', () => {
  it('берётся из поля `token` и становится действующим', async () => {
    answers({ token: INSTALL });

    expect(await loadInstallToken()).toBe(INSTALL);
    expect(getInstallToken()).toBe(INSTALL);
    expect(getToken()).toBe(INSTALL);
  });

  it('в хранилище браузера не попадает: он переживает только вкладку', async () => {
    answers({ token: INSTALL });
    await loadInstallToken();

    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('старше сохранённого: вошедший однажды руками работает ключом установки', async () => {
    setToken('trk_typed_by_hand');
    answers({ token: INSTALL });
    await loadInstallToken();

    expect(getToken()).toBe(INSTALL);
    // Сохранённое при этом не стёрто: это запасной путь, и он ждёт своего случая.
    expect(window.localStorage.getItem('tracker.token')).toBe('trk_typed_by_hand');
  });

  it('спрашивается один раз за загрузку вкладки', async () => {
    answers({ token: INSTALL });

    await Promise.all([loadInstallToken(), loadInstallToken()]);
    await loadInstallToken();

    expect(asked).toBe(1);
  });
});

describe('установка ключа не дала', () => {
  it('`404` — обычный случай, а не отказ', async () => {
    answers(null);

    expect(await loadInstallToken()).toBeNull();
    expect(getToken()).toBeNull();
  });

  it('пустой объект читается так же, как отсутствие файла', async () => {
    answers({});

    expect(await loadInstallToken()).toBeNull();
  });

  it('неразборчивый ответ читается так же', async () => {
    server.use(http.get(CONFIG, () => HttpResponse.text('<html>не туда попали</html>')));

    expect(await loadInstallToken()).toBeNull();
  });

  it('нестроковое поле `token` читается так же', async () => {
    answers({ token: 42 });

    expect(await loadInstallToken()).toBeNull();
  });

  it('ключ, из которого не собрать заголовок, пропускается и назван в консоли', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    // Кириллица собирается кодами символов: в строке исходника её легко принять
    // за латиницу, набранную по ошибке.
    answers({ token: `trk_${String.fromCharCode(1087, 1088, 1080)}` });

    expect(await loadInstallToken()).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('оборванная сеть читается так же: экран входа, а не красная плашка', async () => {
    server.use(http.get(CONFIG, () => HttpResponse.error()));

    expect(await loadInstallToken()).toBeNull();
  });
});

describe('перечитывание после `401`', () => {
  it('отдаёт новый ключ, когда установка выпустила его заново', async () => {
    answers({ token: INSTALL }, { token: 'trk_reissued' });
    await loadInstallToken();

    expect(await refreshInstallToken(INSTALL)).toBe('trk_reissued');
    expect(getToken()).toBe('trk_reissued');
  });

  it('идёт ровно один раз на устаревший ключ, сколько бы отказов ни пришло', async () => {
    answers({ token: INSTALL });
    await loadInstallToken();

    const [first, second] = await Promise.all([
      refreshInstallToken(INSTALL),
      refreshInstallToken(INSTALL),
    ]);
    const third = await refreshInstallToken(INSTALL);

    // Установка отдаёт то же самое — повторять нечем, дальше экран входа.
    expect([first, second, third]).toEqual([null, null, null]);
    // Первое чтение плюс одно перечитывание.
    expect(asked).toBe(2);
  });

  it('ключ, введённый человеком, не перечитывается вовсе', async () => {
    setToken('trk_typed_by_hand');
    answers(null);
    await loadInstallToken();

    expect(await refreshInstallToken('trk_typed_by_hand')).toBeNull();
    // Спрашивали только первый раз: отказ по введённому токену — истёкший сеанс.
    expect(asked).toBe(1);
  });

  it('опоздавший отказ по уже сменённому ключу получает действующий без похода в сеть', async () => {
    answers({ token: INSTALL }, { token: 'trk_reissued' });
    await loadInstallToken();
    await refreshInstallToken(INSTALL);
    const beforeLate = asked;

    expect(await refreshInstallToken(INSTALL)).toBe('trk_reissued');
    expect(asked).toBe(beforeLate);
  });
});

describe('режим входа по учётным записям', () => {
  const SESSION = 'trk_session_of_this_browser';
  /** Сколько раз спрашивали сеанс по куке. */
  let sessionAsked = 0;

  /**
   * Отвечает, как образ интерфейса в режиме входа и API за ним: `/config.json` всегда
   * `401 {"login":"password"}` и ключа не даёт никому, а `GET /api/v1/session` отдаёт
   * токен, пока сеанс жив. Кука здесь — флаг подмены: `HttpOnly` скрипту не видна, и
   * интерфейс о ней не знает ничего; саму куку проверяет `e2e/account-login.spec.ts`.
   */
  function signInMode(session: { open: boolean }) {
    sessionAsked = 0;
    server.use(
      http.get(CONFIG, () => {
        asked += 1;
        return HttpResponse.json({ login: 'password' }, { status: 401 });
      }),
      http.get(`${API}/api/v1/session`, () => {
        sessionAsked += 1;
        return session.open
          ? HttpResponse.json({
              data: {
                token: SESSION,
                expires_at: '2026-09-25T12:00:00Z',
                account: { email: 'alice@example.com' },
              },
            })
          : failure('unauthorized', 401, 'No session', { reason: 'missing_session' });
      }),
    );
  }

  it('без сеанса ключа нет, режим входа виден, и это не ошибка', async () => {
    signInMode({ open: false });

    expect(await loadInstallToken()).toBeNull();
    expect(installLocked()).toBe(true);
    expect(getToken()).toBeNull();
    expect(sessionAsked).toBe(1);
  });

  it('живой сеанс на загрузке вкладки — ключ из `GET /api/v1/session`, и только в памяти', async () => {
    signInMode({ open: true });

    expect(await loadInstallToken()).toBe(SESSION);
    expect(getInstallToken()).toBe(SESSION);
    expect(installLocked()).toBe(true);
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('ключ из ответа входа принимается без похода в сеть', async () => {
    signInMode({ open: false });
    await loadInstallToken();
    const before = { config: asked, session: sessionAsked };

    adoptSessionToken(SESSION);

    expect(getToken()).toBe(SESSION);
    expect(getInstallToken()).toBe(SESSION);
    expect({ config: asked, session: sessionAsked }).toEqual(before);
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('`200` с полем `token` в режиме входа ключом не считается', async () => {
    server.use(
      http.get(CONFIG, () => HttpResponse.json({ token: INSTALL, login: 'password' })),
      http.get(`${API}/api/v1/session`, () =>
        failure('unauthorized', 401, 'No session', { reason: 'missing_session' }),
      ),
    );

    expect(await loadInstallToken()).toBeNull();
    expect(installLocked()).toBe(true);
  });

  it('сеанс кончился посреди работы — переспрашивание после `401` ведёт на вход', async () => {
    const session = { open: true };
    signInMode(session);
    await loadInstallToken();

    session.open = false;

    expect(await refreshInstallToken(SESSION)).toBeNull();
    expect(installLocked()).toBe(true);
  });

  it('`404` у установки без режима входа его не ставит и сеанс не спрашивает', async () => {
    signInMode({ open: true });
    answers(null);

    await loadInstallToken();

    expect(installLocked()).toBe(false);
    expect(sessionAsked).toBe(0);
  });

  it('оборванная сеть о режиме не говорит ничего: прежнее знание остаётся', async () => {
    signInMode({ open: true });
    await loadInstallToken();
    server.use(http.get(CONFIG, () => HttpResponse.error()));

    expect(await refreshInstallToken(SESSION)).toBeNull();
    expect(installLocked()).toBe(true);
  });
});
