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
 * Режим входа по учётным записям (`TRK-113`) глазами интерфейса.
 *
 * Подмена повторяет контракт образа и API: `/config.json` всегда отвечает
 * `401 {"login":"password"}`, вход `POST /api/v1/session` отдаёт токен сеанса, а
 * `GET /api/v1/session` — тот же токен, пока сеанс жив. Сеанс здесь — флаг подмены, а
 * не кука: `HttpOnly` скрипту не видна ни в jsdom, ни в браузере. Саму куку, nginx и
 * двух людей в двух браузерах проверяет `e2e/account-login.spec.ts`.
 */
const EMAIL = 'alice@example.com';
const PASSWORD = 'correct horse battery staple';
const SESSION = 'trk_session_of_alice';

const ACCOUNT = {
  id: '44444444-4444-4444-4444-444444444444',
  email: EMAIL,
  participant: 'alice',
  is_admin: false,
  has_password: true,
  disabled_at: null,
  created_by: { kind: 'human', signature: 'owner' },
  created_at: '2026-09-22T10:00:00Z',
  updated_at: '2026-09-22T10:00:00Z',
} as const;

let session = false;
/** Заголовки запросов к бэкенду: чем подписана работа после входа. */
let sent: (string | null)[] = [];
/** Тела входа: что уходило на сервер. */
let logins: unknown[] = [];
let closed = 0;

beforeEach(() => {
  session = false;
  sent = [];
  logins = [];
  closed = 0;
  server.use(
    http.get(CONFIG, () => HttpResponse.json({ login: 'password' }, { status: 401 })),
    http.get(`${API}/api/v1/session`, () =>
      session
        ? data({ token: SESSION, expires_at: '2026-09-25T12:00:00Z', account: ACCOUNT })
        : failure('unauthorized', 401, 'No session', { reason: 'missing_session' }),
    ),
    http.post(`${API}/api/v1/session`, async ({ request }) => {
      const body = (await request.json()) as { email?: string; password?: string };
      logins.push(body);
      if (body.email !== EMAIL || body.password !== PASSWORD) {
        return failure('unauthorized', 401, 'Wrong email or password', {
          reason: 'wrong_credentials',
        });
      }
      session = true;
      return data({ token: SESSION, expires_at: '2026-09-25T12:00:00Z', account: ACCOUNT });
    }),
    http.delete(`${API}/api/v1/session`, () => {
      session = false;
      closed += 1;
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
      sent.push(request.headers.get('Authorization'));
      return data(
        bootstrap({
          participant: { ...bootstrap().participant!, name: 'alice' },
          account: ACCOUNT,
        }),
      );
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

async function signIn(email: string, password: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(say.login('emailLabel')), email);
  await user.type(screen.getByLabelText(say.login('passwordLabel')), password);
  await user.click(screen.getByRole('button', { name: say.login('submit') }));
  return user;
}

describe('режим входа по учётным записям', () => {
  it('спрашивает почту и пароль, а не токен, и ошибки на экране нет', async () => {
    await open('/');

    expect(await screen.findByLabelText(say.login('emailLabel'))).toHaveAttribute('type', 'email');
    expect(screen.getByLabelText(say.login('passwordLabel'))).toHaveAttribute('type', 'password');
    expect(screen.queryByLabelText(say.login('tokenLabel'))).not.toBeInTheDocument();
    expect(screen.getByText(say.login('signInIntro'))).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('неверные почта или пароль объясняются словами входа, и ключа нет', async () => {
    await open('/');

    await signIn(EMAIL, 'not the password at all');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.login('credentialsWrong'));
    expect(screen.getByLabelText(say.login('emailLabel'))).toBeInTheDocument();
    expect(sent).toEqual([]);
  });

  it('отключённая учётная запись названа своими словами', async () => {
    server.use(
      http.post(`${API}/api/v1/session`, () =>
        failure('unauthorized', 401, 'Account disabled', { reason: 'account_disabled' }),
      ),
    );
    await open('/');

    await signIn(EMAIL, PASSWORD);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.login('accountDisabled'));
  });

  /**
   * `details.scope` различает, чьё окно кончилось (`TRK-113#10`): без него (или с
   * незнакомым интерфейсу значением) экран показывает общий текст с секундами.
   */
  it.each([
    [undefined, 'throttled'],
    ['a-future-scope-value', 'throttled'],
    ['address', 'throttledAddress'],
    ['account', 'throttledAccount'],
    ['installation', 'throttledInstallation'],
  ] as const)('scope %s называет секунды словами своего текста', async (scope, key) => {
    server.use(
      http.post(`${API}/api/v1/session`, () =>
        failure('password_attempts_exceeded', 429, 'Too many password attempts', {
          retry_after: 42,
          limit: 5,
          window_seconds: 60,
          ...(scope === undefined ? {} : { scope }),
        }),
      ),
    );
    await open('/');

    await signIn(EMAIL, PASSWORD);

    expect(await screen.findByRole('alert')).toHaveTextContent(say.login(key, { seconds: 42 }));
  });

  it('верный вход открывает задачи токеном сеанса из ответа, и в хранилище не остаётся ничего', async () => {
    await open('/');

    await signIn(`  ${EMAIL} `, PASSWORD);

    expect(await screen.findByText('DEMO-1')).toBeInTheDocument();
    // Почта уходит без пробелов по краям, пароль — как набран.
    expect(logins).toEqual([{ email: EMAIL, password: PASSWORD }]);
    expect(sent.length).toBeGreaterThan(0);
    expect(sent.every((header) => header === `Bearer ${SESSION}`)).toBe(true);
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(PASSWORD);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(PASSWORD);
  });

  it('живой сеанс на загрузке: сразу задачи, без экрана входа', async () => {
    session = true;
    await open('/');

    expect(await screen.findByText('DEMO-1')).toBeInTheDocument();
    expect(screen.queryByLabelText(say.login('emailLabel'))).not.toBeInTheDocument();
  });

  it('панель называет почту и ведёт на свою учётную запись; людей неадминистратору нет', async () => {
    session = true;
    await open('/');

    expect(await screen.findByRole('link', { name: new RegExp(EMAIL) })).toHaveAttribute(
      'href',
      '/account',
    );
    expect(screen.queryByRole('link', { name: say.ui('app.people') })).not.toBeInTheDocument();
  });

  it('выход есть и закрывает сеанс на сервере, а вернувшегося снова спрашивают почту', async () => {
    await open('/');
    const user = await signIn(EMAIL, PASSWORD);
    await screen.findByText('DEMO-1');

    await user.click(screen.getByRole('button', { name: say.ui('app.signOut') }));

    expect(await screen.findByLabelText(say.login('emailLabel'))).toBeInTheDocument();
    await waitFor(() => expect(closed).toBe(1));
    expect(session).toBe(false);
  });

  it('отказ `401` посреди работы переспрашивает сеанс и без него ведёт на вход', async () => {
    session = true;
    await open('/');
    await screen.findByText('DEMO-1');

    // Сеанс погасили (сброс пароля администратором, выход в соседней вкладке).
    session = false;
    server.use(
      http.get(`${API}/api/v1/tasks`, () =>
        failure('unauthorized', 401, 'Token revoked', { reason: 'token_revoked' }),
      ),
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('link', { name: say.ui('app.allTasks') }));
    // Страница списка перечитывается при каждом переходе; отказ уводит на вход.
    await user.click(screen.getAllByRole('link', { name: /DEMO/ })[0]!);

    expect(await screen.findByLabelText(say.login('emailLabel'))).toBeInTheDocument();
    expect(await screen.findByText(say.login('signInExpired'))).toBeInTheDocument();
  });
});
