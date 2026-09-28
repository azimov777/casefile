import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  API,
  accessToken,
  bootstrap,
  collection,
  data,
  failure,
  questionEntry,
  task,
  taskDetails,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';

/** Ключ сеанса набора `task`: экрану «Начало» больше и не нужно. */
const SESSION = 'trk_session_secret_of_the_interface';

/** Учётная запись владельца установки со своим состоянием знакомства (`TRK-369`). */
function account(status: 'pending' | 'completed' | 'skipped' = 'pending') {
  return {
    id: '55555555-5555-5555-5555-555555555555',
    email: 'owner@localhost',
    participant: 'owner',
    is_admin: true,
    has_password: false,
    disabled_at: null,
    onboarding: { status, hints: { hidden_all: false, hidden: [] as string[] } },
    created_by: { kind: 'tracker' as const, signature: null },
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
  };
}

/**
 * Свежая установка по умолчанию: агента не подключали, задача в работе не взята,
 * вопрос человеку не отвечен — три новых запроса шагов (`TRK-378`) отвечают пусто,
 * пока тест не назовёт своё.
 */
function signedIn(status: Parameters<typeof account>[0] = 'pending') {
  setToken(SESSION);
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account(status) }))),
    http.get(`${API}/api/v1/tasks`, () => collection([])),
    http.get(`${API}/api/v1/tokens`, () => collection([])),
    http.get(`${API}/api/v1/questions`, () => collection([])),
  );
}

/** Учебная задача открыта, проект не в архиве: блок «Знакомство» показан. */
function tutorialOpen() {
  server.use(http.get(`${API}/api/v1/tasks/START-1`, () => data(taskPackage('START-1'))));
}

function tutorialMissing() {
  server.use(
    http.get(`${API}/api/v1/tasks/START-1`, () => failure('task_not_found', 404, 'Task not found')),
  );
}

function tutorialArchived() {
  server.use(
    http.get(`${API}/api/v1/tasks/START-1`, () =>
      data(
        taskPackage('START-1', {
          task: taskDetails('START-1', {
            project: {
              key: 'START',
              title: 'Знакомство',
              description: '',
              archived_at: '2026-09-20T10:00:00Z',
            },
          }),
        }),
      ),
    ),
  );
}

function tutorialClosed() {
  server.use(
    http.get(`${API}/api/v1/tasks/START-1`, () =>
      data(taskPackage('START-1', { task: taskDetails('START-1', { status: 'done' }) })),
    ),
  );
}

/** Раздел по заголовку второго уровня. */
function section(name: string) {
  return screen.getByRole('heading', { level: 2, name }).closest('section');
}

/**
 * Блок трёх шагов (`TRK-378`), внутри содержимого экрана: `within(main)`, а не по всей
 * странице, — иначе поиск ловит пункт «Начало» боковой панели (та же ссылка по смыслу,
 * но не то же место; предупреждение координатора после падения слияния `TRK-377`).
 */
function stepList() {
  const main = screen.getByRole('main');
  return within(main).getByRole('list', { name: say.start('steps.label') });
}

function stepItems() {
  return within(stepList()).getAllByRole('listitem');
}

describe('экран «Начало»', () => {
  it('отвечает на четыре вопроса по порядку TRK-360#14', async () => {
    signedIn();
    tutorialMissing();
    renderApp('/start');

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') }),
    ).toBeInTheDocument();

    const headings = await screen.findAllByRole('heading', { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      say.start('sections.why.title'),
      say.start('sections.source.title'),
      say.start('sections.tellAgent.title'),
      say.start('sections.you.title'),
    ]);
  });

  it('фразы «Завести задачи» и «Выполнить задачи» стоят всегда, а между ними — про новую сессию', async () => {
    signedIn();
    tutorialMissing();
    renderApp('/start');

    const tellAgent = section(say.start('sections.tellAgent.title'));
    expect(tellAgent).not.toBeNull();
    const within2 = within(tellAgent as HTMLElement);
    expect(
      within2.queryByRole('heading', { name: say.start('phrases.tutorial.title') }),
    ).not.toBeInTheDocument();

    const items = within2.getAllByRole('heading', { level: 3 });
    expect(items.map((item) => item.textContent)).toEqual([
      say.start('phrases.file.title'),
      say.start('phrases.execute.title'),
    ]);
    // Текст о новой сессии стоит между «Завести задачи» и «Выполнить задачи», не внутри
    // ни одной из них.
    const text = (tellAgent as HTMLElement).textContent ?? '';
    const fileAt = text.indexOf(say.start('phrases.file.title'));
    const sessionAt = text.indexOf(say.start('sections.tellAgent.newSession'));
    const executeAt = text.indexOf(say.start('phrases.execute.title'));
    expect(fileAt).toBeGreaterThan(-1);
    expect(sessionAt).toBeGreaterThan(fileAt);
    expect(executeAt).toBeGreaterThan(sessionAt);
  });

  it.each([
    ['открытая задача учебного проекта', tutorialOpen, true],
    ['учебного проекта нет вовсе', tutorialMissing, false],
    ['учебный проект в архиве', tutorialArchived, false],
    ['учебная задача уже закрыта', tutorialClosed, false],
  ] as const)('блок «Знакомство»: %s → показан = %s', async (_label, setUp, expected) => {
    signedIn();
    setUp();
    renderApp('/start');

    await screen.findByRole('heading', { level: 1, name: say.ui('app.start') });
    const heading = screen.queryByRole('heading', { name: say.start('phrases.tutorial.title') });
    if (expected) {
      expect(
        await screen.findByRole('heading', { name: say.start('phrases.tutorial.title') }),
      ).toBeInTheDocument();
    } else {
      // Ни спиннера, ни отказа — блок просто не появляется (constraints TRK-361).
      await screen.findByRole('heading', { name: say.start('phrases.file.title') });
      expect(heading).not.toBeInTheDocument();
    }
  });

  it('кнопка копирования каждой из трёх фраз кладёт в буфер её текст дословно', async () => {
    signedIn();
    tutorialOpen();
    const user = userEvent.setup();
    renderApp('/start');

    await screen.findByRole('heading', { name: say.start('phrases.tutorial.title') });

    const phrases: { key: 'tutorial' | 'file' | 'execute' }[] = [
      { key: 'tutorial' },
      { key: 'file' },
      { key: 'execute' },
    ];

    for (const { key } of phrases) {
      const label = say.start(`phrases.${key}.label`);
      await user.click(screen.getByRole('button', { name: say.ui('copyBlock.label', { label }) }));
      expect(await navigator.clipboard.readText()).toBe(say.start(`phrases.${key}.text`));
    }
  });

  it('«Пропустить» ставит `skipped` и уходит на список задач', async () => {
    signedIn();
    tutorialMissing();
    let body: unknown = null;
    server.use(
      http.patch(`${API}/api/v1/accounts/:id/onboarding`, async ({ request, params }) => {
        body = { id: params.id, ...((await request.json()) as object) };
        return data(account('skipped'));
      }),
    );
    const user = userEvent.setup();
    renderApp('/start');

    await user.click(await screen.findByRole('button', { name: say.start('actions.skip') }));

    await waitFor(() => expect(address.current).toBe('/tasks'));
    expect(body).toEqual({ id: account().id, status: 'skipped' });
  });

  it('«Я разобрался» ставит `completed` и уходит на список задач', async () => {
    signedIn();
    tutorialMissing();
    let body: unknown = null;
    server.use(
      http.patch(`${API}/api/v1/accounts/:id/onboarding`, async ({ request, params }) => {
        body = { id: params.id, ...((await request.json()) as object) };
        return data(account('completed'));
      }),
    );
    const user = userEvent.setup();
    renderApp('/start');

    await user.click(await screen.findByRole('button', { name: say.start('actions.complete') }));

    await waitFor(() => expect(address.current).toBe('/tasks'));
    expect(body).toEqual({ id: account().id, status: 'completed' });
  });

  it('пункт «Начало» в панели открывает экран любым состоянием знакомства', async () => {
    signedIn('completed');
    tutorialMissing();
    const user = userEvent.setup();
    renderApp('/tasks');

    await user.click(await screen.findByRole('link', { name: say.ui('app.start') }));

    expect(address.current).toBe('/start');
    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') }),
    ).toBeInTheDocument();
  });

  describe('три шага с отметкой по фактам установки (TRK-378)', () => {
    /** Что и куда ушло: ждём, пока все три новых запроса шагов отработают. */
    function trackedSignedIn(status: Parameters<typeof account>[0] = 'pending') {
      const seen = new Set<string>();
      setToken(SESSION);
      server.use(
        http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account(status) }))),
        http.get(`${API}/api/v1/tasks`, ({ request }) => {
          seen.add(new URL(request.url).pathname);
          return collection([]);
        }),
        http.get(`${API}/api/v1/tokens`, ({ request }) => {
          seen.add(new URL(request.url).pathname);
          return collection([]);
        }),
        http.get(`${API}/api/v1/questions`, ({ request }) => {
          seen.add(new URL(request.url).pathname);
          return collection([]);
        }),
      );
      return seen;
    }

    it('блок стоит сразу под заголовком, перед «Зачем это», и виден по порядку', async () => {
      signedIn();
      tutorialMissing();
      renderApp('/start');

      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') });
      const items = stepItems();
      expect(items).toHaveLength(3);
      expect(items.map((item) => item.textContent)).toEqual([
        expect.stringContaining(say.start('steps.connect.title')),
        expect.stringContaining(say.start('steps.tellAgent.title')),
        expect.stringContaining(say.start('steps.watch.title')),
      ]);

      // Список шагов стоит перед первым разделом («Зачем это») в разметке — сразу под
      // заголовком экрана, а не где-то ниже (constraints задачи).
      const main = screen.getByRole('main');
      const children = Array.from(main.children);
      const listAt = children.findIndex((child) => child.tagName === 'OL');
      const whyAt = children.findIndex((child) => child.tagName === 'SECTION');
      expect(listAt).toBeGreaterThanOrEqual(0);
      expect(whyAt).toBeGreaterThan(listAt);
    });

    it('свежая установка: ни один из трёх шагов не отмечен «сделано», первый ведёт на /connect, третий — на /questions', async () => {
      const seen = trackedSignedIn();
      tutorialMissing();
      renderApp('/start');

      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') });
      await waitFor(() => {
        expect(seen).toEqual(new Set(['/api/v1/tasks', '/api/v1/tokens', '/api/v1/questions']));
      });

      const items = stepItems();
      expect(
        within(items[0]!).getByRole('link', { name: say.start('steps.connect.title') }),
      ).toHaveAttribute('href', '/connect');
      expect(
        within(items[2]!).getByRole('link', { name: say.start('steps.watch.title') }),
      ).toHaveAttribute('href', '/questions');

      for (const item of items) {
        expect(within(item).queryByText(say.start('steps.done'))).not.toBeInTheDocument();
      }
    });

    it('агентом ходили, задача в работе есть, вопрос отвечен — у всех трёх шагов отметка «сделано»', async () => {
      setToken(SESSION);
      server.use(
        http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account() }))),
        http.get(`${API}/api/v1/tokens`, () =>
          collection([
            // Действующий общий токен агента: `participant` пуст — тем и пользуется агент.
            accessToken({
              id: 'a1111111-1111-1111-1111-111111111111',
              participant: null,
              created_by: { kind: 'human', signature: 'owner' },
              last_used_at: '2026-09-27T10:00:00Z',
            }),
            // Шум: отозванный токен агента — им уже нельзя ходить.
            accessToken({
              id: 'a2222222-2222-2222-2222-222222222222',
              participant: 'claude',
              created_by: { kind: 'agent', signature: 'claude' },
              last_used_at: '2026-09-27T09:00:00Z',
              revoked_at: '2026-09-27T09:30:00Z',
            }),
            // Шум: токен человека — говорит не от имени агента.
            accessToken({
              id: 'a3333333-3333-3333-3333-333333333333',
              participant: 'owner',
              created_by: { kind: 'human', signature: 'owner' },
              last_used_at: '2026-09-27T09:00:00Z',
            }),
          ]),
        ),
        http.get(`${API}/api/v1/tasks`, () =>
          collection([task('DEMO-1', { status: 'in_progress' })]),
        ),
        http.get(`${API}/api/v1/questions`, () => collection([questionEntry(4, 'DEMO-4')])),
      );
      tutorialMissing();
      renderApp('/start');

      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') });

      await waitFor(() => {
        for (const item of stepItems()) {
          expect(within(item).getByText(say.start('steps.done'))).toBeInTheDocument();
        }
      });
    });

    it('отозванный токен агента и токен человека сами по себе первый шаг не отмечают', async () => {
      setToken(SESSION);
      server.use(
        http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account() }))),
        http.get(`${API}/api/v1/tokens`, () =>
          collection([
            accessToken({
              id: 'b1111111-1111-1111-1111-111111111111',
              participant: 'claude',
              created_by: { kind: 'agent', signature: 'claude' },
              last_used_at: '2026-09-27T09:00:00Z',
              revoked_at: '2026-09-27T09:30:00Z',
            }),
            accessToken({
              id: 'b2222222-2222-2222-2222-222222222222',
              participant: 'owner',
              created_by: { kind: 'human', signature: 'owner' },
              last_used_at: '2026-09-27T09:00:00Z',
            }),
          ]),
        ),
        http.get(`${API}/api/v1/tasks`, () => collection([])),
        http.get(`${API}/api/v1/questions`, () => collection([])),
      );
      tutorialMissing();
      renderApp('/start');

      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') });

      await waitFor(() => {
        expect(
          within(stepItems()[0]!).queryByText(say.start('steps.done')),
        ).not.toBeInTheDocument();
      });
    });

    it('запрос токенов отвечает отказом: первый шаг без отметки, остальной экран как обычно', async () => {
      setToken(SESSION);
      server.use(
        http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account() }))),
        http.get(`${API}/api/v1/tokens`, () => failure('database_unavailable', 503, 'Boom')),
        http.get(`${API}/api/v1/tasks`, () => collection([])),
        http.get(`${API}/api/v1/questions`, () => collection([])),
      );
      tutorialMissing();
      renderApp('/start');

      await screen.findByRole('heading', { level: 1, name: say.ui('app.start') });

      // Экран остальное показывает как обычно: четыре раздела, три шага, свои ссылки.
      expect(await screen.findAllByRole('heading', { level: 2 })).toHaveLength(4);
      const items = stepItems();
      expect(items).toHaveLength(3);
      expect(
        within(items[0]!).getByRole('link', { name: say.start('steps.connect.title') }),
      ).toHaveAttribute('href', '/connect');

      await waitFor(() => {
        expect(within(items[0]!).queryByText(say.start('steps.done'))).not.toBeInTheDocument();
      });
    });

    it.each(['ru', 'en'] as const)(
      'тексты «Зачем это» и «Откуда берутся задачи» совпадают дословно с «Контекстом» задачи TRK-378 (%s)',
      async (language) => {
        signedIn();
        tutorialMissing();
        renderApp('/start', { language });

        const why = await screen.findByRole('heading', {
          level: 2,
          name: say.start('sections.why.title'),
        });
        const source = screen.getByRole('heading', {
          level: 2,
          name: say.start('sections.source.title'),
        });

        const expected =
          language === 'ru'
            ? {
                why: 'Агент забывает всё между сессиями: следующий начинает с нуля, заново читает код и повторяет то, что уже не сработало. Casefile даёт каждой задаче дело — журнал решений, попыток, находок и вопросов. Следующий агент читает дело и продолжает с того места, где остановился предыдущий. Вы видите на доске, что делает каждый агент, и отвечаете на их вопросы.',
                source:
                  'Задачи заводят и ведут агенты — по вашей просьбе в их чате. Кнопки «создать задачу» здесь нет намеренно: вы говорите агенту, что нужно, а он раскладывает работу на задачи.',
              }
            : {
                why: 'AI agents forget everything between sessions: the next one starts from scratch, re-reads the code and retries what already failed. Casefile gives every task a case file — a log of decisions, attempts, findings and questions. The next agent reads the case and picks up exactly where the last one stopped. You watch on the board what every agent is doing, and answer their questions.',
                source:
                  'Agents create and carry the tasks — at your request, in their own chat. There is no “create task” button here on purpose: you tell the agent what you need, and it splits the work into tasks.',
              };

        expect(why.closest('section')?.querySelector('p')?.textContent).toBe(expected.why);
        expect(source.closest('section')?.querySelector('p')?.textContent).toBe(expected.source);
      },
    );
  });
});
