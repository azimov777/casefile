import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  projectDetail,
  task,
  taskPackage,
  taskPage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { setToken } from '@/shared/api';

/**
 * Проход по экранам (TRK-364): те же пояснения по порядку, номер шага — параметр `walk`.
 * Приложение поднимается целиком: проход пересекает страницы, поэтому тест лежит в `app`.
 */

type Project = { key: string; archived?: boolean };

function account(hints: { hidden_all: boolean; hidden: string[] }) {
  return {
    id: '55555555-5555-5555-5555-555555555555',
    email: 'owner@localhost',
    participant: 'owner',
    is_admin: true,
    has_password: false,
    disabled_at: null,
    onboarding: { status: 'pending' as const, hints },
    created_by: { kind: 'tracker' as const, signature: null },
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
  };
}

/** Записанные `PATCH`: проход не вправе прислать ни одного. */
const patches: string[] = [];

/**
 * Установка: проекты (как отдаёт `bootstrap` — активные), по задаче в проекте (`tasks`,
 * ключ проекта → ключ первой задачи) и состояние пояснений; `withAccount: false` —
 * человек без учётной записи.
 */
function installation({
  projects,
  tasks = {},
  hints = { hidden_all: false, hidden: [] },
  withAccount = true,
}: {
  projects: Project[];
  tasks?: Record<string, string>;
  hints?: { hidden_all: boolean; hidden: string[] };
  withAccount?: boolean;
}) {
  const base = bootstrap();
  const template = base.projects[0]!;
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () =>
      data(
        bootstrap({
          account: withAccount ? account(hints) : null,
          projects: projects.map((item) => ({
            ...template,
            key: item.key,
            archived_at: item.archived === true ? '2026-09-20T10:00:00Z' : null,
          })),
        }),
      ),
    ),
    http.get(`${API}/api/v1/tasks`, ({ request }) => {
      const project = new URL(request.url).searchParams.get('project');
      const key = project === null ? undefined : tasks[project];
      return taskPage(key === undefined ? [] : [task(key)]);
    }),
    http.get(`${API}/api/v1/tasks/:key`, ({ params }) => {
      const key = String(params.key);
      return data(taskPackage(key));
    }),
    http.get(`${API}/api/v1/tasks/:key/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/:key`, ({ params }) =>
      data(projectDetail(String(params.key))),
    ),
    http.get(`${API}/api/v1/projects/:key/entries`, () => collection([])),
    http.get(`${API}/api/v1/questions`, () => collection([])),
    http.get(`${API}/api/v1/tokens`, () => collection([])),
    http.get(`${API}/api/v1/participants`, () => collection([])),
    http.get(`${API}/api/v1/installation`, () => data({ mcp_url: 'http://localhost:8100/mcp' })),
    http.patch(`${API}/api/v1/accounts/:id/onboarding`, ({ request }) => {
      patches.push(request.url);
      return data(account(hints).onboarding);
    }),
  );
}

const main = () => within(screen.getByRole('main'));

/** Полоса прохода со счётчиком «Step N of total» в области содержимого. */
async function counter(n: number, total: number) {
  await waitFor(() => expect(main().getByText(`Step ${n} of ${total}`)).toBeInTheDocument());
}

async function next() {
  await userEvent.click(main().getByRole('link', { name: 'Next' }));
}

beforeEach(() => {
  setToken('trk_test');
  patches.length = 0;
});

describe('проход по экранам: какие шаги есть', () => {
  it('без проектов — три шага: Входящая, подключение, доступы', async () => {
    installation({ projects: [] });
    renderApp('/start');
    await userEvent.click(await screen.findByRole('link', { name: 'Walk through the screens' }));

    await counter(1, 3);
    expect(address.current).toBe('/questions?walk=1');
    await next();
    await counter(2, 3);
    expect(address.current).toBe('/connect?walk=2');
    await next();
    await counter(3, 3);
    expect(address.current).toBe('/access?walk=3');
    await next();
    await screen.findByRole('heading', { level: 1, name: 'Start' });
    expect(address.current).toBe('/start');
    expect(patches).toEqual([]);
  });

  it('проект без задач — шесть шагов: список, доска, проект и три остальных', async () => {
    installation({ projects: [{ key: 'DEMO' }] });
    renderApp('/start');
    await userEvent.click(await screen.findByRole('link', { name: 'Walk through the screens' }));

    const paths = ['/tasks?project=DEMO&walk=1'];
    await counter(1, 6);
    expect(address.current).toBe(paths[0]);
    const seen: string[] = [];
    for (let n = 2; n <= 6; n += 1) {
      await next();
      await counter(n, 6);
      seen.push(address.current);
    }
    expect(seen).toEqual([
      '/tasks?project=DEMO&view=board&walk=2',
      '/projects/DEMO?walk=3',
      '/questions?walk=4',
      '/connect?walk=5',
      '/access?walk=6',
    ]);
    expect(patches).toEqual([]);
  });

  it('без START, но с другим проектом и задачей — восемь шагов с их ключами', async () => {
    installation({ projects: [{ key: 'OPS' }, { key: 'DEMO' }], tasks: { OPS: 'OPS-3' } });
    renderApp('/start');
    await userEvent.click(await screen.findByRole('link', { name: 'Walk through the screens' }));

    await counter(1, 8);
    const seen = [address.current];
    for (let n = 2; n <= 8; n += 1) {
      await next();
      await counter(n, 8);
      seen.push(address.current);
    }
    expect(seen).toEqual([
      '/tasks?project=OPS&walk=1',
      '/tasks?project=OPS&view=board&walk=2',
      '/tasks/OPS-3?walk=3',
      '/tasks/OPS-3/case?walk=4',
      '/projects/OPS?walk=5',
      '/questions?walk=6',
      '/connect?walk=7',
      '/access?walk=8',
    ]);
    expect(patches).toEqual([]);
  });

  it('START берётся раньше первого проекта, а архивный START не берётся', async () => {
    installation({
      projects: [{ key: 'DEMO' }, { key: 'START' }],
      tasks: { START: 'START-1', DEMO: 'DEMO-1' },
    });
    renderApp('/start');
    await userEvent.click(await screen.findByRole('link', { name: 'Walk through the screens' }));
    await counter(1, 8);
    expect(address.current).toBe('/tasks?project=START&walk=1');
  });

  it('архивный START пропущен: проход идёт по первому активному проекту', async () => {
    installation({
      projects: [{ key: 'START', archived: true }, { key: 'DEMO' }],
      tasks: { DEMO: 'DEMO-1' },
    });
    renderApp('/start');
    await userEvent.click(await screen.findByRole('link', { name: 'Walk through the screens' }));
    await counter(1, 8);
    expect(address.current).toBe('/tasks?project=DEMO&walk=1');
  });
});

describe('проход по экранам: ход', () => {
  it('«Назад» ведёт на прежний шаг, на первом шаге «Назад» нет', async () => {
    installation({ projects: [] });
    renderApp('/questions?walk=1');
    await counter(1, 3);
    expect(main().queryByRole('link', { name: 'Back' })).not.toBeInTheDocument();
    await next();
    await counter(2, 3);
    await userEvent.click(main().getByRole('link', { name: 'Back' }));
    await counter(1, 3);
    expect(address.current).toBe('/questions?walk=1');
  });

  it('«Закончить» ведёт на /start и ничего не пишет на сервер', async () => {
    installation({ projects: [] });
    renderApp('/connect?walk=2');
    await counter(2, 3);
    await userEvent.click(main().getByRole('link', { name: 'Finish' }));
    await screen.findByRole('heading', { level: 1, name: 'Start' });
    expect(address.current).toBe('/start');
    expect(patches).toEqual([]);
  });

  it('при hidden_all пояснение шага показано, а кнопок скрытия на шаге нет', async () => {
    installation({ projects: [], hints: { hidden_all: true, hidden: [] } });
    renderApp('/access?walk=3');
    await counter(3, 3);
    expect(main().getByText(/All tokens of the installation are here/)).toBeInTheDocument();
    expect(main().queryByRole('button', { name: 'Hide all hints' })).not.toBeInTheDocument();
    expect(main().queryByRole('button', { name: 'Close this hint' })).not.toBeInTheDocument();
    expect(patches).toEqual([]);
  });

  it('без параметра walk скрытое пояснение не показано и полосы нет', async () => {
    installation({ projects: [], hints: { hidden_all: true, hidden: [] } });
    renderApp('/access');
    await screen.findByRole('heading', { level: 1, name: 'Access' });
    expect(main().queryByText(/Step \d+ of/)).not.toBeInTheDocument();
    expect(main().queryByText(/All tokens of the installation are here/)).not.toBeInTheDocument();
  });

  it('неверный номер шага полосу не рисует', async () => {
    installation({ projects: [] });
    renderApp('/access?walk=9');
    await screen.findByRole('heading', { level: 1, name: 'Access' });
    expect(main().queryByText(/Step \d+ of/)).not.toBeInTheDocument();
  });
});

describe('проход по экранам: человек без учётной записи', () => {
  it('кнопки «Walk through the screens» на /start нет', async () => {
    installation({ projects: [], withAccount: false });
    renderApp('/start');
    await screen.findByRole('heading', { level: 1, name: 'Start' });
    await waitFor(() => expect(screen.queryByText(/Loading|Загружаем/)).not.toBeInTheDocument());
    expect(
      main().queryByRole('link', { name: 'Walk through the screens' }),
    ).not.toBeInTheDocument();
  });
});
