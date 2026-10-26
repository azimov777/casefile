import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import type { components } from '@/shared/api';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';

type FileRead = components['schemas']['FileRead'];

const LOCAL = { installKey: 'trk_local_install_key' } as const;
const ONBOARDING = { status: 'completed' as const, hints: { hidden_all: true, hidden: [] } };
const AUTHOR = { kind: 'human' as const, signature: 'owner' };

function file(id: string, name: string, overrides: Partial<FileRead> = {}): FileRead {
  return {
    id,
    project_key: 'DEMO',
    name,
    mime_type: 'application/pdf',
    size_bytes: 2048,
    sha256: 'a'.repeat(64),
    added_by: AUTHOR,
    added_at: '2026-10-20T10:00:00Z',
    last_opened_at: null,
    deleted: false,
    unopened: false,
    entries: 0,
    tasks: 0,
    ...overrides,
  };
}

let stored: FileRead[] = [];
let requests: URL[] = [];
let deletions: unknown[] = [];

function signedIn() {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
      const archived = new URL(request.url).searchParams.get('include_archived') === 'true';
      const frozen = {
        id: '22222222-2222-2222-2222-222222222223',
        key: 'OLD',
        title: 'Архив',
        description: '',
        last_task_number: 1,
        archived_at: '2026-09-01T10:00:00Z',
        created_by: { kind: 'tracker' as const, signature: null },
        created_at: '2026-09-01T10:00:00Z',
        updated_at: '2026-09-01T10:00:00Z',
      };
      const base = bootstrap({
        account: {
          id: 'account-owner',
          email: 'owner@localhost',
          participant: 'owner',
          is_admin: true,
          has_password: false,
          disabled_at: null,
          onboarding: ONBOARDING,
          created_by: { kind: 'tracker', signature: null },
          created_at: '2026-09-22T10:00:00Z',
          updated_at: '2026-09-22T10:00:00Z',
        },
      });
      return data(archived ? { ...base, projects: [...base.projects, frozen] } : base);
    }),
  );
}

beforeEach(() => {
  stored = [
    file('f1', 'scheme.png', { mime_type: 'image/png', size_bytes: 48_213, entries: 2, tasks: 1 }),
    file('f2', 'report.pdf', { last_opened_at: '2026-10-21T10:00:00Z' }),
    file('f3', 'old.pdf', { project_key: 'OLD' }),
  ];
  requests = [];
  deletions = [];
  signedIn();
  server.use(
    http.get(`${API}/api/v1/tasks`, () => collection([])),
    http.get(`${API}/api/v1/files`, ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      return collection(
        url.searchParams.get('unopened') === 'true' ? stored.filter((f) => f.unopened) : stored,
      );
    }),
    http.get(`${API}/api/v1/settings`, () =>
      collection([
        {
          name: 'file_unopened_days',
          effective_value: '90',
          default_value: '90',
          source: 'default',
          default_source: 'default',
          kind: 'integer',
          value: null,
        },
      ] as never),
    ),
    http.post(`${API}/api/v1/files/delete`, async ({ request }) => {
      const body = (await request.json()) as {
        ids?: string[];
        expected_count?: number;
        unopened?: boolean;
      };
      deletions.push(body);
      const matched = body.unopened === true ? stored.filter((f) => f.unopened) : stored;
      if (body.expected_count !== undefined && body.expected_count !== matched.length) {
        return failure('file_count_mismatch', 409, 'Mismatch', {
          expected: body.expected_count,
          actual: matched.length,
        });
      }
      const gone =
        body.ids === undefined ? matched : stored.filter((f) => body.ids?.includes(f.id));
      stored = stored.filter((f) => !gone.includes(f));
      return data({ deleted: gone.length, files: gone.map((f) => ({ ...f, deleted: true })) });
    }),
  );
});

function card(name: string) {
  return screen.getByRole('article', { name: say.files('item.label', { name }) });
}

describe('экран «Файлы»', () => {
  it('пункт в панели ведёт на экран; карточка несёт имя, проект, размер, число ссылок', async () => {
    const user = userEvent.setup();
    renderApp('/tasks', LOCAL);

    await user.click(await screen.findByRole('link', { name: say.ui('app.files') }));

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.files') }),
    ).toBeVisible();
    const scheme = within(
      await screen.findByRole('article', { name: say.files('item.label', { name: 'scheme.png' }) }),
    );
    expect(scheme.getByText('DEMO')).toBeVisible();
    expect(scheme.getByText('image/png')).toBeVisible();
    expect(scheme.getByText(/47(\.1)? KB/)).toBeVisible();
    expect(scheme.getByText(say.files('item.refs', { count: 2, tasks: 1 }))).toBeVisible();
    expect(scheme.getByText(say.files('item.neverOpened'))).toBeVisible();
    // Открыть можно только изображение; скачать — любой файл.
    expect(scheme.getByRole('button', { name: say.files('actions.open') })).toBeVisible();
    const report = within(card('report.pdf'));
    expect(report.queryByRole('button', { name: say.files('actions.open') })).toBeNull();
    expect(report.getByRole('button', { name: say.files('actions.download') })).toBeVisible();
  });

  it('отбор из адреса уходит на сервер как есть; без условий запрос чистый', async () => {
    renderApp('/files?q=sch&project=DEMO&type=pdf&sort=size&order=asc', LOCAL);
    await screen.findAllByRole('article');

    const url = requests.at(-1);
    expect(url?.searchParams.get('q')).toBe('sch');
    expect(url?.searchParams.get('project')).toBe('DEMO');
    expect(url?.searchParams.get('mime_type')).toBe('application/pdf');
    expect(url?.searchParams.get('sort')).toBe('size');
    expect(url?.searchParams.get('descending')).toBe('false');
    expect(url?.searchParams.has('unopened')).toBe(false);
  });

  it('у файла архивного проекта нет ни выбора, ни «Заменить», ни «Удалить»', async () => {
    renderApp('/files', LOCAL);
    await screen.findAllByRole('article');

    const frozen = within(card('old.pdf'));
    expect(frozen.queryByRole('checkbox')).toBeNull();
    expect(frozen.queryByRole('button', { name: say.files('actions.replace') })).toBeNull();
    expect(frozen.queryByRole('button', { name: say.files('actions.delete') })).toBeNull();
    expect(frozen.getByRole('button', { name: say.files('actions.download') })).toBeVisible();

    const live = within(card('report.pdf'));
    expect(live.getByRole('button', { name: say.files('actions.replace') })).toBeVisible();
    expect(live.getByRole('button', { name: say.files('actions.delete') })).toBeVisible();
  });

  it('удаление выбранных: окно называет число и ссылки, уходят номера', async () => {
    const user = userEvent.setup();
    renderApp('/files', LOCAL);
    await screen.findAllByRole('article');

    await user.click(
      within(card('scheme.png')).getByRole('checkbox', {
        name: say.files('item.select', { name: 'scheme.png' }),
      }),
    );
    expect(screen.getByText(say.files('selection.selected', { count: 1 }))).toBeVisible();

    await user.click(screen.getByRole('button', { name: say.files('selection.deleteSelected') }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(say.files('remove.manyTitle', { count: 1 }))).toBeVisible();
    expect(
      within(dialog).getByText(say.files('remove.refs', { count: 2, tasks: 1 })),
    ).toBeVisible();

    await user.click(within(dialog).getByRole('button', { name: say.files('remove.confirm') }));
    await waitFor(() => expect(deletions).toEqual([{ ids: ['f1'] }]));
    await waitFor(() => expect(screen.queryByText('scheme.png')).toBeNull());
  });

  it('удаление всех отобранных: число посчитано, подтверждено отметкой и уходит expected_count', async () => {
    const user = userEvent.setup();
    renderApp('/files?type=pdf', LOCAL);
    await screen.findAllByRole('article');

    await user.click(screen.getByRole('button', { name: say.files('selection.deleteMatching') }));
    const dialog = await screen.findByRole('alertdialog');
    expect(
      await within(dialog).findByText(say.files('remove.matchingTitle', { count: 3 })),
    ).toBeVisible();

    const confirm = within(dialog).getByRole('button', { name: say.files('remove.confirm') });
    expect(confirm).toBeDisabled();
    await user.click(
      within(dialog).getByRole('checkbox', {
        name: say.files('remove.confirmCount', { count: 3 }),
      }),
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(deletions).toEqual([{ expected_count: 3, mime_type: 'application/pdf' }]),
    );
  });

  it('число изменилось, пока окно было открыто: ничего не удалено, окно называет новое', async () => {
    const user = userEvent.setup();
    renderApp('/files', LOCAL);
    await screen.findAllByRole('article');

    await user.click(screen.getByRole('button', { name: say.files('selection.deleteEverything') }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(
      await within(dialog).findByRole('checkbox', {
        name: say.files('remove.confirmCount', { count: 3 }),
      }),
    );

    // Пока окно открыто, кто-то добавил файл: сервер видит четыре.
    stored = [...stored, file('f4', 'new.pdf')];
    await user.click(within(dialog).getByRole('button', { name: say.files('remove.confirm') }));

    expect(
      await within(dialog).findByText(say.files('remove.mismatch', { actual: 4 })),
    ).toBeVisible();
    expect(stored).toHaveLength(4);
    // Отметка снята: новое число надо подтвердить заново.
    await waitFor(() =>
      expect(
        within(dialog).getByRole('checkbox', {
          name: say.files('remove.confirmCount', { count: 4 }),
        }),
      ).not.toBeChecked(),
    );
  });

  describe('«давно не открывали» (TRK-754)', () => {
    beforeEach(() => {
      stored = [
        file('f1', 'old-a.png', { mime_type: 'image/png', unopened: true }),
        file('f2', 'old-b.png', { mime_type: 'image/png', unopened: true }),
        file('f3', 'fresh.png', { mime_type: 'image/png', last_opened_at: '2026-10-25T10:00:00Z' }),
        file('f4', 'report.pdf'),
      ];
    });

    it('без отбора метка стоит только у карточек с признаком, а запрос не несёт unopened', async () => {
      renderApp('/files', LOCAL);
      await screen.findAllByRole('article');

      expect(requests.at(-1)?.searchParams.has('unopened')).toBe(false);
      const mark = say.files('item.unopened');
      expect(within(card('old-a.png')).getByText(mark)).toBeVisible();
      expect(within(card('old-b.png')).getByText(mark)).toBeVisible();
      expect(within(card('fresh.png')).queryByText(mark)).toBeNull();
      expect(within(card('report.pdf')).queryByText(mark)).toBeNull();
    });

    it('отбор из адреса уходит unopened=true; число отобранных названо, срок и ссылка на настройки видны', async () => {
      renderApp('/files?unopened=1', LOCAL);
      await screen.findAllByRole('article');

      expect(requests.at(-1)?.searchParams.get('unopened')).toBe('true');
      expect(screen.getAllByRole('article')).toHaveLength(2);
      expect(await screen.findByText(say.files('list.unopenedCount', { count: 2 }))).toBeVisible();
      expect(screen.getByRole('checkbox', { name: say.files('filters.unopened') })).toBeChecked();
      expect(screen.getByText(/90/, { selector: '[data-role="unopened-term"]' })).toBeVisible();
      expect(
        screen.getByRole('link', { name: say.files('filters.unopenedSettings') }),
      ).toHaveAttribute('href', '/settings');
    });

    it('переключатель пишет отбор в адрес и запрашивает список заново', async () => {
      const user = userEvent.setup();
      renderApp('/files', LOCAL);
      await screen.findAllByRole('article');

      await user.click(screen.getByRole('checkbox', { name: say.files('filters.unopened') }));
      await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2));
      expect(requests.at(-1)?.searchParams.get('unopened')).toBe('true');
    });

    it('удаление отобранных: окно называет число, уходит expected_count и unopened', async () => {
      const user = userEvent.setup();
      renderApp('/files?unopened=1', LOCAL);
      await screen.findAllByRole('article');

      await user.click(screen.getByRole('button', { name: say.files('selection.deleteUnopened') }));
      const dialog = await screen.findByRole('alertdialog');
      expect(
        await within(dialog).findByText(say.files('remove.matchingTitle', { count: 2 })),
      ).toBeVisible();
      await user.click(
        within(dialog).getByRole('checkbox', {
          name: say.files('remove.confirmCount', { count: 2 }),
        }),
      );
      await user.click(within(dialog).getByRole('button', { name: say.files('remove.confirm') }));

      await waitFor(() => expect(deletions).toEqual([{ expected_count: 2, unopened: true }]));
      // Свежее изображение и документ остались.
      expect(stored.map((f) => f.name)).toEqual(['fresh.png', 'report.pdf']);
    });

    it('число изменилось: ничего не удалено, экран называет новое число', async () => {
      const user = userEvent.setup();
      renderApp('/files?unopened=1', LOCAL);
      await screen.findAllByRole('article');

      await user.click(screen.getByRole('button', { name: say.files('selection.deleteUnopened') }));
      const dialog = await screen.findByRole('alertdialog');
      await user.click(
        await within(dialog).findByRole('checkbox', {
          name: say.files('remove.confirmCount', { count: 2 }),
        }),
      );
      stored = [...stored, file('f5', 'old-c.png', { mime_type: 'image/png', unopened: true })];
      await user.click(within(dialog).getByRole('button', { name: say.files('remove.confirm') }));

      expect(
        await within(dialog).findByText(say.files('remove.mismatch', { actual: 3 })),
      ).toBeVisible();
      expect(stored).toHaveLength(5);
    });
  });

  it('загрузка уходит с ключом повтора', async () => {
    const sent: { kind: string; key: string | null }[] = [];
    server.use(
      http.post(`${API}/api/v1/files`, async ({ request }) => {
        // Тело формы в jsdom не проверить: его `FormData` не тот, что у `fetch` (тип уходит
        // `text/plain`); части формы и границу видит сквозной сценарий в настоящем браузере.
        sent.push({
          kind: request.headers.get('content-type')?.split(';')[0] ?? '',
          key: request.headers.get('idempotency-key'),
        });
        return data(file('f9', 'uploaded.png', { mime_type: 'image/png' }), 201);
      }),
    );
    const user = userEvent.setup();
    renderApp('/files', LOCAL);
    await screen.findAllByRole('article');

    await user.click(screen.getByRole('button', { name: say.files('upload.open') }));
    const dialog = await screen.findByRole('dialog');
    await user.upload(
      within(dialog).getByLabelText(say.files('upload.file')),
      new File(['x'], 'pic.png', { type: 'image/png' }),
    );
    await user.click(within(dialog).getByRole('button', { name: say.files('upload.submit') }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('пустая установка и пустой отбор говорят разное', async () => {
    stored = [];
    const { unmount } = renderApp('/files', LOCAL);
    expect(await screen.findByText(say.files('empty'))).toBeVisible();
    unmount();

    renderApp('/files?q=nothing', LOCAL);
    expect(await screen.findByText(say.files('emptyFiltered'))).toBeVisible();
  });

  it('русский язык: заголовок и подписи берутся из словаря', async () => {
    renderApp('/files', { ...LOCAL, language: 'ru' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Файлы' })).toBeVisible();
  });
});
