import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import type { components } from '@/shared/api';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';

type Setting = components['schemas']['InstallationSettingRead'];

const STAMPS = { created_at: '2026-09-22T10:00:00Z', updated_at: '2026-09-22T10:00:00Z' };
const ONBOARDING = { status: 'pending' as const, hints: { hidden_all: false, hidden: [] } };

function account(is_admin: boolean) {
  return {
    id: 'account-owner',
    email: 'owner@localhost',
    participant: 'owner',
    is_admin,
    has_password: false,
    disabled_at: null,
    onboarding: ONBOARDING,
    created_by: { kind: 'tracker' as const, signature: null },
    ...STAMPS,
  };
}

function setting(name: string, overrides: Partial<Setting> = {}): Setting {
  return {
    name,
    env_var: `TRACKER_${name.toUpperCase()}`,
    kind: 'integer',
    value: null,
    effective_value: '1',
    source: 'default',
    default_value: '1',
    default_source: 'default',
    minimum: 1,
    maximum: 10_000,
    updated_by: null,
    updated_at: null,
    ...overrides,
  };
}

function registry(): Setting[] {
  return [
    setting('session_hours', { effective_value: '168', default_value: '168', maximum: 43_800 }),
    setting('oauth_access_ttl', {
      kind: 'duration',
      effective_value: 'PT2592000S',
      default_value: 'PT2592000S',
      minimum: 60,
      maximum: 31_536_000,
    }),
    setting('mcp_page_size', {
      effective_value: '25',
      default_value: '25',
      default_source: 'environment',
      maximum: 200,
    }),
    setting('mcp_text_limit', {
      effective_value: '2000',
      default_value: '2000',
      minimum: 200,
      maximum: 100_000,
    }),
    setting('release_check', {
      kind: 'boolean',
      effective_value: 'true',
      default_value: 'true',
      minimum: null,
      maximum: null,
    }),
    setting('file_max_bytes', {
      effective_value: '26214400',
      default_value: '26214400',
      maximum: 1_073_741_824,
    }),
    setting('file_unopened_days', {
      effective_value: '90',
      default_value: '90',
      maximum: 3650,
    }),
  ];
}

const LOCAL = { installKey: 'trk_local_install_key' } as const;

let stored: Setting[] = [];
let sent: { method: string; path: string; body: unknown }[] = [];

beforeEach(() => {
  stored = registry();
  sent = [];
  server.events.on('request:start', ({ request }) => {
    const path = new URL(request.url).pathname;
    if (path.startsWith('/api/v1/settings'))
      sent.push({ method: request.method, path, body: null });
  });
  server.use(
    http.get(`${API}/api/v1/tasks`, () => collection([])),
    http.get(`${API}/api/v1/settings`, () => collection(stored)),
    http.patch(`${API}/api/v1/settings/:name`, async ({ params, request }) => {
      const body = (await request.json()) as { value: string | null };
      const index = stored.findIndex((item) => item.name === params.name);
      const current = stored[index];
      if (current === undefined) return failure('installation_setting_not_found', 404);
      if (body.value === '100' && current.name === 'mcp_text_limit') {
        return failure('installation_setting_invalid', 422, 'Invalid', {
          name: current.name,
          reason: 'too_small',
          minimum: 200,
          maximum: 100_000,
        });
      }
      const changed: Setting =
        body.value === null
          ? { ...current, value: null, effective_value: current.default_value, source: 'default' }
          : {
              ...current,
              value: body.value,
              effective_value: body.value,
              source: 'database',
              updated_by: { kind: 'human', signature: 'owner' },
              updated_at: '2026-10-26T10:00:00Z',
            };
      stored[index] = changed;
      return data(changed);
    }),
  );
});

function signedIn(isAdmin: boolean) {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account(isAdmin) }))),
  );
}

function row(name: string) {
  return screen.getByRole('article', { name: say.settings(`items.${name}.title` as never) });
}

describe('экран «Настройки»', () => {
  it('семь строк: название, значение, источник, умолчание; пункт в панели у всех', async () => {
    signedIn(false);
    const user = userEvent.setup();
    renderApp('/tasks', LOCAL);

    await user.click(await screen.findByRole('link', { name: say.ui('app.settings') }));

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.settings') }),
    ).toBeVisible();
    expect(await screen.findAllByRole('article')).toHaveLength(7);

    const page = within(row('mcp_page_size'));
    expect(page.getByText(/^25 /, { selector: '[data-role="value"]' })).toBeVisible();
    expect(page.getByText(say.settings('sources.default'))).toBeVisible();
    expect(
      page.getByText(/TRACKER_MCP_PAGE_SIZE/, { selector: '[data-role="default"]' }),
    ).toBeVisible();

    expect(
      within(row('oauth_access_ttl')).getByText('30 ' + say.settings('units.days'), {
        selector: '[data-role="value"]',
      }),
    ).toBeVisible();
    expect(
      within(row('file_max_bytes')).getByText('25 ' + say.settings('units.megabytes'), {
        selector: '[data-role="value"]',
      }),
    ).toBeVisible();
    expect(within(row('release_check')).getByText(say.settings('boolean.on'))).toBeVisible();
  });

  it('не администратору: объяснение, значения видны, полей и кнопок нет', async () => {
    signedIn(false);
    renderApp('/settings', LOCAL);

    expect(await screen.findByText(say.settings('readOnly'))).toBeVisible();
    expect(await screen.findAllByRole('article')).toHaveLength(7);
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: say.settings('form.save') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.settings('form.reset') })).toBeNull();
  });

  it('администратор сохраняет 10: значение и источник «база», кто изменил; затем сбрасывает', async () => {
    signedIn(true);
    const user = userEvent.setup();
    renderApp('/settings', LOCAL);

    await screen.findAllByRole('article');
    const page = () => within(row('mcp_page_size'));
    expect(page().queryByRole('button', { name: say.settings('form.reset') })).toBeNull();

    const field = page().getByRole('textbox', { name: say.settings('form.newValue') });
    await user.clear(field);
    await user.type(field, '10');
    await user.click(page().getByRole('button', { name: say.settings('form.save') }));

    await waitFor(() => expect(page().getByText(say.settings('sources.database'))).toBeVisible());
    expect(page().getByText(/^10 /, { selector: '[data-role="value"]' })).toBeVisible();
    expect(
      page().getByText(say.settings('row.changedBy', { author: 'owner' }), { exact: false }),
    ).toBeVisible();
    expect(
      sent.some((call) => call.method === 'PATCH' && call.path.endsWith('/mcp_page_size')),
    ).toBe(true);

    await user.click(page().getByRole('button', { name: say.settings('form.reset') }));
    await waitFor(() => expect(page().getByText(say.settings('sources.default'))).toBeVisible());
    expect(page().getByText(/^25 /, { selector: '[data-role="value"]' })).toBeVisible();
    expect(page().queryByRole('button', { name: say.settings('form.reset') })).toBeNull();
  });

  it('срок и размер вписываются в выбранных единицах', async () => {
    signedIn(true);
    const user = userEvent.setup();
    renderApp('/settings', LOCAL);

    await screen.findAllByRole('article');
    const ttl = within(row('oauth_access_ttl'));
    const field = ttl.getByRole('textbox');
    expect(field).toHaveValue('30');
    expect(ttl.getByRole('combobox', { name: say.settings('form.unit') })).toHaveValue('days');
    await user.clear(field);
    await user.type(field, '2');
    await user.click(ttl.getByRole('button', { name: say.settings('form.save') }));

    await waitFor(() => expect(ttl.getByText(say.settings('sources.database'))).toBeVisible());
    expect(stored.find((item) => item.name === 'oauth_access_ttl')?.value).toBe('PT172800S');
  });

  it('вне пределов: отказ рядом с полем, черновик остаётся, прежнее значение цело', async () => {
    signedIn(true);
    const user = userEvent.setup();
    renderApp('/settings', LOCAL);

    await screen.findAllByRole('article');
    const limit = within(row('mcp_text_limit'));
    const field = limit.getByRole('textbox');
    await user.clear(field);
    await user.type(field, '100');
    await user.click(limit.getByRole('button', { name: say.settings('form.save') }));

    const alert = await limit.findByRole('alert');
    expect(alert).toHaveTextContent('200');
    expect(alert).toHaveTextContent('100000');
    expect(field).toHaveValue('100');
    expect(limit.getByText(/^2000 /, { selector: '[data-role="value"]' })).toBeVisible();
    expect(limit.getByText(say.settings('sources.default'))).toBeVisible();
  });

  it('не число: до сервера не доходит', async () => {
    signedIn(true);
    const user = userEvent.setup();
    renderApp('/settings', LOCAL);

    await screen.findAllByRole('article');
    const limit = within(row('mcp_page_size'));
    const field = limit.getByRole('textbox');
    await user.clear(field);
    await user.type(field, '1.5');
    await user.click(limit.getByRole('button', { name: say.settings('form.save') }));

    expect(await limit.findByRole('alert')).toHaveTextContent(
      say.settings('errors.not_an_integer'),
    );
    expect(sent.some((call) => call.method === 'PATCH')).toBe(false);
  });

  it('логическая настройка выбирается, а не вписывается', async () => {
    signedIn(true);
    const user = userEvent.setup();
    renderApp('/settings', LOCAL);

    await screen.findAllByRole('article');
    const check = within(row('release_check'));
    await user.selectOptions(check.getByRole('combobox'), 'false');
    await user.click(check.getByRole('button', { name: say.settings('form.save') }));

    await waitFor(() =>
      expect(
        check.getByText(say.settings('boolean.off'), { selector: '[data-role="value"]' }),
      ).toBeVisible(),
    );
    expect(stored.find((item) => item.name === 'release_check')?.value).toBe('false');
  });
});
