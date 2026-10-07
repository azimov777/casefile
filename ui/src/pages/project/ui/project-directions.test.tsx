import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  directionCard,
  directionDetail,
  failure,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Раздел «Направления» экрана проекта (TRK-557): список, архивные по флажку, заведение,
 * правка и архив; задачи направления — ссылкой в список с отбором `direction`.
 */

const ACTIVE = [
  directionCard('DEMO/promotion', { description: 'Каталоги и день запуска' }),
  directionCard('DEMO/commerce', { title: 'Коммерция' }),
];
const ARCHIVED = directionCard('DEMO/legacy', {
  title: 'Старое',
  archived_at: '2026-09-20T10:00:00Z',
});

let listed: URL[] = [];
let writes: { method: string; path: string; body: unknown }[] = [];

async function remember(request: Request): Promise<void> {
  writes.push({
    method: request.method,
    path: new URL(request.url).pathname,
    body: await request.clone().json(),
  });
}

beforeEach(() => {
  listed = [];
  writes = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail('DEMO'))),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/directions`, ({ request }) => {
      const url = new URL(request.url);
      listed.push(url);
      return collection(
        url.searchParams.get('include_archived') === 'true' ? [...ACTIVE, ARCHIVED] : ACTIVE,
      );
    }),
    http.post(`${API}/api/v1/projects/DEMO/directions`, async ({ request }) => {
      await remember(request);
      return data(directionCard('DEMO/launch', { title: 'Запуск' }), 201);
    }),
    http.get(`${API}/api/v1/projects/DEMO/directions/launch`, () =>
      data(directionDetail('DEMO/launch', { title: 'Запуск' })),
    ),
    http.get(`${API}/api/v1/projects/DEMO/directions/launch/entries`, () => collection([])),
    http.post(`${API}/api/v1/projects/DEMO/directions/:key/archive`, async ({ request }) => {
      await remember(request);
      return data(directionDetail('DEMO/promotion', { archived_at: '2026-10-06T10:00:00Z' }));
    }),
  );
});

function section() {
  return screen.findByRole('region', { name: say.direction('section.title') });
}

describe('раздел «Направления» экрана проекта', () => {
  it('показывает активные направления: название ссылкой на страницу, адрес, описание, задачи', async () => {
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    const row = (await within(region).findByText('DEMO/promotion')).closest('li');
    expect(row).not.toBeNull();
    const card = within(row as HTMLElement);
    expect(card.getByRole('link', { name: /Популяризация/ })).toHaveAttribute(
      'href',
      '/projects/DEMO/directions/promotion',
    );
    expect(card.getByText('Каталоги и день запуска')).toBeInTheDocument();

    const tasks = card.getByRole('link', { name: say.direction('section.tasks') });
    const href = new URL(tasks.getAttribute('href') ?? '', 'http://x');
    expect(href.pathname).toBe('/tasks');
    expect(href.searchParams.get('project')).toBe('DEMO');
    expect(href.searchParams.get('direction')).toBe('DEMO/promotion');

    // Архивные по умолчанию не просятся и не показываются.
    expect(within(region).queryByText('DEMO/legacy')).toBeNull();
    expect(listed[0]?.searchParams.get('include_archived')).toBe('false');
  });

  it('флажок «Показать архивные» просит их у бэкенда и метит словом', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    await within(region).findByText('DEMO/promotion');
    await user.click(
      within(region).getByRole('checkbox', { name: say.direction('section.showArchived') }),
    );

    const row = (await within(region).findByText('DEMO/legacy')).closest('li') as HTMLElement;
    expect(within(row).getByText(say.direction('mark.archived'))).toBeInTheDocument();
    // У архивного — «Восстановить», правки нет.
    expect(
      within(row).getByRole('button', {
        name: say.direction('restore.label', { address: 'DEMO/legacy' }),
      }),
    ).toBeInTheDocument();
    expect(
      within(row).queryByRole('button', {
        name: say.direction('edit.label', { address: 'DEMO/legacy' }),
      }),
    ).toBeNull();
    expect(listed.at(-1)?.searchParams.get('include_archived')).toBe('true');
  });

  it('пустой проект — сказано словами', async () => {
    server.use(http.get(`${API}/api/v1/projects/DEMO/directions`, () => collection([])));
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    expect(await within(region).findByText(say.direction('section.none'))).toBeInTheDocument();
  });

  it('новое направление уходит ключом, названием и описанием и открывается своей страницей', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    await user.click(
      await within(region).findByRole('button', { name: say.direction('create.open') }),
    );
    const dialog = await screen.findByRole('dialog', {
      name: say.direction('create.title', { key: 'DEMO' }),
    });
    await user.type(within(dialog).getByLabelText(say.direction('create.keyLabel')), 'launch');
    await user.type(within(dialog).getByLabelText(say.direction('create.titleLabel')), 'Запуск');
    await user.click(within(dialog).getByRole('button', { name: say.direction('create.submit') }));

    await waitFor(() => expect(address.current).toBe('/projects/DEMO/directions/launch'));
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/directions',
        body: { key: 'launch', title: 'Запуск', description: '' },
      },
    ]);
  });

  it('занятый ключ объяснён у поля ключа, окно остаётся открытым', async () => {
    server.use(
      http.post(`${API}/api/v1/projects/DEMO/directions`, () =>
        failure('direction_key_taken', 409),
      ),
    );
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    await user.click(
      await within(region).findByRole('button', { name: say.direction('create.open') }),
    );
    const dialog = await screen.findByRole('dialog');
    const key = within(dialog).getByLabelText(say.direction('create.keyLabel'));
    await user.type(key, 'promotion');
    await user.type(within(dialog).getByLabelText(say.direction('create.titleLabel')), 'Ещё');
    await user.click(within(dialog).getByRole('button', { name: say.direction('create.submit') }));

    const reason = await within(dialog).findByRole('alert');
    expect(reason).toHaveTextContent(say.errors('direction_key_taken'));
    await waitFor(() => expect(key).toHaveAttribute('aria-invalid', 'true'));
  });

  it('архив направления из строки — только с причиной', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    await user.click(
      await within(region).findByRole('button', {
        name: say.direction('archive.label', { address: 'DEMO/promotion' }),
      }),
    );
    const dialog = await screen.findByRole('alertdialog');
    await user.type(
      within(dialog).getByLabelText(say.direction('archive.reasonLabel')),
      'Запуск прошёл',
    );
    await user.click(within(dialog).getByRole('button', { name: say.direction('archive.submit') }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/directions/promotion/archive',
        body: { reason: 'Запуск прошёл' },
      },
    ]);
  });

  it('архивный проект: список читается, действий с направлениями нет', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(projectDetail('DEMO', { archived_at: '2026-10-01T10:00:00Z' })),
      ),
    );
    renderApp('/projects/DEMO?tab=directions', { language: 'ru' });

    const region = await section();
    await within(region).findByText('DEMO/promotion');
    expect(within(region).queryByRole('button', { name: say.direction('create.open') })).toBeNull();
    expect(
      within(region).queryByRole('button', {
        name: say.direction('archive.label', { address: 'DEMO/promotion' }),
      }),
    ).toBeNull();
    expect(
      within(region).queryByRole('button', {
        name: say.direction('edit.label', { address: 'DEMO/promotion' }),
      }),
    ).toBeNull();
  });
});
