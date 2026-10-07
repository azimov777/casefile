import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  failure,
  projectDetail,
  task,
  taskDetails,
  taskListing,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Момент «можно взять с …» в карточке задачи (TRK-593, TRK#47): строка в поясе браузера,
 * значок по признаку сервера, ввод по часам устройства и отказ бэкенда словами.
 * Пояс — Берлин, как у владельца: осенью +02:00.
 */

const was = process.env.TZ;
beforeAll(() => {
  process.env.TZ = 'Europe/Berlin';
});
afterAll(() => {
  if (was === undefined) delete process.env.TZ;
  else process.env.TZ = was;
});

let writes: { method: string; path: string; body: unknown }[] = [];

function serve(
  notBefore: string | null,
  deferred: boolean,
  status: 'in_progress' | 'open' | 'done' = 'open',
) {
  server.use(
    http.get(`${API}/api/v1/tasks/DEMO-7`, () => {
      const pack = taskPackage('DEMO-7', {
        task: taskDetails('DEMO-7', { status, not_before: notBefore }),
      });
      return data({ ...pack, features: { ...pack.features, blocked: false, deferred } });
    }),
  );
}

beforeEach(() => {
  writes = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks/DEMO-7/entries`, () => collection([])),
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

function cell(label: string): HTMLElement {
  return screen.getByText(label, { selector: 'dt' }).parentElement as HTMLElement;
}

describe('момент «можно взять с …» в карточке задачи', () => {
  it('ответ 07:00Z показан как 12 октября, 09:00 в поясе браузера, со значком отложенной', async () => {
    serve('2026-10-12T07:00:00Z', true);
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    const notBefore = cell(say.task('header.notBefore'));
    expect(notBefore).toHaveTextContent(/12 октября.{1,3}09:00/);
    expect(within(notBefore).getByText(/отложена/)).toBeInTheDocument();
    expect(
      within(notBefore).getByRole('button', {
        name: say.task('notBefore.clearLabel', { key: 'DEMO-7' }),
      }),
    ).toBeInTheDocument();
  });

  it('тот же момент при deferred: false значка не даёт, строка остаётся', async () => {
    serve('2026-10-12T07:00:00Z', false);
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    const notBefore = cell(say.task('header.notBefore'));
    expect(notBefore).toHaveTextContent(/12 октября.{1,3}09:00/);
    expect(notBefore.querySelector('[data-mark="feature"]')).toBeNull();
    expect(screen.queryByText(/отложена/)).toBeNull();
  });

  it('«Снять» шлёт `not_before: null`', async () => {
    serve('2026-10-12T07:00:00Z', true);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await user.click(
      await screen.findByRole('button', {
        name: say.task('notBefore.clearLabel', { key: 'DEMO-7' }),
      }),
    );

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.body).toEqual({ not_before: null });
  });

  it('«Отложить…»: ввод 2026-10-12 09:00 уходит как 2026-10-12T09:00:00+02:00', async () => {
    serve(null, false);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await user.click(
      await screen.findByRole('button', {
        name: say.task('notBefore.deferLabel', { key: 'DEMO-7' }),
      }),
    );
    const dialog = await screen.findByRole('dialog');
    const input = within(dialog).getByLabelText(say.task('notBefore.inputLabel'));
    await user.type(input, '2026-10-12T09:00');
    await user.click(within(dialog).getByRole('button', { name: say.task('notBefore.submit') }));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({
      method: 'PATCH',
      path: '/api/v1/tasks/DEMO-7',
      body: { not_before: '2026-10-12T09:00:00+02:00' },
    });
  });

  it('«Изменить» открывает поле с нынешним моментом в местном времени', async () => {
    serve('2026-10-12T07:00:00Z', true);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await user.click(
      await screen.findByRole('button', {
        name: say.task('notBefore.changeLabel', { key: 'DEMO-7' }),
      }),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText(say.task('notBefore.inputLabel'))).toHaveValue(
      '2026-10-12T09:00',
    );
  });

  it('пустое поле не уходит запросом и просит дату словами', async () => {
    serve(null, false);
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await user.click(
      await screen.findByRole('button', {
        name: say.task('notBefore.deferLabel', { key: 'DEMO-7' }),
      }),
    );
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: say.task('notBefore.submit') }));

    expect(await within(dialog).findByText(say.task('notBefore.empty'))).toBeInTheDocument();
    expect(writes).toHaveLength(0);
  });

  it('отказ сервера показан его текстом в окне', async () => {
    serve(null, false);
    server.use(http.patch(`${API}/api/v1/tasks/DEMO-7`, () => failure('task_closed', 409)));
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await user.click(
      await screen.findByRole('button', {
        name: say.task('notBefore.deferLabel', { key: 'DEMO-7' }),
      }),
    );
    const dialog = await screen.findByRole('dialog');
    await user.type(
      within(dialog).getByLabelText(say.task('notBefore.inputLabel')),
      '2026-10-12T09:00',
    );
    await user.click(within(dialog).getByRole('button', { name: say.task('notBefore.submit') }));

    expect(
      await within(dialog).findByText(say.errors('task_closed'), { exact: false }),
    ).toBeInTheDocument();
  });

  it('у закрытой задачи только строка, без кнопок', async () => {
    serve('2026-10-12T07:00:00Z', false, 'done');
    renderApp('/tasks/DEMO-7', { language: 'ru' });
    await screen.findByRole('heading', { name: /DEMO-7/ });

    expect(cell(say.task('header.notBefore'))).toHaveTextContent(/12 октября.{1,3}09:00/);
    expect(
      screen.queryByRole('button', { name: say.task('notBefore.clearLabel', { key: 'DEMO-7' }) }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: say.task('notBefore.changeLabel', { key: 'DEMO-7' }) }),
    ).toBeNull();
  });
});

describe('значок отложенной задачи в списке и на доске', () => {
  function serveList(deferred: boolean) {
    const base = task('DEMO-9');
    const row = {
      ...base,
      not_before: '2026-10-12T07:00:00Z',
      features: { ...base.features!, deferred },
    };
    server.use(
      http.get(`${API}/api/v1/projects/:key`, ({ params }) =>
        data(projectDetail(String(params.key))),
      ),
      http.get(`${API}/api/v1/tasks`, ({ request }) => taskListing(new URL(request.url), [row])),
    );
  }

  for (const view of ['list', 'board']) {
    it(`${view}: значок стоит по признаку сервера и называет момент`, async () => {
      serveList(true);
      renderApp(`/tasks?project=DEMO&view=${view}`, { language: 'ru' });
      expect(
        (await screen.findAllByText(/отложена: можно взять в работу с 12 окт\.?.{1,3}09:00/))
          .length,
      ).toBeGreaterThan(0);
    });

    it(`${view}: без признака сервера значка нет, каким бы ни был момент`, async () => {
      serveList(false);
      renderApp(`/tasks?project=DEMO&view=${view}`, { language: 'ru' });
      await screen.findAllByText('Задача DEMO-9');
      expect(screen.queryByText(/отложена/)).toBeNull();
    });
  }
});
