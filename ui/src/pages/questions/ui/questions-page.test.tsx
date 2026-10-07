import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  answerEntry,
  bootstrap,
  collection,
  data,
  questionEntry,
  remarkEntry,
  task,
  taskPage,
  withdrawalEntry,
} from '@testing/msw/responses';
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
  // Раздел «Требуют внимания» читает список задач (TRK-561); по умолчанию он пуст, а
  // сценарии, которым он нужен, ставят свой ответ поверх.
  server.use(http.get(`${API}/api/v1/tasks`, () => taskPage([])));
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

  it('пустая половина замечаний под отбором проекта не выдумывает историю', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      // Замечание есть, но в другом проекте: под условие оно не подходит.
      http.get(`${API}/api/v1/remarks`, ({ request }) => {
        const project = new URL(request.url).searchParams.get('project');
        return collection(project === 'TRK' ? [] : [remarkEntry(8, 'DEMO-1')]);
      }),
    );

    renderApp('/questions?project=TRK');

    await waitFor(() => {
      expect(
        screen.getAllByText(
          say.questions('emptyByFilter', {
            conditions: say.questions('condition.project', { project: 'TRK' }),
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
  });

  it('раздела прежних вопросов в делах нет и вопросы из дел во входящей не запрашиваются (TRK-683)', async () => {
    const asked: URL[] = [];
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, ({ request }) => {
        asked.push(new URL(request.url));
        return collection([questionEntry(4, 'DEMO-4')]);
      }),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions');

    await screen.findByText(say.questions('noRemarks'));
    expect(screen.queryByRole('heading', { name: 'Вопросы ко мне' })).toBeNull();
    expect(screen.queryByText(/DEMO-4#4\b/)).toBeNull();
    expect(screen.queryByRole('checkbox', { name: 'только блокирующие' })).toBeNull();
    expect(asked).toHaveLength(0);
  });
});

describe('входящая: требуют внимания (TRK-561)', () => {
  it('задача с открытым предупреждением видна в разделе и ведёт в свою карточку', async () => {
    const asked: URL[] = [];
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ open_warnings: 1 }))),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        asked.push(new URL(request.url));
        return taskPage([
          task('DEMO-8', {
            title: 'Подсказка о сгоревшем номере',
            status: 'done',
            features: {
              blocked: false,
              deferred: false,
              open_questions: 0,
              open_blocking_questions: 0,
              open_remarks: 0,
              open_warnings: 1,
              last_summary_at: '2026-09-01T10:00:00Z',
              last_entry_at: '2026-09-01T10:00:00Z',
            },
          }),
        ]);
      }),
    );

    renderApp('/questions');

    const section = await screen.findByRole('region', { name: say.questions('attentionTitle') });
    expect(await within(section).findByText('Подсказка о сгоревшем номере')).toBeInTheDocument();
    expect(within(section).getByRole('link', { name: 'DEMO-8' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-8',
    );
    expect(within(section).getByText(say.questions('awaitingDecision'))).toBeInTheDocument();

    // Раздел — отбор по признаку, от давних к свежим; правила архива в нём нет: задача
    // с открытым предупреждением не архивная по определению.
    expect(asked.at(-1)?.searchParams.get('query')).toBe('open_warnings: > 0');
    expect(asked.at(-1)?.searchParams.getAll('sort')).toEqual(['last_entry_at']);
  });

  it('пустой раздел говорит словами', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    renderApp('/questions');

    expect(await screen.findByText(say.questions('noAttention'))).toBeInTheDocument();
  });
});

describe('пояснение экрана (TRK-362)', () => {
  /** Учётная запись со своим состоянием пояснений: умолчание — как у новой записи. */
  function accountWithHints(hints: { hidden_all?: boolean; hidden?: string[] } = {}) {
    return {
      id: '55555555-5555-5555-5555-555555555555',
      email: 'owner@localhost',
      participant: 'owner',
      is_admin: true,
      has_password: false,
      disabled_at: null,
      onboarding: {
        status: 'completed' as const,
        hints: { hidden_all: false, hidden: [] as string[], ...hints },
      },
      created_by: { kind: 'tracker' as const, signature: null },
      created_at: '2026-09-01T10:00:00Z',
      updated_at: '2026-09-01T10:00:00Z',
    };
  }

  /**
   * Установка со своим состоянием пояснений: `PATCH` меняет то же состояние, которое
   * следом отдаёт `bootstrap`, — так инвалидация после мутации видит настоящий эффект,
   * а не застывшую фикстуру (тем же приёмом, что `inbox()` above для вопросов и ответа).
   */
  function hintsInstallation(initial: { hidden_all?: boolean; hidden?: string[] } = {}) {
    let hints = { hidden_all: false, hidden: [] as string[], ...initial };
    const patches: unknown[] = [];

    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        data(bootstrap({ account: accountWithHints(hints) })),
      ),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
      http.patch(`${API}/api/v1/accounts/:id/onboarding`, async ({ request }) => {
        const body = (await request.json()) as { hints?: Partial<typeof hints> };
        patches.push(body);
        hints = { ...hints, ...body.hints };
        return data(accountWithHints(hints));
      }),
    );

    return patches;
  }

  it.each(['ru', 'en'] as const)(
    'новый человек открывает Входящую и видит пояснение первым блоком, ничего не нажимая (%s)',
    async (language) => {
      hintsInstallation();
      renderApp('/questions', { language });

      const main = screen.getByRole('main');
      const expected =
        language === 'ru'
          ? 'Сюда приходят обсуждения, в которых агент ждёт вашего ответа: вся переписка по одному узкому вопросу с итогом сверху. Отвечаете вы на экране обсуждения, и агент читает ответ оттуда; пока в обсуждении есть вопрос без ответа, привязанные к нему задачи стоят. Если агент уже остановился, напишите ему в его чате, что ответили.'
          : 'Discussions where an agent waits for your answer arrive here: the whole conversation about one narrow question, with a conclusion on top. You answer on the discussion screen and the agent reads the answer from there; while a discussion has an unanswered question, the tasks attached to it stand still. If the agent has already stopped, tell it in its chat that you have answered.';

      const explanation = await within(main).findByText(expected);
      expect(explanation).toBeInTheDocument();
      // Первый блок области содержимого: ничего не стоит перед ним в разметке `main`.
      expect(main.firstElementChild).toBe(explanation.closest('div'));

      within(main).getByRole('button', { name: say.ui('explanation.close') });
      within(main).getByRole('button', { name: say.ui('explanation.hideAll') });
    },
  );

  it('закрытие пояснения шлёт PATCH с прежними ключами и «questions», и оно пропадает из содержимого', async () => {
    const patches = hintsInstallation({ hidden: ['start'] });
    const user = userEvent.setup();
    renderApp('/questions');

    const main = screen.getByRole('main');
    await within(main).findByText(say.questions('explanation.body'));

    await user.click(within(main).getByRole('button', { name: say.ui('explanation.close') }));

    await waitFor(() =>
      expect(patches.at(-1)).toEqual({ hints: { hidden: ['start', 'questions'] } }),
    );
    await waitFor(() =>
      expect(within(main).queryByText(say.questions('explanation.body'))).not.toBeInTheDocument(),
    );
  });

  it('«Скрыть все пояснения» шлёт hidden_all: true, и пояснение пропадает из содержимого', async () => {
    const patches = hintsInstallation();
    const user = userEvent.setup();
    renderApp('/questions');

    const main = screen.getByRole('main');
    await user.click(
      await within(main).findByRole('button', { name: say.ui('explanation.hideAll') }),
    );

    await waitFor(() => expect(patches.at(-1)).toEqual({ hints: { hidden_all: true } }));
    await waitFor(() =>
      expect(within(main).queryByText(say.questions('explanation.body'))).not.toBeInTheDocument(),
    );
  });

  it.each<[string, { hidden_all: boolean; hidden: string[] }]>([
    ['hidden_all: true', { hidden_all: true, hidden: [] }],
    ['questions в hidden', { hidden_all: false, hidden: ['questions'] }],
  ])('пояснения нет в содержимом: %s', async (_label, hints) => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        data(bootstrap({ account: accountWithHints(hints) })),
      ),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );
    renderApp('/questions');

    // Экран дорисовался (входящая точно есть), а пояснения в его содержимом нет.
    const main = await screen.findByRole('main');
    await screen.findByText(say.questions('noRemarks'));
    expect(within(main).queryByText(say.questions('explanation.body'))).not.toBeInTheDocument();
  });

  it('человек без учётной записи не видит пояснения на Входящей', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );
    renderApp('/questions');

    const main = await screen.findByRole('main');
    await screen.findByText(say.questions('noRemarks'));
    expect(within(main).queryByText(say.questions('explanation.body'))).not.toBeInTheDocument();
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

    expect(await screen.findByText(say.questions('noRemarks'))).toBeInTheDocument();
    const views = screen.getByRole('navigation', { name: say.questions('view.label') });
    expect(within(views).getByRole('link', { name: say.questions('view.inbox') })).toHaveAttribute(
      'aria-current',
      'true',
    );
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
    expect(within(answered).getByText(say.questions('closedAs.answered'))).toBeInTheDocument();
    expect(answered).toHaveAttribute('data-closed-as', 'answered');
    // Ответ по существу выглядит как до исходов: строки «снят»/«заменён» под ним нет.
    expect(answered.querySelector('[data-answer-outcome]')).toBeNull();

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

  /**
   * Снятый и заменённый вопросы (TRK-552) и один новый открытый. Бэкенд считает снятый
   * вопрос закрытым той же записью `answer`, поэтому во входящую (`open=true`) он не
   * приезжает; подмена отвечает так же — по пустоте `answers`, как и сам бэкенд.
   */
  function withdrawn() {
    const dropped = {
      ...questionEntry(3, 'DEMO-4', true),
      answers: [withdrawalEntry(6, 'DEMO-4', 3, 'Эндпоинт удалён в соседней задаче.')],
    };
    const stale = {
      ...questionEntry(4, 'DEMO-4', true),
      answers: [withdrawalEntry(7, 'DEMO-4', 4, 'Спрашиваю короче.', 5)],
    };
    const fresh = { ...questionEntry(5, 'DEMO-4', false), answers: [] };
    const all = [fresh, stale, dropped];
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ open_questions: 1 }))),
      http.get(`${API}/api/v1/questions`, ({ request }) => {
        const open = new URL(request.url).searchParams.get('open') !== 'false';
        return collection(open ? all.filter((item) => item.answers.length === 0) : all);
      }),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );
  }

  it('снятого и заменённого вопроса во входящей нет', async () => {
    withdrawn();
    renderApp('/questions');

    await screen.findByText(say.questions('noRemarks'));
    expect(screen.queryByText(/DEMO-4#[345]\b/)).toBeNull();
  });

  it('история показывает под вопросом «снят» с причиной', async () => {
    withdrawn();
    renderApp('/questions?view=history');

    const row = await screen.findByRole('article', {
      name: say.questions('questionLabel', { reference: 'DEMO-4#3' }),
    });
    expect(row).toHaveAttribute('data-closed-as', 'withdrawn');
    // Снятый вопрос не держит работу: кромки и плашки «блокирующий» нет.
    expect(row).not.toHaveAttribute('data-blocking');
    // Плашка исхода — в шапке строки; то же слово стоит и в строке исхода под вопросом.
    expect(row.querySelector('header [data-badge="neutral"]')?.textContent).toBe(
      say.questions('closedAs.withdrawn'),
    );

    const outcome = row.querySelector('[data-answer-outcome="withdrawn"]');
    expect(outcome).not.toBeNull();
    expect(outcome?.textContent).toBe(
      `${say.ui('entry.headline.question')}DEMO-4#3${say.ui('entry.headline.withdrawn')}`,
    );
    expect(within(row).getByText('Эндпоинт удалён в соседней задаче.')).toBeInTheDocument();
  });

  it('история показывает «заменён вопросом» со ссылкой на запись заменившего вопроса', async () => {
    withdrawn();
    renderApp('/questions?view=history');

    const row = await screen.findByRole('article', {
      name: say.questions('questionLabel', { reference: 'DEMO-4#4' }),
    });
    expect(row).toHaveAttribute('data-closed-as', 'replaced');
    expect(row.querySelector('header [data-badge="neutral"]')?.textContent).toBe(
      say.questions('closedAs.replaced'),
    );

    const outcome = row.querySelector<HTMLElement>('[data-answer-outcome="replaced"]');
    if (outcome === null) throw new Error('под заменённым вопросом нет строки исхода');
    expect(within(outcome).getByText(say.ui('entry.headline.replacedBy'))).toBeInTheDocument();
    expect(within(outcome).getByRole('link', { name: 'DEMO-4#5' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4?entry=5',
    );
    expect(within(row).getByText('Спрашиваю короче.')).toBeInTheDocument();
  });
});
