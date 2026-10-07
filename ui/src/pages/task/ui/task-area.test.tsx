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
  failure,
  taskDetails,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import type { TaskArea } from '@/entities/area';
import { setToken } from '@/shared/api';

/*
 * Область в карточке задачи (TRK-557, TRK#16, ч. 4): название рядом с проектом
 * ссылкой на страницу области, адрес в полосе свойств рядом с приоритетом и правка
 * там же — выбор из областей проекта или «без области».
 */

const PROMOTION: TaskArea = {
  address: 'DEMO/promotion',
  title: 'Популяризация',
  description: 'Каталоги и день запуска',
  archived_at: null,
};

let writes: { method: string; path: string; body: unknown }[] = [];

function serve(area: TaskArea | null, status: 'in_progress' | 'done' = 'in_progress') {
  server.use(
    http.get(`${API}/api/v1/tasks/DEMO-7`, () =>
      data(taskPackage('DEMO-7', { task: taskDetails('DEMO-7', { area, status }) })),
    ),
  );
}

beforeEach(() => {
  writes = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks/DEMO-7/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/areas`, () =>
      collection([
        areaCard('DEMO/promotion', { description: 'Каталоги и день запуска' }),
        areaCard('DEMO/commerce', { title: 'Коммерция' }),
      ]),
    ),
    http.patch(`${API}/api/v1/tasks/DEMO-7`, async ({ request }) => {
      writes.push({
        method: request.method,
        path: new URL(request.url).pathname,
        body: await request.clone().json(),
      });
      return data(taskDetails('DEMO-7'));
    }),
  );
});

/** Ячейка полосы свойств по её подписи. */
function cell(label: string): HTMLElement {
  return screen.getByText(label, { selector: 'dt' }).parentElement as HTMLElement;
}

describe('область в карточке задачи', () => {
  it('название стоит рядом с проектом ссылкой на страницу области, адрес — в полосе', async () => {
    serve(PROMOTION);
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    const link = screen.getByRole('link', { name: /Популяризация/ });
    expect(link).toHaveAttribute('href', '/projects/DEMO/areas/promotion');
    expect(link).toHaveTextContent(say.area('mark.label'));

    const area = cell(say.task('header.area'));
    expect(within(area).getByText('DEMO/promotion')).toBeInTheDocument();
  });

  it('без области ячейка говорит это словами, ссылки рядом с проектом нет', async () => {
    serve(null);
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    expect(
      within(cell(say.task('header.area'))).getByText(say.task('header.noArea')),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Популяризация/ })).toBeNull();
  });

  it('правка: выбор другой области уходит `PATCH` с одним полем `area`', async () => {
    serve(PROMOTION);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', { name: say.area('task.label', { key: 'DEMO-7' }) }),
    );
    const dialog = await screen.findByRole('dialog', {
      name: say.area('task.title', { key: 'DEMO-7' }),
    });
    // Окно открывается на нынешнем значении.
    expect(await within(dialog).findByRole('radio', { name: /Популяризация/ })).toBeChecked();
    await user.click(within(dialog).getByRole('radio', { name: /Коммерция/ }));
    await user.click(within(dialog).getByRole('button', { name: say.area('task.submit') }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([
      { method: 'PATCH', path: '/api/v1/tasks/DEMO-7', body: { area: 'DEMO/commerce' } },
    ]);
  });

  it('«без области» снимает её: `area: null`', async () => {
    serve(PROMOTION);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', { name: say.area('task.label', { key: 'DEMO-7' }) }),
    );
    const dialog = await screen.findByRole('dialog');
    await user.click(
      await within(dialog).findByRole('radio', { name: new RegExp(say.area('task.none')) }),
    );
    await user.click(within(dialog).getByRole('button', { name: say.area('task.submit') }));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.body).toEqual({ area: null });
  });

  it('неизменённый выбор закрывает окно без запроса; отказ бэкенда — словами', async () => {
    serve(PROMOTION);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    const open = await screen.findByRole('button', {
      name: say.area('task.label', { key: 'DEMO-7' }),
    });
    await user.click(open);
    let dialog = await screen.findByRole('dialog');
    await within(dialog).findByRole('radio', { name: /Популяризация/ });
    await user.click(within(dialog).getByRole('button', { name: say.area('task.submit') }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([]);

    server.use(http.patch(`${API}/api/v1/tasks/DEMO-7`, () => failure('area_archived', 409)));
    await user.click(open);
    dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('radio', { name: /Коммерция/ }));
    await user.click(within(dialog).getByRole('button', { name: say.area('task.submit') }));
    expect(
      await within(dialog).findByText(say.errors('area_archived'), { exact: false }),
    ).toBeInTheDocument();
  });

  it('у закрытой задачи правки нет: поле не меняется (`task_closed`)', async () => {
    serve(PROMOTION, 'done');
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    expect(within(cell(say.task('header.area'))).getByText('DEMO/promotion')).toBeVisible();
    expect(
      screen.queryByRole('button', { name: say.area('task.label', { key: 'DEMO-7' }) }),
    ).toBeNull();
  });

  it('нынешняя архивная область стоит в окне с пометкой и подсказкой', async () => {
    serve({
      ...PROMOTION,
      address: 'DEMO/legacy',
      title: 'Старое',
      archived_at: '2026-09-01T10:00:00Z',
    });
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    // У архивной области в строке «где» — пометка словом.
    const link = await screen.findByRole('link', { name: /Старое/ });
    expect(link).toHaveTextContent(say.area('mark.archived'));

    await user.click(
      screen.getByRole('button', { name: say.area('task.label', { key: 'DEMO-7' }) }),
    );
    const dialog = await screen.findByRole('dialog');
    const current = await within(dialog).findByRole('radio', {
      name: new RegExp(
        say.area('task.archivedOption', { title: 'Старое' }).replace(/[()]/g, '\\$&'),
      ),
    });
    expect(current).toBeChecked();
    expect(within(dialog).getByText(say.area('task.archivedHint'))).toBeInTheDocument();
  });
});
