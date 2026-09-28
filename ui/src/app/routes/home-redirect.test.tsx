import { http } from 'msw';
import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, data, task, taskPage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/** Ключ сеанса набора `task`: маршруту `/` больше и не нужно. */
const SESSION = 'trk_session_secret_of_the_interface';

const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-01T10:00:00Z' };

/** Учётная запись владельца установки со своим состоянием знакомства (`TRK-369`). */
function account(status: 'pending' | 'completed' | 'skipped') {
  return {
    id: 'account-owner',
    email: 'owner@localhost',
    participant: 'owner',
    is_admin: true,
    has_password: false,
    disabled_at: null,
    onboarding: { status, hints: { hidden_all: false, hidden: [] } },
    created_by: { kind: 'tracker' as const, signature: null },
    ...STAMPS,
  };
}

beforeEach(() => {
  setToken(SESSION);
  server.use(http.get(`${API}/api/v1/tasks`, () => taskPage([task('DEMO-1')])));
});

/**
 * `/` решает по `bootstrap.account.onboarding.status`, а не по флагу в браузере
 * (`app/routes/home-redirect.tsx`, `TRK-361`, `TRK-360#17`): страничный тест поэтому
 * подменяет только ответ `bootstrap`, а не хранилище вкладки.
 */
describe('/ решает по состоянию знакомства (TRK-361)', () => {
  it('`pending` — открывает «Начало»', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account('pending') }))),
    );

    renderApp('/');

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') }),
    ).toBeInTheDocument();
  });

  it.each(['completed', 'skipped'] as const)('`%s` — список задач', async (status) => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account(status) }))),
    );

    renderApp('/');

    expect(await screen.findByText('Задача DEMO-1')).toBeInTheDocument();
  });

  it('ключ без учётной записи — список задач, как и раньше', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));

    renderApp('/');

    expect(await screen.findByText('Задача DEMO-1')).toBeInTheDocument();
  });
});
