import { http } from 'msw';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, data, taskPackage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import type { CitedDecision } from '@/entities/task';
import { setToken } from '@/shared/api';

/** Решения, на которые ссылается задача: одно действует, другое заменено. */
const DECISIONS: CitedDecision[] = [
  { ref: 'DEMO#4', title: 'Журнал вместо событий', status: 'in_force', superseded_by: null },
  {
    ref: 'DEMO#2',
    title: 'Номер выдаёт счётчик',
    status: 'superseded',
    superseded_by: { ref: 'DEMO#6', title: 'Номер выдаётся последним', status: 'in_force' },
  },
];

beforeEach(() => {
  setToken('trk_test');
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
});

describe('решения проекта в шапке задачи', () => {
  it('строка «Решения» называет каждое решение со статусом, у заменённого — преемника', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-1`, () =>
        data(taskPackage('DEMO-1', { decisions: DECISIONS })),
      ),
    );
    renderApp('/tasks/DEMO-1');
    await screen.findByRole('heading', { name: /DEMO-1/ });

    const label = screen.getByText(say.task('header.decisions'), { selector: 'dt' });
    const cell = label.parentElement as HTMLElement;
    const [current, old] = within(cell).getAllByRole('listitem');

    expect(current).toHaveAttribute('data-status', 'in_force');
    expect(within(current as HTMLElement).getByRole('link', { name: 'DEMO#4' })).toHaveAttribute(
      'href',
      '/projects/DEMO?entry=4',
    );
    expect(current).toHaveTextContent(say.ui('decision.status.in_force'));

    expect(old).toHaveAttribute('data-status', 'superseded');
    expect(old).toHaveTextContent(say.ui('decision.status.superseded'));
    expect(old).toHaveTextContent(say.task('header.supersededBy'));
    expect(within(old as HTMLElement).getByRole('link', { name: 'DEMO#6' })).toHaveAttribute(
      'href',
      '/projects/DEMO?entry=6',
    );
    expect(old).toHaveTextContent('Номер выдаётся последним');
  });

  it('у задачи без решений строки нет вовсе', async () => {
    server.use(http.get(`${API}/api/v1/tasks/DEMO-1`, () => data(taskPackage('DEMO-1'))));
    renderApp('/tasks/DEMO-1');
    await screen.findByRole('heading', { name: /DEMO-1/ });

    expect(screen.queryByText(say.task('header.decisions'), { selector: 'dt' })).toBeNull();
  });
});
