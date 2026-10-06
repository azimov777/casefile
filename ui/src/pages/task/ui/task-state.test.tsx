import { http } from 'msw';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, taskPackage, taskState } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Блок «Сейчас» в карточке задачи (TRK-579): его считает бэкенд при чтении, интерфейс
 * только показывает и не редактирует. Тот же блок видит агент в `get_task`.
 */

function serve(state: ReturnType<typeof taskState>) {
  server.use(http.get(`${API}/api/v1/tasks/DEMO-7`, () => data(taskPackage('DEMO-7', { state }))));
}

beforeEach(() => {
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks/DEMO-7/entries`, () => collection([])),
  );
});

async function block(): Promise<HTMLElement> {
  const heading = await screen.findByRole('heading', { name: say.task('state.title') });
  return heading.closest('section') as HTMLElement;
}

describe('блок «Сейчас»', () => {
  it('называет причину последнего перехода, шаг сводки и записи после неё', async () => {
    serve(
      taskState({
        status: 'open',
        last_transition: {
          no: 6,
          from_status: 'in_progress',
          to_status: 'open',
          at: '2026-10-06T11:59Z',
          by: 'claude',
          reason: 'Жду ответа на DEMO-7#5',
        },
        last_summary: {
          no: 4,
          at: '2026-10-06T11:00Z',
          next_step: 'Ждать ответа владельца',
          blockers: 'Нужен ответ владельца',
          unmeasured: null,
        },
        after_summary: 4,
        recent: ['#7 finding claude 2026-10-06T12:01Z: Свежая находка'],
        recent_total: 1,
      }),
    );
    renderApp('/tasks/DEMO-7');

    const now = within(await block());
    expect(now.getByText('Жду ответа на DEMO-7#5')).toBeInTheDocument();
    expect(now.getByText('Ждать ответа владельца')).toBeInTheDocument();
    expect(now.getByText(/Свежая находка/)).toBeInTheDocument();
    expect(now.queryByText(say.task('state.unmeasured'))).not.toBeInTheDocument();
  });

  it('показывает, кого ждём, блокеры и детей; пустых строк не рисует', async () => {
    serve(
      taskState({
        questions: [{ no: 5, to: ['owner'], blocking: true, title: 'Брать вариант 3?' }],
        blockers: ['DEMO-2'],
        children: { done: 2, open: 1 },
        children_unclosed: ['DEMO-9'],
        decisions_after_card: [4],
      }),
    );
    renderApp('/tasks/DEMO-7');

    const now = within(await block());
    expect(now.getByText(/Брать вариант 3\?/)).toBeInTheDocument();
    expect(now.getByText(/owner/)).toBeInTheDocument();
    expect(now.getByRole('link', { name: 'DEMO-2' })).toHaveAttribute('href', '/tasks/DEMO-2');
    expect(now.getByRole('link', { name: 'DEMO-9' })).toHaveAttribute('href', '/tasks/DEMO-9');
    expect(now.getByText(say.task('state.decisionsAfterCard'))).toBeInTheDocument();
  });

  it('у задачи без вестей так и говорит: ничего не подшито', async () => {
    serve(taskState());
    renderApp('/tasks/DEMO-7');

    const now = within(await block());
    expect(now.getByText(say.task('state.noMove'))).toBeInTheDocument();
    expect(now.getByText(say.task('state.nothingNew'))).toBeInTheDocument();
    expect(now.queryByText(say.task('state.waitingFor'))).not.toBeInTheDocument();
    expect(now.queryByText(say.task('state.blockedBy'))).not.toBeInTheDocument();
  });
});
