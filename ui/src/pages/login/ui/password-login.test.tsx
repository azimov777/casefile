import { HttpResponse, http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, CONFIG, bootstrap, data, failure, task, taskPage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { loadInstallToken } from '@/shared/api';

/**
 * Установка, закрытая паролем владельца (`TRK-90`), глазами интерфейса.
 *
 * Подмена повторяет контракт образа: без сеанса `/config.json` отвечает
 * `401 {"login":"password"}`, после входа — ключом и тем же полем. Сеанс здесь — флаг
 * подмены, а не кука: `HttpOnly` скрипту не видна и в jsdom, и в браузере, и интерфейс
 * о ней не знает ничего, кроме того, что `/config.json` начал отдавать ключ. Саму куку
 * и nginx проверяет сквозной сценарий `e2e/password-login.spec.ts`.
 */
const INSTALL = 'trk_after_the_password';
const PASSWORD = 'correct horse battery staple';

let session = false;
/** Заголовки запросов к бэкенду: чем подписана работа после входа. */
let sent: (string | null)[] = [];
let closed = 0;

beforeEach(() => {
  session = false;
  sent = [];
  closed = 0;
  server.use(
    http.get(CONFIG, () =>
      session
        ? HttpResponse.json({ token: INSTALL, login: 'password' })
        : HttpResponse.json({ login: 'password' }, { status: 401 }),
    ),
    http.post(`${API}/api/v1/session`, async ({ request }) => {
      const body = (await request.json()) as { password?: string };
      if (body.password !== PASSWORD) {
        return failure('unauthorized', 401, 'Password does not match', {
          reason: 'wrong_password',
        });
      }
      session = true;
      return data({ expires_at: '2026-09-25T12:00:00Z' });
    }),
    http.delete(`${API}/api/v1/session`, () => {
      session = false;
      closed += 1;
      return new HttpResponse(null, { status: 204 });
    }),
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

/** Так приложение начинает работу: конфигурацию читают до первой отрисовки. */
async function open(path = '/') {
  const reading = loadInstallToken();
  renderApp(path);
  await reading;
}

async function typePassword(password: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(say.login('passwordLabel')), password);
  await user.click(screen.getByRole('button', { name: say.login('submit') }));
  return user;
}

describe('установка, закрытая паролем', () => {
  it('спрашивает пароль, а не токен, и ошибки на экране нет', async () => {
    await open('/');

    expect(await screen.findByLabelText(say.login('passwordLabel'))).toHaveAttribute(
      'type',
      'password',
    );
    expect(screen.queryByLabelText(say.login('tokenLabel'))).not.toBeInTheDocument();
    expect(screen.getByText(say.login('passwordIntro'))).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('неверный пароль объясняется словами входа, и ключа нет', async () => {
    await open('/');

    await typePassword('not the password at all');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.login('passwordWrong'));
    expect(screen.getByLabelText(say.login('passwordLabel'))).toBeInTheDocument();
    expect(sent).toEqual([]);
  });

  it('окно попыток называет секунды из отказа', async () => {
    server.use(
      http.post(`${API}/api/v1/session`, () =>
        failure('password_attempts_exceeded', 429, 'Too many password attempts', {
          retry_after: 42,
          limit: 5,
          window_seconds: 60,
        }),
      ),
    );
    await open('/');

    await typePassword(PASSWORD);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      say.login('passwordThrottled', { seconds: 42 }),
    );
  });

  it('верный пароль открывает задачи ключом установки, и в хранилище не остаётся ничего', async () => {
    await open('/');

    await typePassword(PASSWORD);

    expect(await screen.findByText('DEMO-1')).toBeInTheDocument();
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.every((header) => header === `Bearer ${INSTALL}`)).toBe(true);
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(PASSWORD);
  });

  it('пароль принят, а ключа нет — отказ с причиной, а не тот же экран по кругу', async () => {
    server.use(
      http.post(`${API}/api/v1/session`, () => data({ expires_at: '2026-09-25T12:00:00Z' })),
    );
    await open('/');

    await typePassword(PASSWORD);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('install_key_missing'));
  });

  it('выход есть и закрывает сеанс на сервере, а вернувшегося снова спрашивают пароль', async () => {
    await open('/');
    const user = await typePassword(PASSWORD);
    await screen.findByText('owner');

    await user.click(screen.getByRole('button', { name: say.ui('app.signOut') }));

    expect(await screen.findByLabelText(say.login('passwordLabel'))).toBeInTheDocument();
    await waitFor(() => expect(closed).toBe(1));
    expect(session).toBe(false);
  });
});
