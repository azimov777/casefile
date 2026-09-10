import { HttpResponse, delay, http } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, CONFIG, bootstrap, data, failure, task, taskPage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { loadInstallToken, setToken } from '@/shared/api';

const INSTALL = 'trk_from_the_installation';

/** Заголовки, с которыми ушли запросы к бэкенду: чем именно подписана работа. */
let sent: (string | null)[] = [];
/** Сколько раз спрашивали конфигурацию установки. */
let asked = 0;

beforeEach(() => {
  sent = [];
  asked = 0;
  server.use(
    http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
      sent.push(request.headers.get('Authorization'));
      return data(bootstrap());
    }),
    http.get(`${API}/api/v1/tasks`, ({ request }) => {
      sent.push(request.headers.get('Authorization'));
      return taskPage([task('DEMO-1')]);
    }),
  );
});

/**
 * Установка отдаёт эти тела по очереди; последнее повторяется. `null` — файла нет.
 *
 * `delay` не случайный: без него ответ приходит в том же кадре, и «страж дождался»
 * ничем не отличалось бы от «страж успел».
 */
function installGives(...bodies: (Record<string, unknown> | null)[]) {
  server.use(
    http.get(CONFIG, async () => {
      const body = bodies[Math.min(asked, bodies.length - 1)] ?? null;
      asked += 1;
      await delay(10);
      if (body === null) return new HttpResponse(null, { status: 404 });
      return HttpResponse.json(body);
    }),
  );
}

/**
 * Так приложение начинает работу: конфигурацию читают до первой отрисовки
 * (`src/main.tsx`), и оснастка повторяет этот порядок, а не подсевает результат.
 */
function open(path = '/') {
  const reading = loadInstallToken();
  const rendered = renderApp(path);
  return { reading, ...rendered };
}

/**
 * Ждёт, пока оболочка договорит: имя участника приходит `bootstrap`ом уже после первой
 * отрисовки. Ожидание разбито на шаги намеренно — у каждого свой запас времени, и
 * загруженная машина не превращает «экран не тот» в «экран не успел».
 */
async function shellReady(): Promise<void> {
  await screen.findByText('owner');
}

describe('ключ от установки', () => {
  it('открывает задачи без экрана входа, и запросы идут с ним', async () => {
    installGives({ token: INSTALL });

    const { reading } = open('/');

    // До ответа конфигурации не показано ничего: вспышка входа была бы враньём —
    // ключ есть, просто его ещё не спросили.
    expect(screen.queryByLabelText(say.login('tokenLabel'))).not.toBeInTheDocument();
    await reading;
    await shellReady();

    expect(await screen.findByText('DEMO-1')).toBeInTheDocument();
    expect(screen.queryByLabelText(say.login('tokenLabel'))).not.toBeInTheDocument();
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.every((header) => header === `Bearer ${INSTALL}`)).toBe(true);
  });

  it('в хранилище браузера не оседает: перезагрузка спросит установку заново', async () => {
    installGives({ token: INSTALL });
    const { reading } = open('/');
    await reading;
    await shellReady();

    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('убирает выход: человеку, который не входил, выходить некуда', async () => {
    installGives({ token: INSTALL });
    const { reading } = open('/');
    await reading;
    await shellReady();

    expect(screen.queryByRole('button', { name: say.ui('app.signOut') })).not.toBeInTheDocument();
  });

  it('старше сохранённого: работа идёт ключом установки, а не прежним входом', async () => {
    setToken('trk_typed_by_hand');
    installGives({ token: INSTALL });

    const { reading } = open('/');
    await reading;
    await shellReady();

    expect(sent.every((header) => header === `Bearer ${INSTALL}`)).toBe(true);
    // Сохранённое не стёрто: это запасной путь, а не мусор.
    expect(window.localStorage.getItem('tracker.token')).toBe('trk_typed_by_hand');
  });
});

describe('установка ключа не дала', () => {
  it('показывает вход, и ошибки на экране нет', async () => {
    installGives(null);

    const { reading } = open('/');
    await reading;

    expect(await screen.findByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
    // `404` — не поломка, а другая установка: там людей несколько и ключ у каждого свой.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: say.login('submit') })).toBeInTheDocument();
  });
});

describe('`401` с ключом от установки', () => {
  /** Бэкенд отвергает всё, кроме названного ключа. */
  function accepts(good: string) {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
        const header = request.headers.get('Authorization');
        sent.push(header);
        if (header !== `Bearer ${good}`) {
          return failure('unauthorized', 401, 'Token is unknown or revoked');
        }
        return data(bootstrap());
      }),
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        const header = request.headers.get('Authorization');
        sent.push(header);
        if (header !== `Bearer ${good}`) {
          return failure('unauthorized', 401, 'Token is unknown or revoked');
        }
        return taskPage([task('DEMO-1')]);
      }),
    );
  }

  it('перечитывает конфигурацию один раз и продолжает работу свежим ключом', async () => {
    // Контур переподняли: вкладка держит прежний ключ, установка отдаёт новый.
    installGives({ token: INSTALL }, { token: 'trk_reissued' });
    accepts('trk_reissued');

    const { reading } = open('/');
    await reading;
    await shellReady();

    expect(await screen.findByText('DEMO-1')).toBeInTheDocument();
    expect(screen.queryByLabelText(say.login('tokenLabel'))).not.toBeInTheDocument();
    // Первое чтение и ровно одно перечитывание, сколько бы запросов ни отказало.
    expect(asked).toBe(2);
    expect(sent).toContain(`Bearer ${INSTALL}`);
    expect(sent).toContain('Bearer trk_reissued');
  });

  it('второй отказ ведёт на вход, а конфигурацию больше не спрашивает', async () => {
    // Установка отдаёт то же самое: повторять нечем.
    installGives({ token: INSTALL });
    accepts('trk_something_else');

    const { reading } = open('/');
    await reading;

    expect(await screen.findByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
    expect(await screen.findByText(say.login('expired'))).toBeInTheDocument();
    await waitFor(() => expect(asked).toBe(2));
    expect(asked).toBe(2);
  });
});
