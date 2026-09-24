import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
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
import { address, renderApp } from '@testing/render';
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

const STAMPS = { created_at: '2026-09-22T10:00:00Z', updated_at: '2026-09-22T10:00:00Z' };

/** Учётная запись за сеансом: так её отдаёт `GET /api/v1/bootstrap` (TRK-113). */
function account(name: string, isAdmin: boolean) {
  return {
    id: `account-${name}`,
    email: `${name}@example.com`,
    participant: name,
    is_admin: isAdmin,
    has_password: true,
    disabled_at: null,
    created_by: { kind: 'tracker' as const, signature: null },
    ...STAMPS,
  };
}

/**
 * Кто за сеансом: администратор-владелец (так на локальной установке), человек без
 * флага администратора или агент — ключ `main` без учётной записи.
 */
type Who = 'admin' | 'alice' | 'agent';

function signedIn(who: Who) {
  if (who === 'admin') return { account: account('owner', true) };
  if (who === 'alice')
    return {
      participant: participant('alice', { kind: 'human' }),
      account: account('alice', false),
    };
  return { participant: participant('agent'), account: null };
}

/** Адреса запросов списка токенов за прогон: по ним видно, уходил ли `mine`. */
let tokenQueries: URL[] = [];

/** Экран с ключом названного набора: первый кадр, список доступов, реестр, установка. */
function installation(
  scope: 'task' | 'main' = 'main',
  tokens = [UI_TOKEN, AGENT_TOKEN],
  who: Who = 'admin',
) {
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () =>
      data(bootstrap({ token: { id: SESSION_ID, scope }, ...signedIn(who) })),
    ),
    http.get(`${API}/api/v1/tokens`, ({ request }) => {
      tokenQueries.push(new URL(request.url));
      return collection(tokens);
    }),
    http.get(`${API}/api/v1/participants`, () =>
      collection([
        participant('nightly_agent'),
        participant('owner', { kind: 'human' }),
        participant('alice', { kind: 'human' }),
      ]),
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
  tokenQueries = [];
  setToken(SESSION);
  server.events.on('request:start', ({ request }) => {
    sent.push(`${request.method} ${new URL(request.url).pathname}`);
  });
});

// Слушатель снимается после каждого теста: иначе они копятся, и запрос следующего теста
// записывался бы в `sent` столько раз, сколько тестов прошло до него.
afterEach(() => {
  server.events.removeAllListeners();
});

/** Запросы записи: всё, кроме чтения. */
function writes(): string[] {
  return sent.filter((call) => !call.startsWith('GET '));
}

/**
 * Кнопки-действия. Время — переключатель подписи (`aria-pressed`, UI-153), плашка набора —
 * раскрытие пояснения (`aria-expanded`, UI-163): ни то ни другое не действие над доступом.
 */
function actions(scope: HTMLElement): HTMLElement[] {
  return within(scope)
    .queryAllByRole('button')
    .filter(
      (button) => !button.hasAttribute('aria-pressed') && !button.hasAttribute('aria-expanded'),
    );
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

    // Отозванный доступ — в истории, а она свёрнута: раскрывается одним нажатием.
    const toggle = screen.getByRole('button', { name: say.access('tokens.history', { count: 1 }) });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(
      screen.queryByRole('article', {
        name: say.ui('token.label', { name: 'проверка 6 сентября' }),
      }),
    ).toBeNull();
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    const revoked = row('проверка 6 сентября');
    expect(within(revoked).getByText(say.ui('token.revoked'))).toBeInTheDocument();
    expect(within(revoked).getByText(say.ui('token.shared'))).toBeInTheDocument();
    // Отозванный доступ отзывать нечего: кнопки у него нет.
    // Действий нет. Время — переключатель подписи на точное (`aria-pressed`, UI-153),
    // плашка набора — раскрытие пояснения (`aria-expanded`, UI-163): не действия над
    // строкой, и в счёт не идут.
    expect(actions(revoked)).toEqual([]);
  });

  it('действующие идут раньше отозванных, даже если выдача их перемешала', async () => {
    // Порядок выдачи — по времени: отозванный стоит между двумя действующими.
    installation('main', [UI_TOKEN, REVOKED_TOKEN, AGENT_TOKEN]);
    const user = userEvent.setup();
    renderApp('/access');

    const active = await screen.findByRole('region', {
      name: new RegExp(say.access('tokens.active')),
    });
    await within(active).findByRole('article', {
      name: say.ui('token.label', { name: 'local-agent' }),
    });
    // Число действующих — у заголовка, словами для диктора.
    expect(active).toHaveTextContent(say.access('tokens.count', { count: 2 }));
    expect(
      within(active)
        .getAllByRole('article')
        .map((item) => item.getAttribute('aria-label')),
    ).toEqual([
      say.ui('token.label', { name: 'local-ui' }),
      say.ui('token.label', { name: 'local-agent' }),
    ]);

    await user.click(
      screen.getByRole('button', { name: say.access('tokens.history', { count: 1 }) }),
    );
    const articles = screen.getAllByRole('article');
    // В разметке история идёт после всех действующих.
    expect(articles.map((item) => item.dataset.revoked ?? 'active')).toEqual([
      'active',
      'active',
      'true',
    ]);
  });

  it('список дочитывается сам: действующий ключ со второй страницы стоит среди действующих', async () => {
    installation('main');
    const OLD_ACTIVE = accessToken({
      id: '44444444-4444-4444-4444-444444444444',
      name: 'давний агент',
      scope: 'task',
      participant: 'agent',
    });
    server.use(
      http.get(`${API}/api/v1/tokens`, ({ request }) =>
        new URL(request.url).searchParams.get('cursor') === 'page-2'
          ? collection([OLD_ACTIVE])
          : collection([UI_TOKEN, REVOKED_TOKEN], { has_more: true, next_cursor: 'page-2' }),
      ),
    );
    renderApp('/access');

    const active = await screen.findByRole('region', {
      name: new RegExp(say.access('tokens.active')),
    });
    expect(
      await within(active).findByRole('article', {
        name: say.ui('token.label', { name: 'давний агент' }),
      }),
    ).toBeInTheDocument();
    // Кнопки «показать ещё» больше нет: дочитывает экран, а не человек.
    expect(sent.filter((call) => call === 'GET /api/v1/tokens')).toHaveLength(2);
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

describe('чьи токены на экране (TRK-114)', () => {
  /** Ключ Алисы её агенту: выпущен ею, говорит за агента. */
  const ALICE_AGENT = accessToken({
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    name: 'агент Алисы',
    participant: 'nightly_agent',
    created_by: { kind: 'human', signature: 'alice' },
  });
  /** Чужой ключ: выпущен владельцем за его агента. Не администратору его не отдают. */
  const FOREIGN = accessToken({
    id: 'aaaaaaaa-0000-0000-0000-000000000002',
    name: 'агент владельца',
    participant: 'agent',
    created_by: { kind: 'human', signature: 'owner' },
  });

  it('человек без флага администратора: вид «свои» без дорожки, отзыв только своих, выбор без чужих людей', async () => {
    installation('main', [ALICE_AGENT, FOREIGN], 'alice');
    const user = userEvent.setup();
    renderApp('/access');

    expect(await screen.findByText(say.access('introMine'))).toBeInTheDocument();
    expect(screen.queryByText(say.access('intro'))).toBeNull();
    // Второго вида у него нет — нет и дорожки.
    expect(screen.queryByRole('navigation', { name: say.access('view.label') })).toBeNull();
    // Параметр `mine` ему не шлётся: бэкенд и так отдаёт свои.
    expect(tokenQueries.every((url) => !url.searchParams.has('mine'))).toBe(true);

    const own = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'агент Алисы' }),
    });
    expect(within(own).getByRole('button', { name: say.access('revoke.action') })).toBeEnabled();
    // Чужая строка — без кнопки: её отзыв ответил бы `403 not_own_token`.
    // Действий нет. Время — переключатель подписи на точное (`aria-pressed`, UI-153),
    // плашка набора — раскрытие пояснения (`aria-expanded`, UI-163): не действия над
    // строкой, и в счёт не идут.
    expect(actions(row('агент владельца'))).toEqual([]);

    // Выпуск открыт: за сеансом человек с учётной записью.
    await user.click(screen.getByRole('button', { name: say.access('actions.issue') }));
    const whom = await screen.findByLabelText(say.access('issue.whomLabel'));
    await screen.findByRole('option', { name: 'nightly_agent — agent' });
    const options = within(whom)
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'));
    // Себя и агентов — можно, другого человека — нет (`foreign_human`).
    expect(options).toContain('alice');
    expect(options).toContain('nightly_agent');
    expect(options).not.toContain('owner');
  });

  it('администратор: все токены установки по умолчанию, «Мои» — в адресе и с `mine=true`', async () => {
    installation('main', [UI_TOKEN, AGENT_TOKEN], 'admin');
    const user = userEvent.setup();
    renderApp('/access');

    expect(await screen.findByText(say.access('intro'))).toBeInTheDocument();
    const view = await screen.findByRole('navigation', { name: say.access('view.label') });
    expect(within(view).getByRole('link', { name: say.access('view.all') })).toHaveAttribute(
      'aria-current',
      'true',
    );
    await screen.findByRole('article', { name: say.ui('token.label', { name: 'local-agent' }) });
    expect(tokenQueries.at(-1)?.searchParams.has('mine')).toBe(false);

    await user.click(within(view).getByRole('link', { name: say.access('view.mine') }));

    await waitFor(() => expect(address.current).toBe('/access?tokens=mine'));
    expect(await screen.findByText(say.access('introMine'))).toBeInTheDocument();
    expect(within(view).getByRole('link', { name: say.access('view.mine') })).toHaveAttribute(
      'aria-current',
      'true',
    );
    await waitFor(() => expect(tokenQueries.at(-1)?.searchParams.get('mine')).toBe('true'));
    // Администратор отзывает и чужое: кнопка у ключа агента, выпущенного не им.
    expect(
      within(row('local-agent')).getByRole('button', { name: say.access('revoke.action') }),
    ).toBeEnabled();
  });

  it('сеансы входа — своим разделом и только живые; закончившиеся не показываются нигде', async () => {
    const future = new Date(Date.now() + 86_400_000).toISOString();
    const past = new Date(Date.now() - 86_400_000).toISOString();
    const LIVE = accessToken({
      id: 'bbbbbbbb-0000-0000-0000-000000000001',
      name: 'вход с ноутбука',
      scope: 'main',
      participant: 'alice',
      expires_at: future,
    });
    const EXPIRED = accessToken({
      id: 'bbbbbbbb-0000-0000-0000-000000000002',
      name: 'вход вчера',
      scope: 'main',
      participant: 'alice',
      expires_at: past,
    });
    const SIGNED_OUT = accessToken({
      id: 'bbbbbbbb-0000-0000-0000-000000000003',
      name: 'вход с телефона',
      scope: 'main',
      participant: 'alice',
      expires_at: future,
      revoked_at: '2026-09-22T11:00:00Z',
    });
    installation('main', [ALICE_AGENT, LIVE, EXPIRED, SIGNED_OUT, REVOKED_TOKEN], 'alice');
    const user = userEvent.setup();
    renderApp('/access');

    const sessions = await screen.findByRole('region', {
      name: new RegExp(say.access('sessions.title')),
    });
    const live = within(sessions).getByRole('article', {
      name: say.ui('token.label', { name: 'вход с ноутбука' }),
    });
    expect(within(live).getByText(say.ui('token.expiresAt'), { exact: false })).toBeInTheDocument();
    // Свой сеанс отзывается: это выход на том устройстве.
    expect(within(live).getByRole('button', { name: say.access('revoke.action') })).toBeEnabled();
    expect(within(sessions).getAllByRole('article')).toHaveLength(1);

    // Среди ключей агентов сеанса нет.
    const active = screen.getByRole('region', { name: new RegExp(say.access('tokens.active')) });
    expect(
      within(active)
        .getAllByRole('article')
        .map((item) => item.getAttribute('aria-label')),
    ).toEqual([say.ui('token.label', { name: 'агент Алисы' })]);

    // И в истории отозванных — только ключ агента: закончившиеся сеансы не история доступа.
    await user.click(
      screen.getByRole('button', { name: say.access('tokens.history', { count: 1 }) }),
    );
    expect(
      screen.queryByRole('article', { name: say.ui('token.label', { name: 'вход вчера' }) }),
    ).toBeNull();
    expect(
      screen.queryByRole('article', { name: say.ui('token.label', { name: 'вход с телефона' }) }),
    ).toBeNull();
    expect(row('проверка 6 сентября')).toHaveAttribute('data-revoked', 'true');
  });

  it('ключ агента `main` без учётной записи: выпуск закрыт с причиной, свои ключи отзываются', async () => {
    const OWN = accessToken({
      id: 'cccccccc-0000-0000-0000-000000000001',
      name: 'ключ агента',
      scope: 'main',
      participant: 'agent',
    });
    installation('main', [OWN], 'agent');
    renderApp('/access');

    const own = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'ключ агента' }),
    });
    const issue = screen.getByRole('button', { name: say.access('actions.issue') });
    const newAgent = screen.getByRole('button', { name: say.access('actions.newAgent') });
    expect(issue).toBeDisabled();
    expect(newAgent).toBeDisabled();
    const explanation = screen.getByText(say.access('closed.noAccount'));
    expect(issue).toHaveAttribute('aria-describedby', explanation.id);
    expect(within(own).getByRole('button', { name: say.access('revoke.action') })).toBeEnabled();
    expect(writes()).toEqual([]);
  });

  it('отказ выпуска от имени другого человека объяснён причиной, а не только кодом', async () => {
    installation('main', [UI_TOKEN], 'admin');
    server.use(
      http.post(`${API}/api/v1/tokens`, () =>
        failure('permission_denied', 403, 'Not allowed', {
          action: 'token.issue',
          reason: 'foreign_human',
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/access');

    await user.click(await screen.findByRole('button', { name: say.access('actions.issue') }));
    await user.selectOptions(await screen.findByLabelText(say.access('issue.whomLabel')), 'alice');
    await user.type(screen.getByLabelText(say.access('issue.nameLabel')), 'от имени Алисы');
    await user.click(screen.getByRole('button', { name: say.access('issue.submit') }));

    expect(
      await screen.findByText(say.access('denied.foreign_human'), { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByText(say.errors('permission_denied'), { exact: false })).toBeInTheDocument();
  });

  it('отказ отзыва чужого ключа объяснён причиной', async () => {
    installation('main', [UI_TOKEN, AGENT_TOKEN], 'admin');
    server.use(
      http.delete(`${API}/api/v1/tokens/:id`, () =>
        failure('permission_denied', 403, 'Not allowed', {
          action: 'token.revoke',
          reason: 'not_own_token',
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/access');

    const agent = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'local-agent' }),
    });
    await user.click(within(agent).getByRole('button', { name: say.access('revoke.action') }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: say.access('revoke.confirm') }));

    expect(
      await within(dialog).findByText(say.access('denied.not_own_token'), { exact: false }),
    ).toBeInTheDocument();
  });
});

describe('смысл набора токена достижим без наведения (UI-163)', () => {
  it('нажатие на плашку набора раскрывает, что он открывает, повторное — прячет', async () => {
    installation('main', [UI_TOKEN, AGENT_TOKEN, REVOKED_TOKEN]);
    const user = userEvent.setup();
    renderApp('/access');

    const own = await screen.findByRole('article', {
      name: say.ui('token.label', { name: 'local-ui' }),
    });
    // Плашка — кнопка-раскрытие: на телефоне подсказки `title` нет вовсе.
    const scope = within(own).getByRole('button', {
      name: say.ui('token.scopeExplain', { scope: 'main' }),
    });
    const hint = within(own).getByText(say.ui('token.scopeMain'));
    expect(scope).toHaveAttribute('aria-expanded', 'false');
    expect(scope).toHaveAttribute('aria-controls', hint.id);
    expect(hint).not.toBeVisible();

    await user.click(scope);
    expect(scope).toHaveAttribute('aria-expanded', 'true');
    expect(hint).toBeVisible();

    await user.click(scope);
    expect(hint).not.toBeVisible();

    // Набор `task` называет своё, и раскрытие одной строки не трогает соседнюю.
    await user.click(
      screen.getByRole('button', { name: say.access('tokens.history', { count: 1 }) }),
    );
    const revoked = row('проверка 6 сентября');
    const task = within(revoked).getByRole('button', {
      name: say.ui('token.scopeExplain', { scope: 'task' }),
    });
    task.focus();
    await user.keyboard('{Enter}');
    expect(within(revoked).getByText(say.ui('token.scopeTask'))).toBeVisible();
    expect(within(row('local-agent')).getByText(say.ui('token.scopeMain'))).not.toBeVisible();
  });
});
