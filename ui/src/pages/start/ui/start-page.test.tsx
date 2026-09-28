import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  failure,
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

function signedIn(status: Parameters<typeof account>[0] = 'pending') {
  setToken(SESSION);
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ account: account(status) }))),
    http.get(`${API}/api/v1/tasks`, () => collection([])),
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
});
