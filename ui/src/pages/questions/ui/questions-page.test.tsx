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
  remarkEntry,
  taskPackage,
} from '@testing/msw/responses';
import { liveJournal } from '@testing/live-journal';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
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
  it('блокирующий вопрос отличается признаком в разметке и доступным именем', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () =>
        collection([questionEntry(7, 'DEMO-3', true), questionEntry(8, 'DEMO-4', false)]),
      ),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions');

    const blocking = await screen.findByRole('article', {
      name: say.questions('blockingQuestionLabel', { reference: 'DEMO-3#7' }),
    });
    const usual = screen.getByRole('article', {
      name: say.questions('questionLabel', { reference: 'DEMO-4#8' }),
    });

    // Различие держится не цветом кромки: признак есть в разметке и в доступном имени,
    // а рядом остаётся плашка со словом.
    expect(blocking).toHaveAttribute('data-blocking', 'true');
    expect(usual).not.toHaveAttribute('data-blocking');
    expect(blocking).toHaveTextContent(say.ui('entry.blocking'));
  });
  it('показывает адресованный вопрос и отвечает на него с ключом повтора', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    expect(await screen.findByText(/Срок хранения дел|Удалять ли записи/)).toBeInTheDocument();
    expect(screen.getByText(say.ui('entry.blocking'))).toBeInTheDocument();
    expect(screen.getByText(say.ui('app.openQuestions', { count: 2 }))).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: say.ui('answer.open') }));
    await user.type(
      screen.getByLabelText(say.ui('answer.fieldLabel')),
      'Храним вечно: дело неизменяемо.',
    );
    await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));

    // Ответ подшит — и это сказано словами, с номером записи ссылкой. Вопрос при этом
    // никуда не делся: раньше здесь исчезал весь блок, и единственным признаком, что
    // что-то произошло, был счётчик в шапке.
    const receipt = await screen.findByRole('region', {
      name: say.ui('answer.receiptLabel', { reference: 'DEMO-4#4' }),
    });
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4?entry=9',
    );
    expect(within(receipt).getByText('Храним вечно: дело неизменяемо.')).toBeInTheDocument();
    expect(screen.getByText(/Удалять ли записи/)).toBeInTheDocument();

    // Счётчик всё равно перечитан у бэкенда: подтверждение его не подменяет.
    await waitFor(() =>
      expect(screen.getByText(say.ui('app.openQuestions', { count: 1 }))).toBeInTheDocument(),
    );

    const post = posts()[0];
    expect(post?.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(post?.body).toEqual({
      type: 'answer',
      body: 'Храним вечно: дело неизменяемо.',
      payload: { question_no: 4 },
    });

    // Закрыть подтверждение — решение человека, а не таймера.
    await user.click(within(receipt).getByRole('button', { name: say.ui('receipt.close') }));
    expect(await screen.findByText(say.questions('noQuestions'))).toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(
      screen.getByLabelText(say.ui('answer.fieldLabel')),
      'Ответ, который не дошёл с первого раза',
    );
    await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));

    expect(
      await screen.findByText(new RegExp(say.errors('database_unavailable'))),
    ).toBeInTheDocument();
    // Текст никуда не делся: человеку не нужно набирать его заново.
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue(
      'Ответ, который не дошёл с первого раза',
    );

    await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));
    await waitFor(() => expect(posts()).toHaveLength(2));

    const [first, second] = posts();
    expect(second?.key).toBe(first?.key);
  });

  it.each(['en', 'ru'] as const)(
    'пустой ответ не отправляется, а причина по полю от бэкенда переведена и показана у него (%s)',
    async (language) => {
      server.use(
        http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
        http.get(`${API}/api/v1/questions`, () => collection([questionEntry(4, 'DEMO-4')])),
        http.post(`${API}/api/v1/tasks/DEMO-4/entries`, async ({ request }) => {
          sent.push({
            url: new URL(request.url),
            key: request.headers.get('Idempotency-Key'),
            body: await request.json(),
          });
          // Настоящая форма бэкенда (`app/domain/fields.py`, `tests/test_case_api.py`):
          // список `{field, reason, ...}`, а не объект `{поле: причина}` (UI-165) —
          // и причина стабильный код `snake_case`, а не готовая фраза для человека.
          return failure('entry_fields_invalid', 422, 'Entry fields invalid', {
            fields: [{ field: 'body', reason: 'too_long', max: 65_536, got: 70_000 }],
          });
        }),
      );

      const user = userEvent.setup();
      renderApp('/questions', { language });

      await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
      await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));

      expect(await screen.findByText(say.ui('answer.empty'))).toBeInTheDocument();
      expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveAttribute(
        'aria-invalid',
        'true',
      );
      expect(posts()).toHaveLength(0);

      // Упрёк снимается первым же символом: человек сделал ровно то, о чём его
      // попросили, и продолжать показывать ему красное значит штрафовать за прошлое.
      await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'О');
      expect(screen.queryByText(say.ui('answer.empty'))).not.toBeInTheDocument();
      expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveAttribute(
        'aria-invalid',
        'false',
      );

      await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'тветил');
      await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));

      // Причина — переведённый текст по коду словаря `fieldReasons`, на языке
      // интерфейса, а не код и не фраза бэкенда: `message` — техническая, для лога.
      expect(await screen.findByText(say.fieldReasons('too_long'))).toBeInTheDocument();
      expect(posts()).toHaveLength(1);
    },
  );

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
    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(
      screen.getByLabelText(say.ui('answer.fieldLabel')),
      'Храним вечно: дело неизменяемо.',
    );
    await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));
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

    const receipt = await screen.findByRole('region', {
      name: say.ui('answer.receiptLabel', { reference: 'DEMO-4#4' }),
    });
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

    const receipt = await screen.findByRole('region', {
      name: say.ui('answer.receiptLabel', { reference: 'DEMO-4#4' }),
    });
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toBeInTheDocument();

    // Кадр приезжает следом и ничего не отменяет.
    act(() => liveJournal.send(answerFrame()));
    await waitFor(() =>
      expect(
        screen.getByRole('region', {
          name: say.ui('answer.receiptLabel', { reference: 'DEMO-4#4' }),
        }),
      ).toBeInTheDocument(),
    );
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  it('черновик переживает уход на другую страницу и возврат', async () => {
    inbox();
    server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));

    const user = userEvent.setup();
    const { unmount } = renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'Начал писать и отвлёкся');
    unmount();

    renderApp('/questions');
    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));

    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue(
      'Начал писать и отвлёкся',
    );
  });

  it('отбор «только блокирующие» уходит в запрос', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    await screen.findByRole('button', { name: say.ui('answer.open') });
    await user.click(screen.getByRole('checkbox', { name: say.questions('blockingOnly') }));

    await waitFor(() => {
      const last = sent.filter((call) => call.url.pathname.endsWith('/questions')).at(-1);
      expect(last?.url.searchParams.get('blocking')).toBe('true');
    });
  });
});

describe('входящая: отмена ответа (UI-156)', () => {
  it('«Отмена» на пустой форме сворачивает её без вопроса', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('');

    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    // Никакого вопроса — форма ушла сразу, и на месте снова кнопка «Ответить».
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.queryByLabelText(say.ui('answer.fieldLabel'))).toBeNull();
    expect(screen.getByRole('button', { name: say.ui('answer.open') })).toBeInTheDocument();
  });

  it('«Отмена» на непустом черновике спрашивает и выбрасывает его по подтверждению', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'Хочу проверить отмену.');

    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    const dialog = await screen.findByRole('alertdialog', {
      name: say.ui('composer.discardTitle'),
    });
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue(
      'Хочу проверить отмену.',
    );

    await user.click(
      within(dialog).getByRole('button', { name: say.ui('composer.discardConfirm') }),
    );

    // Свернулась, и черновик пропал не только из вида: открыв форму заново, поле пусто.
    expect(screen.queryByLabelText(say.ui('answer.fieldLabel'))).toBeNull();
    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('');

    expect(posts()).toHaveLength(0);
  });

  it('«Продолжить писать» закрывает диалог и оставляет черновик как был', async () => {
    inbox();
    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'Ещё дописываю.');
    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: say.ui('composer.keepWriting') }));

    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('Ещё дописываю.');
  });
});

describe('входящая: мои замечания', () => {
  /** Входящая, где вопросов нет, а замечания есть: две половины экрана независимы. */
  function inboxWithRemarks() {
    const asked: URL[] = [];

    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, ({ request }) => {
        asked.push(new URL(request.url));
        return collection([remarkEntry(8, 'DEMO-1', 'Дыры в нумерации сбивают с толку')]);
      }),
    );

    return asked;
  }

  it('пустой отбор вопросов говорит о несовпадении, а не о том, что агенты не ждут', async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      // Бэкенд отбирает как настоящий: неблокирующий вопрос под условие не подходит.
      http.get(`${API}/api/v1/questions`, ({ request }) => {
        const blocking = new URL(request.url).searchParams.get('blocking') === 'true';
        return collection(blocking ? [] : [questionEntry(8, 'DEMO-4', false)]);
      }),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions?blocking=true');

    // Вывод обо всей входящей по отобранной выдаче не делается, а условие названо
    // поимённо в самом сообщении: человек мог о нём забыть.
    const condition = say.questions('condition.blocking');
    const empty = await screen.findByText(
      say.questions('emptyByFilter', { conditions: condition }),
    );
    expect(empty).toHaveTextContent(condition);
    expect(screen.queryByText(say.questions('noQuestions'))).not.toBeInTheDocument();

    // И снимается на месте, вместе с адресом.
    await user.click(screen.getAllByRole('button', { name: say.questions('resetFilter') })[0]!);
    expect(
      await screen.findByText(
        new RegExp(`${say.questions('questionLabel', { reference: 'DEMO-4#8' })}|DEMO-4#8`),
      ),
    ).toBeInTheDocument();
    expect(address.current).not.toContain('blocking=true');
  });

  it('пустая половина замечаний под отбором очереди не выдумывает историю', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      // Замечание есть, но в другой очереди: под условие оно не подходит.
      http.get(`${API}/api/v1/remarks`, ({ request }) => {
        const queue = new URL(request.url).searchParams.get('queue');
        return collection(queue === 'TRK' ? [] : [remarkEntry(8, 'DEMO-1')]);
      }),
    );

    renderApp('/questions?queue=TRK');

    await waitFor(() => {
      expect(
        screen.getAllByText(
          say.questions('emptyByFilter', {
            conditions: say.questions('condition.queue', { queue: 'TRK' }),
          }),
        ).length,
      ).toBeGreaterThan(0);
    });
    // Вывод обо всей входящей по отобранной выдаче не делается: «неразобранных
    // замечаний нет» — утверждение обо всём, и по отбору оно не звучит.
    expect(screen.queryByText(say.questions('noRemarks'))).not.toBeInTheDocument();
  });

  it('без отбора пустая половина замечаний говорит нейтрально', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions');

    expect(await screen.findByText(say.questions('noRemarks'))).toBeInTheDocument();
    // И обратно: отбора нет — значит нечего и снимать, объяснения по отбору тоже нет.
    expect(screen.queryByRole('button', { name: say.questions('resetFilter') })).toBeNull();
  });

  it('ссылка вопроса открывает свою запись, а не только задачу', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([questionEntry(12, 'DEMO-4', true)])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions');

    expect(await screen.findByRole('link', { name: 'DEMO-4#12' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4?entry=12',
    );
  });

  it('показывает мои неразобранные замечания и ведёт в их задачи', async () => {
    const asked = inboxWithRemarks();
    renderApp('/questions');

    // Ждём саму строку, а не заголовок секции: секция рисуется сразу, а замечания
    // приезжают вторым запросом — после того, как первый кадр сказал, кто вошёл.
    const row = await screen.findByText(/Дыры в нумерации/);
    const section = row.closest('section') as HTMLElement;
    expect(within(section).getByText(say.questions('awaitingResolution'))).toBeInTheDocument();
    // Ссылка называет запись и её же открывает: подпись `KEY#N` без номера в адресе
    // обещала бы одно, а вела в другое место.
    expect(within(section).getByRole('link', { name: 'DEMO-1#8' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-1?entry=8',
    );

    // «Мои» — это подпись автора: у замечания нет адресата, и бэкенд сам его не
    // подставит. Имя берётся из первого кадра, а не набирается человеком.
    await waitFor(() => expect(asked).not.toHaveLength(0));
    expect(asked.at(-1)?.searchParams.get('author')).toBe('owner');
    expect(asked.at(-1)?.searchParams.get('open')).toBe('true');
  });

  it('пустая половина говорит словами, а не пустотой', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions');

    expect(await screen.findByText(say.questions('noRemarks'))).toBeInTheDocument();
    expect(screen.getByText(say.questions('noQuestions'))).toBeInTheDocument();
  });
});

describe('история вопросов', () => {
  /** Отвеченный вопрос с двумя ответами и открытый блокирующий — от свежих к старым. */
  function history() {
    const answered = {
      ...questionEntry(4, 'DEMO-4', true),
      answers: [
        answerEntry(9, 'DEMO-4', 4, 'Храним вечно: дело неизменяемо.'),
        answerEntry(11, 'DEMO-4', 4, 'И архив раз в год.'),
      ],
    };
    const open = { ...questionEntry(12, 'DEMO-3', true), answers: [] };
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, ({ request }) => {
        const url = new URL(request.url);
        sent.push({ url, key: null, body: null });
        return collection(url.searchParams.get('open') === 'false' ? [open, answered] : []);
      }),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );
  }

  function lastQuestionsCall() {
    return sent.filter((call) => call.url.pathname.endsWith('/questions')).at(-1);
  }

  it('без параметров экран остаётся входящей, а история — вторым видом', async () => {
    history();
    renderApp('/questions');

    expect(await screen.findByText(say.questions('noQuestions'))).toBeInTheDocument();
    const views = screen.getByRole('navigation', { name: say.questions('view.label') });
    expect(within(views).getByRole('link', { name: say.questions('view.inbox') })).toHaveAttribute(
      'aria-current',
      'true',
    );
    // Входящая спрашивает то же, что и до истории: открытые, без порядка и без «кому угодно».
    const call = lastQuestionsCall();
    expect(call?.url.searchParams.get('open')).toBe('true');
    expect(call?.url.searchParams.has('order')).toBe(false);
    expect(call?.url.searchParams.has('any_addressee')).toBe(false);
  });

  it('переход в историю показывает вопросы с ответами и ссылками на записи ответов', async () => {
    history();
    const user = userEvent.setup();
    renderApp('/questions');

    await user.click(await screen.findByRole('link', { name: say.questions('view.history') }));
    expect(address.current).toContain('view=history');

    const answered = await screen.findByRole('article', {
      name: say.questions('questionLabel', { reference: 'DEMO-4#4' }),
    });
    expect(answered).toHaveAttribute('data-answered', 'true');
    // У отвеченного вопроса работа не стоит: красного нет, хотя вопрос был блокирующим.
    expect(answered).not.toHaveAttribute('data-blocking');
    expect(within(answered).getByText(say.questions('answered'))).toBeInTheDocument();

    const answers = within(answered).getByRole('list', {
      name: say.questions('answersLabel', { reference: 'DEMO-4#4' }),
    });
    expect(within(answers).getByText('Храним вечно: дело неизменяемо.')).toBeInTheDocument();
    expect(within(answers).getByRole('link', { name: 'DEMO-4#9' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4?entry=9',
    );
    expect(within(answers).getByRole('link', { name: 'DEMO-4#11' })).toBeInTheDocument();

    // Отвечать из истории нельзя — ни у отвеченного, ни у открытого.
    expect(screen.queryByRole('button', { name: say.ui('answer.open') })).toBeNull();

    const open = screen.getByRole('article', {
      name: say.questions('questionLabel', { reference: 'DEMO-3#12' }),
    });
    expect(open).toHaveAttribute('data-answered', 'false');
    expect(open).toHaveAttribute('data-blocking', 'true');
    expect(within(open).getByText(say.questions('noAnswerYet'))).toBeInTheDocument();

    // Порядок и ответы считает бэкенд: страница только просит историю.
    const call = lastQuestionsCall();
    expect(call?.url.searchParams.get('open')).toBe('false');
    expect(call?.url.searchParams.get('order')).toBe('newest');
    expect(call?.url.searchParams.has('any_addressee')).toBe(false);
  });

  it('флажок «только мне» снимает условие адресата и держится адресом', async () => {
    history();
    const user = userEvent.setup();
    renderApp('/questions?view=history');

    const onlyMine = await screen.findByRole('checkbox', { name: say.questions('onlyMine') });
    expect(onlyMine).toBeChecked();
    await user.click(onlyMine);

    await waitFor(() =>
      expect(lastQuestionsCall()?.url.searchParams.get('any_addressee')).toBe('true'),
    );
    expect(address.current).toContain('to=anyone');
  });

  it('пустая история говорит словами, чья она', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
    );
    renderApp('/questions?view=history');
    expect(await screen.findByText(say.questions('noHistory'))).toBeInTheDocument();
  });
});
