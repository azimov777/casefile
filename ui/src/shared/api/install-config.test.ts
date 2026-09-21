import { HttpResponse, http } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CONFIG } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import {
  installLocked,
  loadInstallToken,
  refreshInstallToken,
  reloadInstallToken,
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

describe('установка, закрытая паролем владельца', () => {
  /** Отвечает, как образ интерфейса в режиме пароля: без сеанса `401`, с ним — ключ. */
  function lockedInstall(session: { open: boolean }) {
    server.use(
      http.get(CONFIG, () => {
        asked += 1;
        return session.open
          ? HttpResponse.json({ token: INSTALL, login: 'password' })
          : HttpResponse.json({ login: 'password' }, { status: 401 });
      }),
    );
  }

  it('`401` с полем `login` — ключа нет, установка закрыта, и это не ошибка', async () => {
    lockedInstall({ open: false });

    expect(await loadInstallToken()).toBeNull();
    expect(installLocked()).toBe(true);
    expect(getToken()).toBeNull();
  });

  it('после входа перечитывается заново, хотя за эту загрузку уже спрашивали', async () => {
    const session = { open: false };
    lockedInstall(session);
    await loadInstallToken();

    session.open = true;

    expect(await reloadInstallToken()).toBe(INSTALL);
    expect(getInstallToken()).toBe(INSTALL);
    expect(installLocked()).toBe(true);
    expect(asked).toBe(2);
    // Ключ за паролем тоже только в памяти вкладки.
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('открытый сеанс на загрузке вкладки — ключ сразу, и замок всё равно виден', async () => {
    lockedInstall({ open: true });

    expect(await loadInstallToken()).toBe(INSTALL);
    expect(installLocked()).toBe(true);
  });

  it('сеанс кончился посреди работы — перечитывание после `401` ведёт на вход', async () => {
    const session = { open: true };
    lockedInstall(session);
    await loadInstallToken();

    session.open = false;

    expect(await refreshInstallToken(INSTALL)).toBeNull();
    expect(installLocked()).toBe(true);
  });

  it('`404` у установки без пароля замка не ставит', async () => {
    answers(null);

    await loadInstallToken();

    expect(installLocked()).toBe(false);
  });

  it('оборванная сеть о замке не говорит ничего: прежнее знание остаётся', async () => {
    const session = { open: true };
    lockedInstall(session);
    await loadInstallToken();
    server.use(http.get(CONFIG, () => HttpResponse.error()));

    expect(await refreshInstallToken(INSTALL)).toBeNull();
    expect(installLocked()).toBe(true);
  });
});
