import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  accessToken,
  bootstrap,
  collection,
  data,
  failure,
  participant,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';
import { connectionSnippets } from '@/features/connect-agent';

/** Ключ, которым нарисован экран: тот же идентификатор придёт в `bootstrap`. */
const SESSION_ID = '33333333-3333-3333-3333-333333333333';
const SESSION = 'trk_session_secret_of_the_interface';
const ADDRESS = 'https://mcp.example.test:9443/casefile/mcp';

/** Секрет, который бэкенд отдаёт один раз при выпуске. */
const SECRET = 'trk_issued_secret_seen_once_and_never_again';

/** Что уходило на бэкенд за прогон: метод и путь. */
let sent: string[] = [];
/** Ключи повтора, с которыми уходил выпуск, по порядку попыток. */
let issueKeys: (string | null)[] = [];

const UI_TOKEN = accessToken({
  id: SESSION_ID,
  name: 'local-ui',
  scope: 'main',
  participant: 'owner',
  last_used_at: '2026-09-01T10:30:00Z',
});

const AGENT_TOKEN = accessToken({
  id: '77777777-7777-7777-7777-777777777777',
  name: 'local-agent',
  scope: 'main',
  participant: 'agent',
});

const REVOKED_TOKEN = accessToken({
  id: '88888888-8888-8888-8888-888888888888',
  name: 'проверка 6 сентября',
  scope: 'task',
  participant: null,
  revoked_at: '2026-09-06T12:00:00Z',
});

/** Ответ выпуска: тот же токен, что придёт в список, плюс секрет. */
function issued(overrides: Record<string, unknown> = {}) {
  return {
    ...accessToken({
      id: '99999999-9999-9999-9999-999999999999',
      name: 'nightly_agent на ноутбуке',
      scope: 'task',
      participant: 'nightly_agent',
    }),
    secret: SECRET,
    ...overrides,
  };
}

/** Экран с ключом названного набора: первый кадр, список доступов, реестр, установка. */
function installation(scope: 'task' | 'main' = 'main', tokens = [UI_TOKEN, AGENT_TOKEN]) {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () =>
      data(bootstrap({ token: { id: SESSION_ID, scope } })),
    ),
    http.get(`${API}/api/v1/tokens`, () => collection(tokens)),
    http.get(`${API}/api/v1/participants`, () =>
      collection([participant('nightly_agent'), participant('owner', { kind: 'human' })]),
    ),
    http.get(`${API}/api/v1/installation`, () => data({ mcp_url: ADDRESS })),
    http.get(`${API}/api/v1/tasks`, () => collection([])),
  );
}

/** Строка доступа по имени токена. */
function row(name: string): HTMLElement {
  return screen.getByRole('article', { name: say.ui('token.label', { name }) });
}

beforeEach(() => {
  sent = [];
  issueKeys = [];
  setToken(SESSION);
  server.events.on('request:start', ({ request }) => {
    sent.push(`${request.method} ${new URL(request.url).pathname}`);
  });
});

/** Запросы записи: всё, кроме чтения. */
function writes(): string[] {
  return sent.filter((call) => !call.startsWith('GET '));
}

describe('экран «Доступы»', () => {
  it('открывается из навигации и показывает доступы установки, отмечая ключ этого сеанса', async () => {
    installation('main', [UI_TOKEN, AGENT_TOKEN, REVOKED_TOKEN]);
    const user = userEvent.setup();
    renderApp('/tasks');

    await user.click(await screen.findByRole('link', { name: say.ui('app.access') }));

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.access') }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: say.ui('app.access') })).toHaveAttribute(
      'aria-current',
      'page',
    );

    const own = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'local-ui' }),
    });
    // Ключ сеанса отмечен, и отмечен ровно один.
    expect(within(own).getByText(say.ui('token.thisSession'))).toBeInTheDocument();
    expect(screen.getAllByText(say.ui('token.thisSession'))).toHaveLength(1);

    // Чей доступ, что открывает, когда им ходили и жив ли он — в самой строке.
    expect(within(own).getByText('owner')).toBeInTheDocument();
    expect(within(own).getByText('main')).toBeInTheDocument();
    expect(within(row('local-agent')).getByText(say.ui('token.neverUsed'))).toBeInTheDocument();

    const revoked = row('проверка 6 сентября');
    expect(within(revoked).getByText(say.ui('token.revoked'))).toBeInTheDocument();
    expect(within(revoked).getByText(say.ui('token.shared'))).toBeInTheDocument();
    // Отозванный доступ отзывать нечего: кнопки у него нет.
    expect(within(revoked).queryByRole('button')).toBeNull();
  });

  it('ключ набора `task`: список виден, действия недоступны с объяснением, запросов записи нет', async () => {
    installation('task');
    renderApp('/access');

    expect(await screen.findByRole('article', { name: /local-ui/ })).toBeInTheDocument();

    const newAgent = screen.getByRole('button', { name: say.access('actions.newAgent') });
    const issue = screen.getByRole('button', { name: say.access('actions.issue') });
    expect(newAgent).toBeDisabled();
    expect(issue).toBeDisabled();

    // Запрет объяснён, и запрещённые кнопки ссылаются на то же объяснение.
    const explanation = screen.getByText(say.access('closed.text', { scope: 'task' }));
    expect(newAgent).toHaveAttribute('aria-describedby', explanation.id);
    expect(issue).toHaveAttribute('aria-describedby', explanation.id);

    // Отзыв с таким ключом не предлагается вовсе.
    expect(screen.queryByRole('button', { name: say.access('revoke.action') })).toBeNull();
    // И ни одного запроса записи: отказ `403` проверкой прав не служит.
    expect(writes()).toEqual([]);
  });

  it('выпуск показывает секрет один раз вместе с фрагментами, а закрытие окна его уносит', async () => {
    installation('main');
    let body: Record<string, unknown> = {};
    server.use(
      http.post(`${API}/api/v1/tokens`, async ({ request }) => {
        issueKeys.push(request.headers.get('Idempotency-Key'));
        body = (await request.json()) as Record<string, unknown>;
        return data(issued(), 201);
      }),
    );
    const user = userEvent.setup();
    const { container, queryClient } = renderApp('/access');

    await user.click(await screen.findByRole('button', { name: say.access('actions.issue') }));

    await user.selectOptions(
      await screen.findByLabelText(say.access('issue.whomLabel')),
      'nightly_agent',
    );
    await user.type(screen.getByLabelText(say.access('issue.nameLabel')), 'ноутбук');
    await user.click(screen.getByRole('button', { name: say.access('issue.submit') }));

    // Умолчание набора — `task`, и оно уехало на бэкенд как есть.
    expect(body).toEqual({ name: 'ноутбук', scope: 'task', participant: 'nightly_agent' });

    // Секрет показан — и сам по себе, и внутри фрагментов подключения.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(SECRET)).toBeInTheDocument();
    expect(
      await within(dialog).findByText(
        connectionSnippets({ mcpUrl: ADDRESS, token: SECRET, labelled: false }).claudeCode,
      ),
    ).toBeInTheDocument();
    // Человеку сказано, что второго показа не будет.
    expect(within(dialog).getByText(say.access('secret.onlyOnce'))).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: say.access('secret.done') }));

    // После закрытия окна секрета нет ни на экране, ни в хранилищах, ни в кэшах.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.body.textContent ?? '').not.toContain(SECRET);
    expect(container.innerHTML).not.toContain(SECRET);
    expect(JSON.stringify(window.localStorage)).not.toContain(SECRET);
    expect(JSON.stringify(window.sessionStorage)).not.toContain(SECRET);
    expect(
      JSON.stringify(
        queryClient
          .getQueryCache()
          .getAll()
          .map((query) => query.state),
      ),
    ).not.toContain(SECRET);
    expect(
      JSON.stringify(
        queryClient
          .getMutationCache()
          .getAll()
          .map((mutation) => mutation.state),
      ),
    ).not.toContain(SECRET);
    // И в адрес страницы он тоже не попадал.
    expect(window.location.href).not.toContain(SECRET);
  });

  it('повтор того же выпуска идёт с тем же ключом повтора, а исправленный — с новым', async () => {
    installation('main');
    let left = 1;
    server.use(
      http.post(`${API}/api/v1/tokens`, ({ request }) => {
        issueKeys.push(request.headers.get('Idempotency-Key'));
        if (left > 0) {
          left -= 1;
          return failure('database_unavailable', 503, 'Database is not available');
        }
        return data(issued(), 201);
      }),
    );
    const user = userEvent.setup();
    renderApp('/access');

    await user.click(await screen.findByRole('button', { name: say.access('actions.issue') }));
    await user.selectOptions(
      await screen.findByLabelText(say.access('issue.whomLabel')),
      'nightly_agent',
    );
    const name = screen.getByLabelText(say.access('issue.nameLabel'));
    await user.type(name, 'ноутбук');

    const submit = screen.getByRole('button', { name: say.access('issue.submit') });
    await user.click(submit);

    // Отказ назван по причине, и сказано, что повтор второго токена не заведёт.
    expect(
      await screen.findByText(say.errors('database_unavailable'), { exact: false }),
    ).toBeInTheDocument();

    await user.click(submit);
    await screen.findByText(SECRET);

    expect(issueKeys).toHaveLength(2);
    expect(issueKeys[0]).toBe(issueKeys[1]);
    expect(issueKeys[0]).not.toBeNull();
  });

  it('исправленный выпуск получает новый ключ повтора: тот же ключ с другим запросом отвергнут бэкендом', async () => {
    installation('main');
    server.use(
      http.post(`${API}/api/v1/tokens`, ({ request }) => {
        issueKeys.push(request.headers.get('Idempotency-Key'));
        return failure('database_unavailable', 503, 'Database is not available');
      }),
    );
    const user = userEvent.setup();
    renderApp('/access');

    await user.click(await screen.findByRole('button', { name: say.access('actions.issue') }));
    await user.selectOptions(
      await screen.findByLabelText(say.access('issue.whomLabel')),
      'nightly_agent',
    );
    const name = screen.getByLabelText(say.access('issue.nameLabel'));
    await user.type(name, 'ноутбук');
    await user.click(screen.getByRole('button', { name: say.access('issue.submit') }));
    await screen.findByText(say.errors('database_unavailable'), { exact: false });

    await user.type(name, ' номер два');
    await user.click(screen.getByRole('button', { name: say.access('issue.submit') }));

    expect(issueKeys).toHaveLength(2);
    expect(issueKeys[0]).not.toBe(issueKeys[1]);
  });

  it('заведение агента объясняет занятое имя и ведёт к выпуску ему токена', async () => {
    installation('main');
    let taken = true;
    const registry = [participant('nightly_agent'), participant('owner', { kind: 'human' })];
    server.use(
      http.get(`${API}/api/v1/participants`, () => collection(registry)),
      http.post(`${API}/api/v1/participants`, () => {
        if (taken) {
          taken = false;
          return failure('participant_name_taken', 409, 'Participant name is already taken', {
            name: 'nightly_agent',
          });
        }
        registry.push(participant('second_agent'));
        return data(participant('second_agent'), 201);
      }),
    );
    const user = userEvent.setup();
    renderApp('/access');

    await user.click(await screen.findByRole('button', { name: say.access('actions.newAgent') }));
    await user.type(screen.getByLabelText(say.access('agent.nameLabel')), 'nightly_agent');
    await user.click(screen.getByRole('button', { name: say.access('agent.submit') }));

    // Отказ назван по причине, а не «что-то пошло не так».
    expect(
      await screen.findByText(say.errors('participant_name_taken'), { exact: false }),
    ).toBeInTheDocument();

    await user.clear(screen.getByLabelText(say.access('agent.nameLabel')));
    await user.type(screen.getByLabelText(say.access('agent.nameLabel')), 'second_agent');
    await user.click(screen.getByRole('button', { name: say.access('agent.submit') }));

    // Заведённый участник — ещё не подключённый агент, и окно ведёт к выпуску.
    expect(
      await screen.findByText(say.access('agent.done', { name: 'second_agent' })),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: say.access('agent.issueNow') }));

    expect(await screen.findByLabelText(say.access('issue.whomLabel'))).toHaveValue('second_agent');
  });

  it('отзыв ключа этого сеанса спрашивает подтверждение и объясняет последствия', async () => {
    installation('main');
    const revoked: string[] = [];
    server.use(
      http.delete(`${API}/api/v1/tokens/:id`, ({ params }) => {
        revoked.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/access');

    const own = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'local-ui' }),
    });
    await user.click(within(own).getByRole('button', { name: say.access('revoke.action') }));

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(say.access('revoke.ownKey'))).toBeInTheDocument();
    // Пока не подтвердили — ни одного запроса записи.
    expect(writes()).toEqual([]);

    await user.click(within(dialog).getByRole('button', { name: say.access('revoke.confirm') }));

    expect(revoked).toEqual([SESSION_ID]);
  });

  it('отзыв чужого доступа объясняет последствия без предупреждения о своём ключе', async () => {
    installation('main');
    const user = userEvent.setup();
    renderApp('/access');

    const agent = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'local-agent' }),
    });
    await user.click(within(agent).getByRole('button', { name: say.access('revoke.action') }));

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(say.access('revoke.intro'))).toBeInTheDocument();
    expect(within(dialog).queryByText(say.access('revoke.ownKey'))).toBeNull();
  });

  it('говорит по-русски целиком', async () => {
    installation('main');
    renderApp('/access', { language: 'ru' });

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.access') }),
    ).toHaveTextContent('Доступы');
    expect(await screen.findByRole('article', { name: /local-ui/ })).toBeInTheDocument();
  });
});
