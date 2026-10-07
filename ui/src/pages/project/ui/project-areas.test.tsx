import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  areaCard,
  areaDetail,
  failure,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Раздел «Области» экрана проекта (TRK-557): список, архивные по флажку, заведение,
 * правка и архив; задачи области — ссылкой в список с отбором `area`.
 */

const ACTIVE = [
  areaCard('DEMO/promotion', { description: 'Каталоги и день запуска' }),
  areaCard('DEMO/commerce', { title: 'Коммерция' }),
];
const ARCHIVED = areaCard('DEMO/legacy', {
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
    // Счётчики шапки (TRK-619) читают список задач; их числа здесь не проверяются.
    http.get(`${API}/api/v1/tasks`, () => collection([], { total: 0 })),
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail('DEMO'))),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/areas`, ({ request }) => {
      const url = new URL(request.url);
      listed.push(url);
      return collection(
        url.searchParams.get('include_archived') === 'true' ? [...ACTIVE, ARCHIVED] : ACTIVE,
      );
    }),
    http.post(`${API}/api/v1/projects/DEMO/areas`, async ({ request }) => {
      await remember(request);
      return data(areaCard('DEMO/launch', { title: 'Запуск' }), 201);
    }),
    http.get(`${API}/api/v1/projects/DEMO/areas/launch`, () =>
      data(areaDetail('DEMO/launch', { title: 'Запуск' })),
    ),
    http.get(`${API}/api/v1/projects/DEMO/areas/launch/entries`, () => collection([])),
    http.post(`${API}/api/v1/projects/DEMO/areas/:key/archive`, async ({ request }) => {
      await remember(request);
      return data(areaDetail('DEMO/promotion', { archived_at: '2026-10-06T10:00:00Z' }));
    }),
  );
});

function section() {
  return screen.findByRole('region', { name: say.area('section.title') });
}

describe('раздел «Области» экрана проекта', () => {
  it('показывает активные области: название ссылкой на страницу, адрес, описание, задачи', async () => {
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    const row = (await within(region).findByText('DEMO/promotion')).closest('li');
    expect(row).not.toBeNull();
    const card = within(row as HTMLElement);
    expect(card.getByRole('link', { name: /Популяризация/ })).toHaveAttribute(
      'href',
      '/projects/DEMO/areas/promotion',
    );
    expect(card.getByText('Каталоги и день запуска')).toBeInTheDocument();

    const tasks = card.getByRole('link', { name: say.area('section.tasks') });
    const href = new URL(tasks.getAttribute('href') ?? '', 'http://x');
    expect(href.pathname).toBe('/tasks');
    expect(href.searchParams.get('project')).toBe('DEMO');
    expect(href.searchParams.get('area')).toBe('DEMO/promotion');

    // Архивные по умолчанию не просятся и не показываются.
    expect(within(region).queryByText('DEMO/legacy')).toBeNull();
    expect(listed[0]?.searchParams.get('include_archived')).toBe('false');
  });

  it('флажок «Показать архивные» просит их у бэкенда и метит словом', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    await within(region).findByText('DEMO/promotion');
    await user.click(
      within(region).getByRole('checkbox', { name: say.area('section.showArchived') }),
    );

    const row = (await within(region).findByText('DEMO/legacy')).closest('li') as HTMLElement;
    expect(within(row).getByText(say.area('mark.archived'))).toBeInTheDocument();
    // У архивного — «Восстановить», правки нет.
    expect(
      within(row).getByRole('button', {
        name: say.area('restore.label', { address: 'DEMO/legacy' }),
      }),
    ).toBeInTheDocument();
    expect(
      within(row).queryByRole('button', {
        name: say.area('edit.label', { address: 'DEMO/legacy' }),
      }),
    ).toBeNull();
    expect(listed.at(-1)?.searchParams.get('include_archived')).toBe('true');
  });

  it('пустой проект — сказано словами', async () => {
    server.use(http.get(`${API}/api/v1/projects/DEMO/areas`, () => collection([])));
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    expect(await within(region).findByText(say.area('section.none'))).toBeInTheDocument();
  });

  it('новая область уходит ключом, названием и описанием и открывается своей страницей', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    await user.click(await within(region).findByRole('button', { name: say.area('create.open') }));
    const dialog = await screen.findByRole('dialog', {
      name: say.area('create.title', { key: 'DEMO' }),
    });
    await user.type(within(dialog).getByLabelText(say.area('create.keyLabel')), 'launch');
    await user.type(within(dialog).getByLabelText(say.area('create.titleLabel')), 'Запуск');
    await user.click(within(dialog).getByRole('button', { name: say.area('create.submit') }));

    await waitFor(() => expect(address.current).toBe('/projects/DEMO/areas/launch'));
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/areas',
        body: { key: 'launch', title: 'Запуск', description: '' },
      },
    ]);
  });

  it('занятый ключ объяснён у поля ключа, окно остаётся открытым', async () => {
    server.use(
      http.post(`${API}/api/v1/projects/DEMO/areas`, () => failure('area_key_taken', 409)),
    );
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    await user.click(await within(region).findByRole('button', { name: say.area('create.open') }));
    const dialog = await screen.findByRole('dialog');
    const key = within(dialog).getByLabelText(say.area('create.keyLabel'));
    await user.type(key, 'promotion');
    await user.type(within(dialog).getByLabelText(say.area('create.titleLabel')), 'Ещё');
    await user.click(within(dialog).getByRole('button', { name: say.area('create.submit') }));

    const reason = await within(dialog).findByRole('alert');
    expect(reason).toHaveTextContent(say.errors('area_key_taken'));
    await waitFor(() => expect(key).toHaveAttribute('aria-invalid', 'true'));
  });

  it('архив области из строки — только с причиной', async () => {
    const user = userEvent.setup();
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    await user.click(
      await within(region).findByRole('button', {
        name: say.area('archive.label', { address: 'DEMO/promotion' }),
      }),
    );
    const dialog = await screen.findByRole('alertdialog');
    await user.type(
      within(dialog).getByLabelText(say.area('archive.reasonLabel')),
      'Запуск прошёл',
    );
    await user.click(within(dialog).getByRole('button', { name: say.area('archive.submit') }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(writes).toEqual([
      {
        method: 'POST',
        path: '/api/v1/projects/DEMO/areas/promotion/archive',
        body: { reason: 'Запуск прошёл' },
      },
    ]);
  });

  it('архивный проект: список читается, действий с областями нет', async () => {
    server.use(
      http.get(`${API}/api/v1/projects/DEMO`, () =>
        data(projectDetail('DEMO', { archived_at: '2026-10-01T10:00:00Z' })),
      ),
    );
    renderApp('/projects/DEMO?tab=areas', { language: 'ru' });

    const region = await section();
    await within(region).findByText('DEMO/promotion');
    expect(within(region).queryByRole('button', { name: say.area('create.open') })).toBeNull();
    expect(
      within(region).queryByRole('button', {
        name: say.area('archive.label', { address: 'DEMO/promotion' }),
      }),
    ).toBeNull();
    expect(
      within(region).queryByRole('button', {
        name: say.area('edit.label', { address: 'DEMO/promotion' }),
      }),
    ).toBeNull();
  });
});
