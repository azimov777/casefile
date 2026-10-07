import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  discussion,
  discussionDetail,
  taskPage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Обсуждения во входящей и в истории (TRK-672, решение проекта `TRK#51`, п. 8): список
 * незакрытых с ходом за человеком, строка ведёт на экран обсуждения, «Новое обсуждение»
 * запиской.
 */

let asked: URL[] = [];

beforeEach(() => {
  asked = [];
  setToken('trk_test');
  server.use(
    http.get(`${API}/api/v1/tasks`, () => taskPage([])),
    http.get(`${API}/api/v1/questions`, () => collection([])),
    http.get(`${API}/api/v1/remarks`, () => collection([])),
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ open_discussions: 2 }))),
  );
});

describe('входящая по обсуждениям', () => {
  it('просит незакрытые с ходом за человеком, давнишние первыми', async () => {
    server.use(
      http.get(`${API}/api/v1/discussions`, ({ request }) => {
        asked.push(new URL(request.url));
        return collection([
          discussion('DEMO~2', { open_questions: 2 }),
          discussion('DEMO~5', { title: 'Нужна ли ночная тема?', open_questions: 1 }),
        ]);
      }),
    );
    renderApp('/questions');

    const section = await screen.findByRole('region', { name: say.discussions('inbox.title') });
    const rows = await within(section).findAllByRole('article');
    expect(rows).toHaveLength(2);

    expect(asked[0]?.searchParams.get('status')).toBe('open');
    expect(asked[0]?.searchParams.get('turn')).toBe('human');
    expect(asked[0]?.searchParams.get('order')).toBe('oldest');

    const first = within(rows[0] as HTMLElement);
    expect(first.getByRole('link', { name: 'DEMO~2' })).toHaveAttribute(
      'href',
      '/discussions/DEMO~2',
    );
    expect(first.getByText(say.discussions('row.openQuestions', { count: 2 }))).toBeInTheDocument();
    expect(first.getByText(say.discussions('turn.human'))).toBeInTheDocument();
  });

  it('проект отбирает и обсуждения', async () => {
    server.use(
      http.get(`${API}/api/v1/discussions`, ({ request }) => {
        asked.push(new URL(request.url));
        return collection([]);
      }),
    );
    renderApp('/questions?project=DEMO');

    expect(
      await screen.findByText(say.discussions('inbox.noneByProject', { project: 'DEMO' })),
    ).toBeInTheDocument();
    expect(asked[0]?.searchParams.get('project')).toBe('DEMO');
  });

  it('пусто — честно, без выдуманных обсуждений', async () => {
    renderApp('/questions');
    expect(await screen.findByText(say.discussions('inbox.none'))).toBeInTheDocument();
  });

  it('«Новое обсуждение» заводит запиской и открывает его экран', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${API}/api/v1/discussions`, async ({ request }) => {
        body = await request.json();
        return data(discussionDetail('DEMO~9', { turn: 'agent', open_questions: 0 }), 201);
      }),
      http.get(`${API}/api/v1/discussions/DEMO~9`, () =>
        data(discussionDetail('DEMO~9', { turn: 'agent', open_questions: 0 })),
      ),
      http.get(`${API}/api/v1/discussions/DEMO~9/entries`, () => collection([])),
    );
    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: say.discussions('create.open') }));
    const dialog = await screen.findByRole('dialog', { name: say.discussions('create.title') });
    await user.selectOptions(
      within(dialog).getByLabelText(say.discussions('create.projectLabel')),
      'DEMO',
    );
    await user.type(
      within(dialog).getByLabelText(say.discussions('create.titleLabel')),
      'Нужна ли ночная тема?',
    );
    await user.type(
      within(dialog).getByLabelText(say.discussions('create.tasksLabel')),
      'DEMO-4 DEMO-5',
    );
    await user.click(
      within(dialog).getByRole('button', { name: say.discussions('create.submit') }),
    );

    await waitFor(() => expect(address.current).toBe('/discussions/DEMO~9'));
    expect(body).toEqual({
      project: 'DEMO',
      title: 'Нужна ли ночная тема?',
      body: '',
      tasks: ['DEMO-4', 'DEMO-5'],
    });
  });
});

describe('история обсуждений', () => {
  it('показывает все обсуждения от свежих, и закрытые тоже', async () => {
    server.use(
      http.get(`${API}/api/v1/discussions`, ({ request }) => {
        asked.push(new URL(request.url));
        return collection([
          discussion('DEMO~3', { status: 'closed', turn: null, open_questions: 0 }),
        ]);
      }),
      http.get(`${API}/api/v1/questions`, () => collection([])),
    );
    renderApp('/questions?view=history');

    const section = await screen.findByRole('region', { name: say.discussions('history.title') });
    expect(await within(section).findByText(say.discussions('turn.closed'))).toBeInTheDocument();
    expect(asked[0]?.searchParams.get('order')).toBe('newest');
    expect(asked[0]?.searchParams.get('status')).toBeNull();
  });
});
