import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';

const SESSION = 'trk_session_of_the_admin';
/** Пароль, который трекер генерирует и отдаёт один раз. */
const GENERATED = 'generated-once-Kx9v-2mQp-7tLw';

const STAMPS = { created_at: '2026-09-22T10:00:00Z', updated_at: '2026-09-22T10:00:00Z' };

function account(email: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `id-${email}`,
    email,
    participant: email.split('@')[0]!.replace(/\W/g, '_'),
    is_admin: false,
    has_password: true,
    disabled_at: null,
    created_by: { kind: 'human' as const, signature: 'owner' },
    ...STAMPS,
    ...overrides,
  };
}

const ADMIN = account('owner@localhost', { is_admin: true, participant: 'owner' });
const ALICE = account('alice@example.com');
const BOB = account('bob@example.com', { disabled_at: '2026-09-22T11:00:00Z' });

/** Что уходило на бэкенд за прогон: метод и путь. */
let sent: string[] = [];

beforeEach(() => {
  sent = [];
  server.events.on('request:start', ({ request }) => {
    sent.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  server.use(
    http.get(`${API}/api/v1/accounts`, () => collection([ADMIN, ALICE, BOB])),
    http.get(`${API}/api/v1/tasks`, () => collection([])),
  );
});

/** Режим входа по учётным записям: вкладка работает токеном сеанса. */
const SIGN_IN = { installKey: SESSION, signIn: true } as const;

/** Вошёл человек с этой учётной записью. */
function signedInAs(me: ReturnType<typeof account> | null) {
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: me }))));
}

function card(email: string): HTMLElement {
  return screen.getByRole('article', { name: say.ui('account.label', { email }) });
}

/** Кнопки-действия: время — переключатель подписи (`aria-pressed`, UI-153), не действие. */
function actions(scope: HTMLElement): HTMLElement[] {
  return within(scope)
    .queryAllByRole('button')
    .filter((button) => !button.hasAttribute('aria-pressed'));
}

describe('экран «Люди»', () => {
  it('администратору: пункт в панели, список учётных записей, у своей нет действий', async () => {
    signedInAs(ADMIN);
    const user = userEvent.setup();
    renderApp('/tasks', SIGN_IN);

    await user.click(await screen.findByRole('link', { name: say.ui('app.people') }));

    expect(address.current).toBe('/people');
    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.people') }),
    ).toBeVisible();
    await screen.findByText(ALICE.email);
    expect(within(card(ADMIN.email)).getByText(say.ui('account.you'))).toBeInTheDocument();
    // Действий нет. Время — переключатель подписи на точное (`aria-pressed`, UI-153),
    // а не действие над строкой, и в счёт не идёт.
    expect(actions(card(ADMIN.email))).toEqual([]);
    expect(within(card(BOB.email)).getByText(say.ui('account.disabled'))).toBeInTheDocument();
    // У отключённого сброса нет — только включение.
    expect(
      within(card(BOB.email)).getByRole('button', { name: say.people('enable.action') }),
    ).toBeInTheDocument();
    expect(
      within(card(BOB.email)).queryByRole('button', { name: say.people('reset.action') }),
    ).toBeNull();
  });

  it('неадминистратору по прямой ссылке — объяснение, пункта нет, список не спрашивается', async () => {
    signedInAs(ALICE);
    renderApp('/people', SIGN_IN);

    expect(await screen.findByText(say.people('notAdmin'))).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: say.ui('app.people') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.people('create.open') })).toBeNull();
    expect(sent).not.toContain('GET /api/v1/accounts');
  });

  it('на своей машине экрана нет: адрес — «страница не найдена», пунктов и выхода в панели нет', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: ADMIN }))));
    renderApp('/people', { installKey: 'trk_local_install_key' });

    expect(await screen.findByText(say.ui('app.notFound.title'))).toBeInTheDocument();
    await screen.findByText('owner');
    expect(screen.queryByRole('link', { name: say.ui('app.people') })).toBeNull();
    expect(screen.queryByRole('link', { name: new RegExp(say.ui('app.account')) })).toBeNull();
    expect(screen.queryByRole('button', { name: say.ui('app.signOut') })).toBeNull();
    expect(sent).not.toContain('GET /api/v1/accounts');
  });

  it('заведение со сгенерированным паролем показывает его один раз, закрытие окна уносит', async () => {
    signedInAs(ADMIN);
    let body: Record<string, unknown> = {};
    server.use(
      http.post(`${API}/api/v1/accounts`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return data(
          { ...account('carol@example.com', { participant: 'carol' }), password: GENERATED },
          201,
        );
      }),
    );
    const user = userEvent.setup();
    const { container, queryClient } = renderApp('/people', SIGN_IN);

    await user.click(await screen.findByRole('button', { name: say.people('create.open') }));
    const form = await screen.findByRole('dialog');
    await user.type(
      within(form).getByLabelText(say.people('create.emailLabel')),
      ' carol@example.com ',
    );
    await user.type(within(form).getByLabelText(say.people('create.nameLabel')), 'carol');
    await user.click(within(form).getByRole('button', { name: say.people('create.submit') }));

    // Пароль не вписан — его не было и в запросе: генерирует трекер.
    expect(body).toEqual({
      email: 'carol@example.com',
      name: 'carol',
      description: '',
      is_admin: false,
    });

    const once = await screen.findByRole('dialog', {
      name: say.people('once.createdTitle', { email: 'carol@example.com' }),
    });
    expect(within(once).getByText(GENERATED)).toBeInTheDocument();
    expect(within(once).getByText(say.people('once.onlyOnce'))).toBeInTheDocument();

    await user.click(within(once).getByRole('button', { name: say.people('once.done') }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(container.innerHTML).not.toContain(GENERATED);
    expect(document.body.textContent ?? '').not.toContain(GENERATED);
    expect(JSON.stringify(window.localStorage)).not.toContain(GENERATED);
    expect(JSON.stringify(window.sessionStorage)).not.toContain(GENERATED);
    expect(
      JSON.stringify(
        queryClient
          .getQueryCache()
          .getAll()
          .map((query) => query.state),
      ),
    ).not.toContain(GENERATED);
    expect(
      JSON.stringify(
        queryClient
          .getMutationCache()
          .getAll()
          .map((mutation) => mutation.state),
      ),
    ).not.toContain(GENERATED);
    expect(window.location.href).not.toContain(GENERATED);
  });

  it('вписанный пароль и флаг администратора уходят как есть, окна «один раз» нет', async () => {
    signedInAs(ADMIN);
    let body: Record<string, unknown> = {};
    server.use(
      http.post(`${API}/api/v1/accounts`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return data({ ...account('dan@example.com'), is_admin: true, password: null }, 201);
      }),
    );
    const user = userEvent.setup();
    renderApp('/people', SIGN_IN);

    await user.click(await screen.findByRole('button', { name: say.people('create.open') }));
    const form = await screen.findByRole('dialog');
    await user.type(
      within(form).getByLabelText(say.people('create.emailLabel')),
      'dan@example.com',
    );
    await user.type(within(form).getByLabelText(say.people('create.nameLabel')), 'dan');
    await user.click(within(form).getByLabelText(say.people('create.admin')));
    await user.click(within(form).getByLabelText(say.people('password.type')));
    await user.type(
      within(form).getByLabelText(say.people('password.label')),
      'a typed password 12',
    );
    await user.click(within(form).getByRole('button', { name: say.people('create.submit') }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(body).toEqual({
      email: 'dan@example.com',
      name: 'dan',
      description: '',
      is_admin: true,
      password: 'a typed password 12',
    });
  });

  it('занятая почта объясняется у формы, окно остаётся', async () => {
    signedInAs(ADMIN);
    server.use(
      http.post(`${API}/api/v1/accounts`, () =>
        failure('account_email_taken', 409, 'Email taken', { email: ALICE.email }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/people', SIGN_IN);

    await user.click(await screen.findByRole('button', { name: say.people('create.open') }));
    const form = await screen.findByRole('dialog');
    await user.type(within(form).getByLabelText(say.people('create.emailLabel')), ALICE.email);
    await user.type(within(form).getByLabelText(say.people('create.nameLabel')), 'alice2');
    await user.click(within(form).getByRole('button', { name: say.people('create.submit') }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      say.errors('account_email_taken'),
    );
    expect(within(form).getByLabelText(say.people('create.emailLabel'))).toHaveAttribute(
      'aria-invalid',
      'true',
    );
  });

  it('сброс спрашивает подтверждение и показывает новый пароль один раз', async () => {
    signedInAs(ADMIN);
    let resetBody: unknown = null;
    server.use(
      http.post(`${API}/api/v1/accounts/:id/password-reset`, async ({ request }) => {
        resetBody = await request.json();
        return data({ ...ALICE, password: GENERATED });
      }),
    );
    const user = userEvent.setup();
    renderApp('/people', SIGN_IN);

    await screen.findByText(ALICE.email);
    await user.click(
      within(card(ALICE.email)).getByRole('button', { name: say.people('reset.action') }),
    );
    const confirm = await screen.findByRole('alertdialog');
    expect(within(confirm).getByText(say.people('reset.intro'))).toBeInTheDocument();
    await user.click(within(confirm).getByRole('button', { name: say.people('reset.confirm') }));

    expect(resetBody).toEqual({});
    const once = await screen.findByRole('dialog', {
      name: say.people('once.resetTitle', { email: ALICE.email }),
    });
    expect(within(once).getByText(GENERATED)).toBeInTheDocument();
  });

  it('отключение спрашивает подтверждение с последствиями и уходит `PATCH disabled: true`', async () => {
    signedInAs(ADMIN);
    let patch: unknown = null;
    server.use(
      http.patch(`${API}/api/v1/accounts/:id`, async ({ request }) => {
        patch = await request.json();
        return data({ ...ALICE, disabled_at: '2026-09-22T12:00:00Z' });
      }),
    );
    const user = userEvent.setup();
    renderApp('/people', SIGN_IN);

    await screen.findByText(ALICE.email);
    await user.click(
      within(card(ALICE.email)).getByRole('button', { name: say.people('disable.action') }),
    );
    const confirm = await screen.findByRole('alertdialog');
    expect(within(confirm).getByText(say.people('disable.intro'))).toBeInTheDocument();
    await user.click(within(confirm).getByRole('button', { name: say.people('disable.confirm') }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(patch).toEqual({ disabled: true });
  });

  it('последнего администратора отключить нельзя — отказ словами в окне', async () => {
    const other = account('root@example.com', { is_admin: true });
    signedInAs(ADMIN);
    server.use(
      http.get(`${API}/api/v1/accounts`, () => collection([ADMIN, other])),
      http.patch(`${API}/api/v1/accounts/:id`, () => failure('last_admin', 409, 'Last admin')),
    );
    const user = userEvent.setup();
    renderApp('/people', SIGN_IN);

    await screen.findByText(other.email);
    await user.click(
      within(card(other.email)).getByRole('button', { name: say.people('disable.action') }),
    );
    const confirm = await screen.findByRole('alertdialog');
    await user.click(within(confirm).getByRole('button', { name: say.people('disable.confirm') }));

    expect(await within(confirm).findByRole('alert')).toHaveTextContent(say.errors('last_admin'));
  });

  it('говорит по-русски целиком', async () => {
    signedInAs(ADMIN);
    renderApp('/people', { ...SIGN_IN, language: 'ru' });

    expect(await screen.findByRole('heading', { level: 1, name: 'Люди' })).toBeVisible();
    expect(await screen.findByRole('button', { name: 'Завести человека' })).toBeInTheDocument();
  });
});
