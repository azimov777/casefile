import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  discussionAnswer,
  discussionConclusion,
  discussionDetail,
  discussionNote,
  discussionQuestion,
  failure,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/*
 * Экран обсуждения (TRK-672): итог сверху, привязанные задачи, переписка по времени,
 * ответ и заметка прямо на экране, привязка и отвязка; закрытое обсуждение — без форм.
 */

const ADDRESS = 'DEMO~2';
const PATH = `${API}/api/v1/discussions/${ADDRESS}`;

interface Sent {
  method: string;
  path: string;
  key: string | null;
  body: unknown;
}

let sent: Sent[] = [];

async function remember(request: Request): Promise<void> {
  const text = await request.clone().text();
  sent.push({
    method: request.method,
    path: new URL(request.url).pathname,
    key: request.headers.get('Idempotency-Key'),
    body: text === '' ? null : JSON.parse(text),
  });
}

beforeEach(() => {
  sent = [];
  setToken('trk_test');
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
});

/** Обсуждение с вопросом без ответа и одной привязанной задачей. */
function openDiscussion(overrides: Parameters<typeof discussionDetail>[1] = {}) {
  server.use(
    http.get(PATH, () =>
      data(
        discussionDetail(ADDRESS, {
          tasks: [
            {
              key: 'DEMO-4',
              title: 'Хранение дел',
              status: 'open',
              attached_by: { kind: 'agent', signature: 'claude' },
              attached_at: '2026-09-01T10:00:00Z',
            },
          ],
          ...overrides,
        }),
      ),
    ),
    http.get(`${PATH}/entries`, () =>
      collection([
        discussionNote(ADDRESS, 1, 'Контекст: см. DEMO~1#2'),
        discussionQuestion(ADDRESS, 2),
      ]),
    ),
  );
}

describe('экран обсуждения', () => {
  it('показывает название, чей ход, пустой итог, задачи и переписку', async () => {
    openDiscussion();
    renderApp(`/discussions/${ADDRESS}`);

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Сколько хранить дела отменённых задач?',
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(say.discussions('turn.human')).length).toBeGreaterThan(0);
    expect(screen.getByText(say.discussions('conclusion.none'))).toBeInTheDocument();

    const tasks = screen.getByRole('region', { name: say.discussions('tasks.title') });
    expect(within(tasks).getByRole('link', { name: 'DEMO-4' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4',
    );

    const thread = await screen.findByRole('list', { name: say.discussions('thread.label') });
    expect(within(thread).getByText('Хранить вечно или год?')).toBeInTheDocument();
    expect(within(thread).getByText(say.discussions('thread.waiting'))).toBeInTheDocument();
  });

  it('закрыть обсуждение человек не может: кнопки закрытия нет', async () => {
    openDiscussion();
    renderApp(`/discussions/${ADDRESS}`);
    await screen.findByRole('heading', { level: 1 });

    expect(screen.queryByRole('button', { name: /close|закры/i })).not.toBeInTheDocument();
  });

  it('ссылки TRK~N#M в тексте записей кликабельны', async () => {
    server.use(
      http.get(PATH, () => data(discussionDetail(ADDRESS))),
      http.get(`${PATH}/entries`, () =>
        collection([
          discussionQuestion(ADDRESS, 2, 'Раньше решили в DEMO~1#2, а задача — DEMO-4.'),
        ]),
      ),
    );
    // `?entry=2` раскрывает тело вопроса: свёрнутое под «Подробности» диктору не видно.
    renderApp(`/discussions/${ADDRESS}?entry=2`);

    const thread = await screen.findByRole('list', { name: say.discussions('thread.label') });
    expect(within(thread).getByRole('link', { name: 'DEMO~1#2' })).toHaveAttribute(
      'href',
      '/discussions/DEMO~1?entry=2',
    );
    expect(within(thread).getByRole('link', { name: 'DEMO-4' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4',
    );
  });

  it('итог сверху: три части и ссылка на запись', async () => {
    openDiscussion({ conclusion: discussionConclusion(ADDRESS, 5) });
    renderApp(`/discussions/${ADDRESS}`);

    const box = await screen.findByRole('region', { name: say.discussions('conclusion.title') });
    expect(within(box).getByText(say.ui('entry.conclusion.decided'))).toBeInTheDocument();
    expect(within(box).getByText(say.ui('entry.conclusion.superseded'))).toBeInTheDocument();
    expect(within(box).getByText(say.ui('entry.conclusion.open'))).toBeInTheDocument();
    // Ссылка внутри текста части ведёт на запись обсуждения.
    expect(within(box).getByRole('link', { name: `${ADDRESS}#2` })).toHaveAttribute(
      'href',
      `/discussions/${ADDRESS}?entry=2`,
    );
  });

  it('«Ответить на #N» шлёт ответ на вопрос с ключом повтора', async () => {
    openDiscussion();
    server.use(
      http.post(`${PATH}/entries`, async ({ request }) => {
        await remember(request);
        return data(discussionAnswer(ADDRESS, 3, 2), 201);
      }),
    );
    const user = userEvent.setup();
    renderApp(`/discussions/${ADDRESS}`);

    await user.click(
      await screen.findByRole('button', { name: say.discussions('reply.open', { no: 2 }) }),
    );
    await user.type(
      screen.getByRole('textbox', { name: say.discussions('reply.fieldLabel') }),
      'Храним вечно',
    );
    await user.click(screen.getByRole('button', { name: say.discussions('reply.submit') }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      method: 'POST',
      path: `/api/v1/discussions/${ADDRESS}/entries`,
      body: { type: 'answer', body: 'Храним вечно', payload: { question_no: 2 } },
    });
    expect(sent[0]?.key).not.toBeNull();
  });

  it('вопрос с ответом не просит ответа и называется отвеченным', async () => {
    server.use(
      http.get(PATH, () => data(discussionDetail(ADDRESS, { turn: 'agent', open_questions: 0 }))),
      http.get(`${PATH}/entries`, () =>
        collection([discussionQuestion(ADDRESS, 2), discussionAnswer(ADDRESS, 3, 2)]),
      ),
    );
    renderApp(`/discussions/${ADDRESS}`);

    const thread = await screen.findByRole('list', { name: say.discussions('thread.label') });
    expect(await within(thread).findByText(say.discussions('thread.answered'))).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: say.discussions('reply.open', { no: 2 }) }),
    ).not.toBeInTheDocument();
  });

  it('«Заметка» шлёт свободную запись, заголовок — первая строка', async () => {
    openDiscussion();
    server.use(
      http.post(`${PATH}/entries`, async ({ request }) => {
        await remember(request);
        return data(discussionNote(ADDRESS, 3), 201);
      }),
    );
    const user = userEvent.setup();
    renderApp(`/discussions/${ADDRESS}`);

    await user.click(await screen.findByRole('button', { name: say.discussions('note.open') }));
    await user.type(
      screen.getByRole('textbox', { name: say.discussions('note.fieldLabel') }),
      'Это касается архивных проектов',
    );
    await user.click(screen.getByRole('button', { name: say.discussions('note.submit') }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.body).toEqual({
      type: 'note',
      title: 'Это касается архивных проектов',
      body: 'Это касается архивных проектов',
    });
  });

  it('привязывает задачу по ключу и отвязывает привязанную', async () => {
    openDiscussion();
    server.use(
      http.post(`${PATH}/tasks`, async ({ request }) => {
        await remember(request);
        return data(
          {
            key: 'DEMO-5',
            title: 'Другая',
            status: 'open',
            attached_by: { kind: 'human', signature: 'owner' },
            attached_at: '2026-09-02T10:00:00Z',
          },
          201,
        );
      }),
      http.delete(`${PATH}/tasks/DEMO-4`, async ({ request }) => {
        await remember(request);
        return new Response(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/discussions/${ADDRESS}`);

    await user.type(
      await screen.findByRole('textbox', { name: say.discussions('attach.fieldLabel') }),
      'DEMO-5',
    );
    await user.click(screen.getByRole('button', { name: say.discussions('attach.submit') }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      method: 'POST',
      path: `/api/v1/discussions/${ADDRESS}/tasks`,
      body: { task: 'DEMO-5' },
    });

    await user.click(
      screen.getByRole('button', { name: say.discussions('detach.label', { key: 'DEMO-4' }) }),
    );
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({
      method: 'DELETE',
      path: `/api/v1/discussions/${ADDRESS}/tasks/DEMO-4`,
    });
  });

  it('отказ привязки сказан словами под полем', async () => {
    openDiscussion();
    server.use(http.post(`${PATH}/tasks`, () => failure('task_closed', 409, 'Task is closed')));
    const user = userEvent.setup();
    renderApp(`/discussions/${ADDRESS}`);

    await user.type(
      await screen.findByRole('textbox', { name: say.discussions('attach.fieldLabel') }),
      'DEMO-1',
    );
    await user.click(screen.getByRole('button', { name: say.discussions('attach.submit') }));

    expect(await screen.findByText(say.errors('task_closed'))).toBeInTheDocument();
  });

  it('закрытое обсуждение: плашка, ни форм, ни «Отвязать», ни «Привязать»', async () => {
    openDiscussion({
      status: 'closed',
      turn: null,
      open_questions: 0,
      closed_at: '2026-09-03T10:00:00Z',
      conclusion: discussionConclusion(ADDRESS, 5),
    });
    renderApp(`/discussions/${ADDRESS}`);

    await screen.findByRole('heading', { level: 1 });
    expect(await screen.findAllByText(say.discussions('turn.closed'))).not.toHaveLength(0);
    expect(screen.queryByRole('button', { name: say.discussions('note.open') })).toBeNull();
    expect(
      screen.queryByRole('textbox', { name: say.discussions('attach.fieldLabel') }),
    ).toBeNull();
    expect(screen.queryByRole('button', { name: say.discussions('attach.submit') })).toBeNull();
    expect(
      screen.queryByRole('button', { name: say.discussions('detach.label', { key: 'DEMO-4' }) }),
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: say.discussions('reply.open', { no: 2 }) }),
    ).toBeNull();
    // Привязанная задача остаётся видна ссылкой.
    expect(screen.getByRole('link', { name: 'DEMO-4' })).toBeInTheDocument();
  });

  it('нет такого обсуждения — словами и ссылкой во входящую', async () => {
    server.use(http.get(PATH, () => failure('discussion_not_found', 404, 'Discussion not found')));
    renderApp(`/discussions/${ADDRESS}`);

    expect(
      await screen.findByRole('heading', {
        name: say.discussions('page.missingTitle', { address: ADDRESS }),
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: say.discussions('page.backToInbox') })).toHaveAttribute(
      'href',
      '/questions',
    );
  });
});
