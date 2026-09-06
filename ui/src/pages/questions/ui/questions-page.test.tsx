import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { act } from '@testing-library/react';
import {
  API,
  answerEntry,
  bootstrap,
  collection,
  data,
  failure,
  questionEntry,
  taskPackage,
} from '@testing/msw/responses';
import { liveJournal } from '@testing/live-journal';
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
      const body = await request.json();
      sent.push({ url: new URL(request.url), key: request.headers.get('Idempotency-Key'), body });
      answered = true;
      open -= 1;
      return data(answerEntry(9, 'DEMO-4', 4, 'Храним вечно: дело неизменяемо.'), 201);
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

    // Ответ подшит — и это сказано словами, с номером записи ссылкой. Вопрос при этом
    // никуда не делся: раньше здесь исчезал весь блок, и единственным признаком, что
    // что-то произошло, был счётчик в шапке.
    const receipt = await screen.findByRole('region', { name: 'Ответ на DEMO-4#4 подшит' });
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4?entry=9',
    );
    expect(within(receipt).getByText('Храним вечно: дело неизменяемо.')).toBeInTheDocument();
    expect(screen.getByText(/Удалять ли записи/)).toBeInTheDocument();

    // Счётчик всё равно перечитан у бэкенда: подтверждение его не подменяет.
    await waitFor(() => expect(screen.getByText('Открытых вопросов: 1')).toBeInTheDocument());

    const post = posts()[0];
    expect(post?.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(post?.body).toEqual({
      type: 'answer',
      body: 'Храним вечно: дело неизменяемо.',
      payload: { question_no: 4 },
    });

    // Закрыть подтверждение — решение человека, а не таймера.
    await user.click(within(receipt).getByRole('button', { name: 'Закрыть' }));
    expect(await screen.findByText(/Вопросов без ответа нет/)).toBeInTheDocument();
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
          fields: { body: 'Тело записи не может быть пустым' },
        });
      }),
    );

    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: 'Ответить' }));
    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    expect(await screen.findByText(/Пустой ответ отправить нельзя/)).toBeInTheDocument();
    expect(screen.getByLabelText('Ответ')).toHaveAttribute('aria-invalid', 'true');
    expect(posts()).toHaveLength(0);

    // Упрёк снимается первым же символом: человек сделал ровно то, о чём его
    // попросили, и продолжать показывать ему красное значит штрафовать за прошлое.
    await user.type(screen.getByLabelText('Ответ'), 'О');
    expect(screen.queryByText(/Пустой ответ отправить нельзя/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Ответ')).toHaveAttribute('aria-invalid', 'false');

    await user.type(screen.getByLabelText('Ответ'), 'тветил');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));

    expect(await screen.findByText('Тело записи не может быть пустым')).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  /**
   * Кадр живого потока об ответе так, как его отдаёт бэкенд: ответ подшит,
   * входящая и счётчик устарели.
   */
  function answerFrame() {
    return {
      ...answerEntry(9, 'DEMO-4', 4, 'Храним вечно: дело неизменяемо.'),
      seq: 1050,
    };
  }

  /** Входящая, в которой ответ уже подшит на сервере, но ответ POST ещё не пришёл. */
  function inFlight() {
    let answered = false;
    let release = () => {};

    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => {
        sent.push({ url: new URL(`${API}/api/v1/questions`), key: null, body: null });
        return collection(answered ? [] : [questionEntry(4, 'DEMO-4')]);
      }),
      http.post(`${API}/api/v1/tasks/DEMO-4/entries`, async ({ request }) => {
        sent.push({
          url: new URL(request.url),
          key: request.headers.get('Idempotency-Key'),
          body: await request.json(),
        });
        // Бэкенд подшил ответ и с этого мгновения отдаёт входящую без этого вопроса —
        // но наш ответ POST ещё в пути.
        answered = true;
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return data(answerEntry(9, 'DEMO-4', 4, 'Храним вечно: дело неизменяемо.'), 201);
      }),
      http.get(`${API}/api/v1/tasks/DEMO-4`, () => data(taskPackage('DEMO-4'))),
    );

    return { release: () => release() };
  }

  async function fillAndSend(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: 'Ответить' }));
    await user.type(screen.getByLabelText('Ответ'), 'Храним вечно: дело неизменяемо.');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));
    await waitFor(() => expect(posts()).toHaveLength(1));
  }

  it('кадр потока приходит раньше ответа сервера — подтверждение всё равно показано', async () => {
    const flight = inFlight();
    const user = userEvent.setup();
    renderApp('/questions');
    await fillAndSend(user);

    // Кадр обгоняет ответ POST: входящая перечитывается и приходит уже без вопроса.
    // Раньше здесь строка размонтировалась вместе с формой, и исход ответа терялся.
    act(() => liveJournal.send(answerFrame()));
    await waitFor(() =>
      expect(
        sent.filter((call) => call.url.pathname.endsWith('/questions')).length,
      ).toBeGreaterThan(1),
    );
    expect(screen.getByText(/Удалять ли записи/)).toBeInTheDocument();

    await act(async () => {
      flight.release();
      await Promise.resolve();
    });

    const receipt = await screen.findByRole('region', { name: 'Ответ на DEMO-4#4 подшит' });
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toBeInTheDocument();
    // Второго ответа не создано: отправка была одна.
    expect(posts()).toHaveLength(1);
  });

  it('ответ сервера приходит раньше кадра — видимый исход тот же', async () => {
    const flight = inFlight();
    const user = userEvent.setup();
    renderApp('/questions');
    await fillAndSend(user);

    await act(async () => {
      flight.release();
      await Promise.resolve();
    });

    const receipt = await screen.findByRole('region', { name: 'Ответ на DEMO-4#4 подшит' });
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toBeInTheDocument();

    // Кадр приезжает следом и ничего не отменяет.
    act(() => liveJournal.send(answerFrame()));
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Ответ на DEMO-4#4 подшит' })).toBeInTheDocument(),
    );
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toBeInTheDocument();
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
