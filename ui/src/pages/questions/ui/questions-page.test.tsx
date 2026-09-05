import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  failure,
  questionEntry,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { setToken } from '@/shared/api';

/** Что и с какими заголовками уходило на бэкенд за прогон. */
interface Sent {
  url: URL;
  key: string | null;
  body: unknown;
}

let sent: Sent[] = [];

beforeEach(() => {
  sent = [];
  setToken('trk_test');
});

/** Входящая: пока не ответили — один вопрос, после ответа — пусто. */
function inbox() {
  let answered = false;
  let open = 2;

  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ open_questions: open }))),

    http.get(`${API}/api/v1/questions`, ({ request }) => {
      const url = new URL(request.url);
      sent.push({ url, key: null, body: null });
      if (answered) return collection([]);
      const blocking = url.searchParams.get('blocking');
      const items =
        blocking === 'true' ? [questionEntry(4, 'DEMO-4')] : [questionEntry(4, 'DEMO-4')];
      return collection(items);
    }),

    http.post(`${API}/api/v1/tasks/DEMO-4/entries`, async ({ request }) => {
      sent.push({
        url: new URL(request.url),
        key: request.headers.get('Idempotency-Key'),
        body: await request.json(),
      });
      answered = true;
      open -= 1;
      return data({ ok: true }, 201);
    }),

    http.get(`${API}/api/v1/tasks/DEMO-4`, () => data(taskPackage('DEMO-4'))),
  );
}

function posts() {
  return sent.filter((call) => call.url.pathname.endsWith('/entries'));
}

describe('входящая и ответ', () => {
  it('показывает адресованный вопрос и отвечает на него с ключом повтора', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    expect(await screen.findByText(/Срок хранения дел|Удалять ли записи/)).toBeInTheDocument();
    expect(screen.getByText('блокирующий')).toBeInTheDocument();
    expect(screen.getByText('Открытых вопросов: 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Ответить' }));
    await user.type(screen.getByLabelText('Ответ'), 'Храним вечно: дело неизменяемо.');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    // Вопрос ушёл из входящей, счётчик в шапке перечитан у бэкенда.
    expect(await screen.findByText(/Вопросов без ответа нет/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Открытых вопросов: 1')).toBeInTheDocument());

    const post = posts()[0];
    expect(post?.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(post?.body).toEqual({
      type: 'answer',
      body: 'Храним вечно: дело неизменяемо.',
      refs: [],
      payload: { question_no: 4 },
    });
  });

  it('повтор после обрыва идёт с тем же ключом: второго ответа не будет', async () => {
    let firstAttempt = true;
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([questionEntry(4, 'DEMO-4')])),
      http.post(`${API}/api/v1/tasks/DEMO-4/entries`, async ({ request }) => {
        sent.push({
          url: new URL(request.url),
          key: request.headers.get('Idempotency-Key'),
          body: await request.json(),
        });
        if (firstAttempt) {
          firstAttempt = false;
          return failure('database_unavailable', 503, 'Database is not available');
        }
        return data({ ok: true }, 201);
      }),
      http.get(`${API}/api/v1/tasks/DEMO-4`, () => data(taskPackage('DEMO-4'))),
    );

    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: 'Ответить' }));
    await user.type(screen.getByLabelText('Ответ'), 'Ответ, который не дошёл с первого раза');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    expect(await screen.findByText(/База данных недоступна/)).toBeInTheDocument();
    // Текст никуда не делся: человеку не нужно набирать его заново.
    expect(screen.getByLabelText('Ответ')).toHaveValue('Ответ, который не дошёл с первого раза');

    await user.click(screen.getByRole('button', { name: 'Ответить' }));
    await waitFor(() => expect(posts()).toHaveLength(2));

    const [first, second] = posts();
    expect(second?.key).toBe(first?.key);
  });

  it('пустой ответ не отправляется, а замечание бэкенда показано у поля', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([questionEntry(4, 'DEMO-4')])),
      http.post(`${API}/api/v1/tasks/DEMO-4/entries`, async ({ request }) => {
        sent.push({
          url: new URL(request.url),
          key: request.headers.get('Idempotency-Key'),
          body: await request.json(),
        });
        return failure('entry_fields_invalid', 422, 'Entry fields invalid', {
          fields: { refs: 'Ссылка DEMO-999 не существует' },
        });
      }),
    );

    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: 'Ответить' }));
    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    expect(await screen.findByText(/Пустой ответ отправить нельзя/)).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Ответ'), 'Ответ со ссылкой');
    await user.type(screen.getByLabelText('Ссылки на записи и задачи'), 'DEMO-999');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    expect(await screen.findByText('Ссылка DEMO-999 не существует')).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  it('черновик переживает уход на другую страницу и возврат', async () => {
    inbox();
    server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));

    const user = userEvent.setup();
    const { unmount } = renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: 'Ответить' }));
    await user.type(screen.getByLabelText('Ответ'), 'Начал писать и отвлёкся');
    unmount();

    renderApp('/questions');
    await user.click(await screen.findByRole('button', { name: 'Ответить' }));

    expect(screen.getByLabelText('Ответ')).toHaveValue('Начал писать и отвлёкся');
  });

  it('отбор «только блокирующие» уходит в запрос', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    await screen.findByRole('button', { name: 'Ответить' });
    await user.click(screen.getByRole('checkbox', { name: 'только блокирующие' }));

    await waitFor(() => {
      const last = sent.filter((call) => call.url.pathname.endsWith('/questions')).at(-1);
      expect(last?.url.searchParams.get('blocking')).toBe('true');
    });
  });
});
