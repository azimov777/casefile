import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';

const STAMPS = { created_at: '2026-09-22T10:00:00Z', updated_at: '2026-09-22T10:00:00Z' };

function account(overrides: Record<string, unknown> = {}) {
  return {
    id: 'account-owner',
    email: 'owner@localhost',
    participant: 'owner',
    is_admin: false,
    has_password: false,
    disabled_at: null,
    created_by: { kind: 'tracker' as const, signature: null },
    ...STAMPS,
    ...overrides,
  };
}

const ADMIN = account({ is_admin: true });
const NOT_ADMIN = account({ is_admin: false });

const ARCHIVE = {
  data: {
    format: 'casefile.installation-archive' as const,
    format_version: 1,
    schema_revision: 'c4a9d31f7e58',
    app_version: '0.1.0',
    exported_at: '2026-09-22T12:00:00Z',
    tables: [{ name: 'tasks', columns: ['id'], rows: [] }],
  },
};

const IMPORT_RESULT = {
  schema_revision: 'c4a9d31f7e58',
  head_revision: '7e3b52a9c1d4',
  tables: [
    { name: 'tasks', rows: 520 },
    { name: 'entries', rows: 3760 },
  ],
  replaced: { participants: 1, tokens: 1, accounts: 0 },
  machine_keys: ['local-ui'],
  revoked_source_keys: 2,
};

/** Что уходило на бэкенд за прогон: метод и путь. */
let sent: string[] = [];

beforeEach(() => {
  sent = [];
  server.events.on('request:start', ({ request }) => {
    sent.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));
});

/** Своя машина без учётных записей: владелец, каким бы флагом администратора ни был. */
function signedInAsOwner(me: ReturnType<typeof account>) {
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: me }))));
}

/** Установка ключом, без входа — та же оболочка, что у человека на своей машине. */
const LOCAL = { installKey: 'trk_local_install_key' } as const;

function archiveFile(body: unknown = ARCHIVE): File {
  return new File([JSON.stringify(body)], 'casefile-archive-2026-09-22.json', {
    type: 'application/json',
  });
}

describe('экран «Перенос установки»', () => {
  it('администратору: пункт в панели, обе кнопки, заголовки разделов', async () => {
    signedInAsOwner(ADMIN);
    const user = userEvent.setup();
    renderApp('/tasks', LOCAL);

    await user.click(await screen.findByRole('link', { name: say.ui('app.moving') }));

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.moving') }),
    ).toBeVisible();
    expect(screen.getByRole('heading', { name: say.moving('export.title') })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: say.moving('import.title') })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: say.moving('export.action') })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: say.moving('import.action') })).toBeDisabled();
  });

  it('неадминистратору: пункта нет, объяснение вместо кнопок, архив не спрашивается', async () => {
    signedInAsOwner(NOT_ADMIN);
    renderApp('/moving', LOCAL);

    expect(await screen.findByText(say.moving('notAdmin'))).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: say.ui('app.moving') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.moving('export.action') })).toBeNull();
    expect(screen.queryByRole('button', { name: say.moving('import.action') })).toBeNull();
    expect(sent).not.toContain('GET /api/v1/installation/archive');
  });

  it('выгрузка: кнопка спрашивает архив и остаётся доступной после ответа', async () => {
    signedInAsOwner(ADMIN);
    server.use(http.get(`${API}/api/v1/installation/archive`, () => data(ARCHIVE.data)));
    const user = userEvent.setup();
    renderApp('/moving', LOCAL);

    await user.click(await screen.findByRole('button', { name: say.moving('export.action') }));

    await waitFor(() => expect(sent).toContain('GET /api/v1/installation/archive'));
    expect(await screen.findByRole('button', { name: say.moving('export.action') })).toBeEnabled();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('выгрузка: отказ показывается словами словаря', async () => {
    signedInAsOwner(ADMIN);
    server.use(
      http.get(`${API}/api/v1/installation/archive`, () =>
        failure('admin_required', 403, 'Admins only'),
      ),
    );
    const user = userEvent.setup();
    renderApp('/moving', LOCAL);

    await user.click(await screen.findByRole('button', { name: say.moving('export.action') }));

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('admin_required'));
  });

  it('выбранный файл — не JSON: ошибка сразу, «Принять» недоступна', async () => {
    signedInAsOwner(ADMIN);
    const user = userEvent.setup();
    renderApp('/moving', LOCAL);

    const input = (await screen.findByLabelText(
      say.moving('import.fileLabel'),
    )) as HTMLInputElement;
    // Тип и имя совпадают с `accept` поля: `userEvent.upload` сам отсеивает файл,
    // который под него не подходит, — а здесь важно содержимое, а не выбор файла.
    const broken = new File(['не json вовсе'], 'bad-archive.json', { type: 'application/json' });
    await user.upload(input, broken);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      say.errors('archive_format_unsupported'),
    );
    expect(screen.getByRole('button', { name: say.moving('import.action') })).toBeDisabled();
  });

  it('приём: подтверждение называет файл и предупреждает, отправка несёт файл как есть, итог на экране', async () => {
    signedInAsOwner(ADMIN);
    let body: unknown = null;
    server.use(
      http.post(`${API}/api/v1/installation/archive`, async ({ request }) => {
        body = await request.json();
        return data(IMPORT_RESULT);
      }),
    );
    const user = userEvent.setup();
    renderApp('/moving', LOCAL);

    const input = (await screen.findByLabelText(
      say.moving('import.fileLabel'),
    )) as HTMLInputElement;
    await user.upload(input, archiveFile());
    await waitFor(() =>
      expect(screen.getByRole('button', { name: say.moving('import.action') })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: say.moving('import.action') }));

    const confirm = await screen.findByRole('alertdialog');
    expect(within(confirm).getByText(say.moving('import.warning'))).toBeInTheDocument();
    expect(within(confirm).getByText('casefile-archive-2026-09-22.json')).toBeInTheDocument();

    await user.click(within(confirm).getByRole('button', { name: say.moving('import.confirm') }));

    // Тело — файл выгрузки как есть, той же формой, что и разобранный JSON.
    expect(body).toEqual(ARCHIVE);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    const result = await screen.findByRole('region', { name: say.moving('import.result.label') });
    expect(within(result).getByText('local-ui')).toBeInTheDocument();
    expect(within(result).getByText('c4a9d31f7e58')).toBeInTheDocument();
    expect(within(result).getByText('7e3b52a9c1d4')).toBeInTheDocument();
    expect(within(result).getByText('2')).toBeInTheDocument();
  });

  it('повторный приём: отказ `installation_not_empty` остаётся в открытом окне', async () => {
    signedInAsOwner(ADMIN);
    server.use(
      http.post(`${API}/api/v1/installation/archive`, () =>
        failure('installation_not_empty', 409, 'Not empty'),
      ),
    );
    const user = userEvent.setup();
    renderApp('/moving', LOCAL);

    const input = (await screen.findByLabelText(
      say.moving('import.fileLabel'),
    )) as HTMLInputElement;
    await user.upload(input, archiveFile());
    await waitFor(() =>
      expect(screen.getByRole('button', { name: say.moving('import.action') })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: say.moving('import.action') }));
    const confirm = await screen.findByRole('alertdialog');
    await user.click(within(confirm).getByRole('button', { name: say.moving('import.confirm') }));

    // Предупреждение окна тоже `tone="danger"` (тот же образец, что `RevokeDialog`) и
    // тоже несёт `role="alert"`, поэтому отказ ищется текстом, а не голой ролью — ролей
    // в окне на этот момент две.
    expect(
      await within(confirm).findByText(say.errors('installation_not_empty')),
    ).toBeInTheDocument();
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('отмена в окне подтверждения не отправляет запрос', async () => {
    signedInAsOwner(ADMIN);
    let posted = false;
    server.use(
      http.post(`${API}/api/v1/installation/archive`, () => {
        posted = true;
        return data(IMPORT_RESULT);
      }),
    );
    const user = userEvent.setup();
    renderApp('/moving', LOCAL);

    const input = (await screen.findByLabelText(
      say.moving('import.fileLabel'),
    )) as HTMLInputElement;
    await user.upload(input, archiveFile());
    await waitFor(() =>
      expect(screen.getByRole('button', { name: say.moving('import.action') })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: say.moving('import.action') }));
    const confirm = await screen.findByRole('alertdialog');
    await user.click(within(confirm).getByRole('button', { name: say.moving('cancel') }));

    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(posted).toBe(false);
  });

  it('говорит по-русски целиком', async () => {
    signedInAsOwner(ADMIN);
    renderApp('/moving', { ...LOCAL, language: 'ru' });

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Перенос установки' }),
    ).toBeVisible();
    // Заголовок рисуется всегда, а кнопки — только после первого кадра (`bootstrap`):
    // ждать их надо отдельно, а не считать, что заголовок уже поручился за весь экран.
    expect(await screen.findByRole('button', { name: 'Скачать архив' })).toBeInTheDocument();
  });
});
