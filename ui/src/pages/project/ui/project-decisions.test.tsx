import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  entryOfType,
  projectDetail,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import type { ProjectDecision } from '@/entities/project';
import { setToken, type components } from '@/shared/api';

const CREATED = '2026-09-01T10:00:00Z';

/** Решение проекта DEMO в чтении проекта: статус и преемник считает бэкенд. */
function decision(no: number, overrides: Partial<ProjectDecision> = {}): ProjectDecision {
  return {
    no,
    ref: `DEMO#${no}`,
    title: `Решение ${no}`,
    author: { kind: 'agent', signature: 'demo_agent' },
    created_at: CREATED,
    status: 'in_force',
    supersedes: [],
    superseded_by: null,
    tasks: 0,
    ...overrides,
  };
}

/** Заменённое решение и его преемник: обратный путь к задачам — у заменённого. */
const DECISIONS: ProjectDecision[] = [
  decision(5, {
    title: 'Держим ветку main единственной',
    status: 'superseded',
    superseded_by: 8,
    tasks: 2,
  }),
  decision(8, { title: 'Ветки задач сливаются в main скриптом', supersedes: [5] }),
];

function serve(decisions: ProjectDecision[]) {
  server.use(
    http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail('DEMO', { decisions }))),
    http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([])),
    http.get(`${API}/api/v1/projects/DEMO/areas`, () => collection([])),
    // Счётчики шапки (TRK-619) читают список задач; их числа здесь не проверяются.
    http.get(`${API}/api/v1/tasks`, () => collection([], { total: 0 })),
  );
}

beforeEach(() => {
  setToken('trk_test');
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
});

describe('решения проекта на экране проекта', () => {
  it('действующее — сверху со статусом, заменённое свёрнуто вместе с тем, что его заменило', async () => {
    const user = userEvent.setup();
    serve(DECISIONS);
    renderApp('/projects/DEMO?tab=decisions');

    const region = await screen.findByRole('region', { name: say.project('decisions.title') });
    const inForce = within(region).getByRole('list', { name: say.project('decisions.inForce') });
    const row = within(inForce).getByRole('listitem');
    expect(within(row).getByRole('link', { name: 'DEMO#8' })).toHaveAttribute(
      'href',
      '/projects/DEMO?entry=8',
    );
    expect(row).toHaveTextContent('Ветки задач сливаются в main скриптом');
    expect(row).toHaveTextContent(say.ui('decision.status.in_force'));
    expect(row).toHaveTextContent(say.project('decisions.noTasks'));
    expect(within(row).getByRole('link', { name: 'DEMO#5' })).toHaveAttribute(
      'href',
      '/projects/DEMO?entry=5',
    );

    // Заменённое — история: оно свёрнуто, пока его не попросили.
    expect(
      within(region).queryByRole('list', { name: say.project('decisions.supersededList') }),
    ).toBeNull();
    const toggle = within(region).getByRole('button', {
      name: say.project('decisions.superseded', { count: 1 }),
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const history = within(region).getByRole('list', {
      name: say.project('decisions.supersededList'),
    });
    const old = within(history).getByRole('listitem');
    expect(old).toHaveAttribute('data-status', 'superseded');
    expect(old).toHaveTextContent(say.ui('decision.status.superseded'));
    expect(old).toHaveTextContent(`${say.project('decisions.supersededBy')} DEMO#8`);

    // Обратный путь: задачи по заменённому решению — список задач с отбором `decision:`
    // и показанным архивом: закрытые задачи в этой истории важнее открытых.
    const tasks = within(old).getByRole('link', {
      name: say.project('decisions.tasks', { count: 2 }),
    });
    const target = new URL(tasks.getAttribute('href') ?? '', 'http://ui.test');
    expect(target.pathname).toBe('/tasks');
    expect(target.searchParams.get('query')).toBe('decision: DEMO#5');
    expect(target.searchParams.has('archive')).toBe(true);
  });

  it('ссылка решения открывает «Дело» с раскрытой записью — тем же адресом, что `DEMO#8`', async () => {
    const user = userEvent.setup();
    serve(DECISIONS);
    const record = {
      ...entryOfType(8, 'DEMO', 'decision'),
      task_key: null,
      project_key: 'DEMO',
      title: 'Ветки задач сливаются в main скриптом',
      body: 'Скрипт прогоняет оба набора.',
    } as components['schemas']['EntryRead'];
    server.use(
      http.get(`${API}/api/v1/projects/DEMO/entries`, () => collection([record])),
      http.get(`${API}/api/v1/projects/DEMO/entries/8`, () => data(record)),
    );
    renderApp('/projects/DEMO?tab=decisions');

    const region = await screen.findByRole('region', { name: say.project('decisions.title') });
    await user.click(within(region).getAllByRole('link', { name: 'DEMO#8' })[0] as HTMLElement);

    // Вкладка решений снята: запись сама открывает «Дело» — тот же адрес, что у ссылки
    // `DEMO#8` из любого другого места.
    expect(address.current).toBe('/projects/DEMO?entry=8');
    expect(
      within(screen.getByRole('navigation', { name: say.project('tabs.label') })).getByRole(
        'link',
        { name: say.project('tabs.case') },
      ),
    ).toHaveAttribute('aria-current', 'true');
    expect(await screen.findByText('Скрипт прогоняет оба набора.')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Ветки задач сливаются в main скриптом/ }),
    ).toHaveAttribute('aria-expanded', 'true');
  });

  it('пустое состояние сказано словами', async () => {
    serve([]);
    renderApp('/projects/DEMO?tab=decisions');

    const region = await screen.findByRole('region', { name: say.project('decisions.title') });
    expect(region).toHaveTextContent(say.project('decisions.none'));
    expect(within(region).queryByRole('button')).toBeNull();
  });

  it('когда действующих нет, это сказано отдельно от «решений нет вовсе»', async () => {
    serve([
      decision(3, { status: 'superseded', superseded_by: 4 }),
      decision(4, { status: 'superseded', superseded_by: 6 }),
    ]);
    renderApp('/projects/DEMO?tab=decisions');

    const region = await screen.findByRole('region', { name: say.project('decisions.title') });
    expect(region).toHaveTextContent(say.project('decisions.noneInForce'));
  });
});
