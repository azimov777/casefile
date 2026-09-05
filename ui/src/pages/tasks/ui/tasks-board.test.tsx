import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, task } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { TASK_STATUSES } from '@/entities/task';
import { setToken } from '@/shared/api';

/** Запросы списка за прогон: доска обязана обходиться одним. */
let seen: URL[] = [];

beforeEach(() => {
  seen = [];
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
  setToken('trk_test');
});

/**
 * Выдача, разложенная по статусам: по одной задаче на каждое значение перечисления
 * контракта. Набор строится из `TASK_STATUSES`, а не перечисляется здесь: тест доски
 * не должен знать список статусов лучше, чем сгенерированный клиент.
 */
function tasksForEveryStatus() {
  return TASK_STATUSES.map((status, index) => task(`DEMO-${index + 1}`, { status }));
}

function listing(items = tasksForEveryStatus(), meta = {}) {
  return http.get(`${API}/api/v1/tasks`, ({ request }) => {
    const url = new URL(request.url);
    seen.push(url);
    return collection(items, meta);
  });
}

function column(status: string) {
  return screen.getByRole('region', { name: status });
}

describe('доска', () => {
  it('раскладывает задачи по столбцу на каждое значение статуса из контракта', async () => {
    server.use(listing());

    renderApp('/tasks?queue=DEMO&view=board');

    await screen.findByRole('region', { name: TASK_STATUSES[0] as string });

    for (const [index, status] of TASK_STATUSES.entries()) {
      const key = `DEMO-${index + 1}`;
      const section = column(status);
      // Свёрнутый столбец карточек не показывает: разворачиваем и проверяем содержимое.
      if (within(section).queryByText(key) === null) {
        await userEvent.setup().click(within(section).getByRole('button'));
      }
      expect(within(section).getByRole('link', { name: key })).toBeInTheDocument();
    }

    // Один запрос списка на отрисовку доски.
    expect(seen).toHaveLength(1);
  });

  it('закрытые и отменённые свёрнуты и показывают число, клик раскрывает', async () => {
    server.use(listing());
    renderApp('/tasks?queue=DEMO&view=board');

    await screen.findByRole('region', { name: 'done' });
    const done = column('done');

    const toggle = within(done).getByRole('button');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveTextContent('1');
    expect(within(done).queryByRole('link')).not.toBeInTheDocument();

    await userEvent.setup().click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(within(done).getByRole('link')).toBeInTheDocument();
  });

  it('статус в отборе на доску не уходит: столбцы и есть отбор по статусу', async () => {
    server.use(listing());

    renderApp('/tasks?queue=DEMO&view=board&status=open&assignee=owner&sort=key');
    await screen.findByRole('region', { name: 'open' });

    const request = seen[0] as URL;
    expect(request.searchParams.getAll('status')).toEqual([]);
    // Исполнитель — общий фильтр, он действует и на доске.
    expect(request.searchParams.getAll('assignee')).toEqual(['owner']);
    // Порядок внутри столбца задан доской: свежие сверху.
    expect(request.searchParams.getAll('sort')).toEqual(['-updated_at']);
  });

  it('переключение в таблицу сохраняет отбор и меняет адрес', async () => {
    server.use(listing());
    renderApp('/tasks?queue=DEMO&view=board&assignee=owner');
    await screen.findByRole('region', { name: 'open' });

    await userEvent.setup().click(screen.getByRole('radio', { name: 'Таблица' }));

    expect(await screen.findByRole('table')).toBeInTheDocument();
    const request = seen.at(-1) as URL;
    expect(request.searchParams.getAll('assignee')).toEqual(['owner']);
    expect(screen.getByLabelText('Исполнитель')).toHaveValue('owner');
  });

  it('недочитанная выдача помечает столбцы «из ?» и дочитывается кнопкой', async () => {
    let page = 0;
    server.use(
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        page += 1;
        return page === 1
          ? collection([task('DEMO-1', { status: 'open' })], {
              has_more: true,
              next_cursor: 'next',
            })
          : collection([task('DEMO-2', { status: 'open' })]);
      }),
    );

    renderApp('/tasks?queue=DEMO&view=board');

    const open = await screen.findByRole('region', { name: 'open' });
    expect(within(open).getByRole('button')).toHaveTextContent('1 из ?');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Ещё' }));

    expect(await within(open).findByRole('link', { name: 'DEMO-2' })).toBeInTheDocument();
    expect(within(open).getByRole('button')).toHaveTextContent('2');
    expect(seen).toHaveLength(2);
    expect((seen[1] as URL).searchParams.get('cursor')).toBe('next');
  });
});
