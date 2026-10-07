import { http } from 'msw';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, discussion, taskPackage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Блок «Обсуждения» в карточке задачи (TRK-672, `TRK#51`, п. 8): адрес, название и чей
 * ход. Пакет преемника обсуждений не несёт, блок читает список отбором `task`.
 */

beforeEach(() => {
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks/DEMO-4`, () => data(taskPackage('DEMO-4'))),
    http.get(`${API}/api/v1/tasks/DEMO-4/entries`, () => collection([])),
  );
});

describe('обсуждения в карточке задачи', () => {
  it('перечисляет обсуждения задачи с ходом и вопросами, запрос — отбором по задаче', async () => {
    let asked: URL | null = null;
    server.use(
      http.get(`${API}/api/v1/discussions`, ({ request }) => {
        asked = new URL(request.url);
        return collection([
          discussion('DEMO~2', { open_questions: 1 }),
          discussion('DEMO~1', { status: 'closed', turn: null, open_questions: 0 }),
        ]);
      }),
    );
    renderApp('/tasks/DEMO-4');

    const block = (
      await screen.findByRole('heading', { name: say.discussions('taskBlock.title') })
    ).closest('section') as HTMLElement;
    const rows = await within(block).findAllByRole('article');
    expect(rows).toHaveLength(2);
    expect(within(block).getByRole('link', { name: 'DEMO~2' })).toHaveAttribute(
      'href',
      '/discussions/DEMO~2',
    );
    expect(within(block).getByText(say.discussions('turn.human'))).toBeInTheDocument();
    expect(within(block).getByText(say.discussions('turn.closed'))).toBeInTheDocument();
    expect(asked).not.toBeNull();
    expect((asked as unknown as URL).searchParams.get('task')).toBe('DEMO-4');
  });

  it('у задачи без обсуждений блок говорит об этом', async () => {
    renderApp('/tasks/DEMO-4');
    expect(await screen.findByText(say.discussions('taskBlock.none'))).toBeInTheDocument();
  });
});
