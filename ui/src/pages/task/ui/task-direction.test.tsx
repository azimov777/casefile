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
  failure,
  taskDetails,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import type { TaskDirection } from '@/entities/direction';
import { setToken } from '@/shared/api';

/*
 * Направление в карточке задачи (TRK-557, TRK#16, ч. 4): название рядом с проектом
 * ссылкой на страницу направления, адрес в полосе свойств рядом с приоритетом и правка
 * там же — выбор из направлений проекта или «без направления».
 */

const PROMOTION: TaskDirection = {
  address: 'DEMO/promotion',
  title: 'Популяризация',
  description: 'Каталоги и день запуска',
  archived_at: null,
};

let writes: { method: string; path: string; body: unknown }[] = [];

function serve(direction: TaskDirection | null, status: 'in_progress' | 'done' = 'in_progress') {
  server.use(
    http.get(`${API}/api/v1/tasks/DEMO-7`, () =>
      data(taskPackage('DEMO-7', { task: taskDetails('DEMO-7', { direction, status }) })),
    ),
  );
}

beforeEach(() => {
  writes = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks/DEMO-7/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/directions`, () =>
      collection([
        directionCard('DEMO/promotion', { description: 'Каталоги и день запуска' }),
        directionCard('DEMO/commerce', { title: 'Коммерция' }),
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

describe('направление в карточке задачи', () => {
  it('название стоит рядом с проектом ссылкой на страницу направления, адрес — в полосе', async () => {
    serve(PROMOTION);
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    const link = screen.getByRole('link', { name: /Популяризация/ });
    expect(link).toHaveAttribute('href', '/projects/DEMO/directions/promotion');
    expect(link).toHaveTextContent(say.direction('mark.label'));

    const direction = cell(say.task('header.direction'));
    expect(within(direction).getByText('DEMO/promotion')).toBeInTheDocument();
  });

  it('без направления ячейка говорит это словами, ссылки рядом с проектом нет', async () => {
    serve(null);
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    expect(
      within(cell(say.task('header.direction'))).getByText(say.task('header.noDirection')),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Популяризация/ })).toBeNull();
  });

  it('правка: выбор другого направления уходит `PATCH` с одним полем `direction`', async () => {
    serve(PROMOTION);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', { name: say.direction('task.label', { key: 'DEMO-7' }) }),
    );
    const dialog = await screen.findByRole('dialog', {
      name: say.direction('task.title', { key: 'DEMO-7' }),
    });
    // Окно открывается на нынешнем значении.
    expect(await within(dialog).findByRole('radio', { name: /Популяризация/ })).toBeChecked();
    await user.click(within(dialog).getByRole('radio', { name: /Коммерция/ }));
    await user.click(within(dialog).getByRole('button', { name: say.direction('task.submit') }));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([
      { method: 'PATCH', path: '/api/v1/tasks/DEMO-7', body: { direction: 'DEMO/commerce' } },
    ]);
  });

  it('«без направления» снимает его: `direction: null`', async () => {
    serve(PROMOTION);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    await user.click(
      await screen.findByRole('button', { name: say.direction('task.label', { key: 'DEMO-7' }) }),
    );
    const dialog = await screen.findByRole('dialog');
    await user.click(
      await within(dialog).findByRole('radio', { name: new RegExp(say.direction('task.none')) }),
    );
    await user.click(within(dialog).getByRole('button', { name: say.direction('task.submit') }));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.body).toEqual({ direction: null });
  });

  it('неизменённый выбор закрывает окно без запроса; отказ бэкенда — словами', async () => {
    serve(PROMOTION);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    const open = await screen.findByRole('button', {
      name: say.direction('task.label', { key: 'DEMO-7' }),
    });
    await user.click(open);
    let dialog = await screen.findByRole('dialog');
    await within(dialog).findByRole('radio', { name: /Популяризация/ });
    await user.click(within(dialog).getByRole('button', { name: say.direction('task.submit') }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(writes).toEqual([]);

    server.use(http.patch(`${API}/api/v1/tasks/DEMO-7`, () => failure('direction_archived', 409)));
    await user.click(open);
    dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('radio', { name: /Коммерция/ }));
    await user.click(within(dialog).getByRole('button', { name: say.direction('task.submit') }));
    expect(
      await within(dialog).findByText(say.errors('direction_archived'), { exact: false }),
    ).toBeInTheDocument();
  });

  it('у закрытой задачи правки нет: поле не меняется (`task_closed`)', async () => {
    serve(PROMOTION, 'done');
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    expect(within(cell(say.task('header.direction'))).getByText('DEMO/promotion')).toBeVisible();
    expect(
      screen.queryByRole('button', { name: say.direction('task.label', { key: 'DEMO-7' }) }),
    ).toBeNull();
  });

  it('нынешнее архивное направление стоит в окне с пометкой и подсказкой', async () => {
    serve({
      ...PROMOTION,
      address: 'DEMO/legacy',
      title: 'Старое',
      archived_at: '2026-09-01T10:00:00Z',
    });
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });

    // У архивного направления в строке «где» — пометка словом.
    const link = await screen.findByRole('link', { name: /Старое/ });
    expect(link).toHaveTextContent(say.direction('mark.archived'));

    await user.click(
      screen.getByRole('button', { name: say.direction('task.label', { key: 'DEMO-7' }) }),
    );
    const dialog = await screen.findByRole('dialog');
    const current = await within(dialog).findByRole('radio', {
      name: new RegExp(
        say.direction('task.archivedOption', { title: 'Старое' }).replace(/[()]/g, '\\$&'),
      ),
    });
    expect(current).toBeChecked();
    expect(within(dialog).getByText(say.direction('task.archivedHint'))).toBeInTheDocument();
  });
});
