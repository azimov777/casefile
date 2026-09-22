import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';

const ALICE = {
  id: '44444444-4444-4444-4444-444444444444',
  email: 'alice@example.com',
  participant: 'alice',
  is_admin: false,
  has_password: true,
  disabled_at: null,
  created_by: { kind: 'human', signature: 'owner' },
  created_at: '2026-09-22T10:00:00Z',
  updated_at: '2026-09-22T10:00:00Z',
} as const;

/** Режим входа по учётным записям: вкладка работает токеном сеанса. */
const SIGN_IN = { installKey: 'trk_session_of_alice', signIn: true } as const;

function signedIn() {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: ALICE }))),
    http.get(`${API}/api/v1/tasks`, () => collection([])),
  );
}

async function fill(current: string, next: string, repeat: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(say.account('password.currentLabel')), current);
  await user.type(screen.getByLabelText(say.account('password.newLabel')), next);
  await user.type(screen.getByLabelText(say.account('password.repeatLabel')), repeat);
  await user.click(screen.getByRole('button', { name: say.account('password.submit') }));
}

describe('экран «Моя учётная запись»', () => {
  it('открывается из панели почтой и называет себя', async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp('/tasks', SIGN_IN);

    await user.click(await screen.findByRole('link', { name: new RegExp(ALICE.email) }));

    expect(address.current).toBe('/account');
    const main = await screen.findByRole('main');
    expect(within(main).getByText(ALICE.email)).toBeInTheDocument();
    expect(within(main).getByText('alice')).toBeInTheDocument();
    expect(within(main).getByText(say.account('member'))).toBeInTheDocument();
  });

  it('смена пароля уходит с прежним паролем, поля очищаются, исход сказан', async () => {
    signedIn();
    let body: unknown = null;
    server.use(
      http.put(`${API}/api/v1/accounts/:id/password`, async ({ request, params }) => {
        body = { id: params.id, ...((await request.json()) as object) };
        return data(ALICE);
      }),
    );
    renderApp('/account', SIGN_IN);

    await fill('old password 12', 'new password 1234', 'new password 1234');

    expect(await screen.findByText(say.account('password.changed'))).toBeInTheDocument();
    expect(body).toEqual({
      id: ALICE.id,
      current_password: 'old password 12',
      new_password: 'new password 1234',
    });
    expect(screen.getByLabelText(say.account('password.newLabel'))).toHaveValue('');
  });

  it('несовпавший повтор ловится до отправки', async () => {
    signedIn();
    let asked = 0;
    server.use(
      http.put(`${API}/api/v1/accounts/:id/password`, () => {
        asked += 1;
        return data(ALICE);
      }),
    );
    renderApp('/account', SIGN_IN);

    await fill('old password 12', 'new password 1234', 'new password 12345');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.account('password.mismatch'));
    expect(asked).toBe(0);
  });

  it('неверный прежний пароль — отказ словами словаря', async () => {
    signedIn();
    server.use(
      http.put(`${API}/api/v1/accounts/:id/password`, () =>
        failure('current_password_mismatch', 422, 'Wrong current password'),
      ),
    );
    renderApp('/account', SIGN_IN);

    await fill('wrong password 12', 'new password 1234', 'new password 1234');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      say.errors('current_password_mismatch'),
    );
  });

  it('на своей машине экрана нет', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: ALICE }))),
      http.get(`${API}/api/v1/tasks`, () => collection([])),
    );
    renderApp('/account', { installKey: 'trk_local_install_key' });

    expect(await screen.findByText(say.ui('app.notFound.title'))).toBeInTheDocument();
  });
});
