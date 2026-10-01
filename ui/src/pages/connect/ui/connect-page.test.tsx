import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { say } from '@testing/say';
import { setToken } from '@/shared/api';
import { LABEL_HEADER, TOKEN_PLACEHOLDER, connectionSnippets } from '@/features/connect-agent';

/**
 * Адрес нарочно не умолчание установки: экран, зашивший `localhost:8100`, совпал бы
 * с умолчанием, но не с ним.
 */
const ADDRESS = 'https://mcp.example.test:9443/casefile/mcp';
const SESSION = 'trk_session_secret_of_the_interface';

/** Что уходило на бэкенд за прогон: метод и путь. */
let sent: string[] = [];

beforeEach(() => {
  sent = [];
  setToken(SESSION);
  server.events.on('request:start', ({ request }) => {
    sent.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  server.use(
    // Ключ сеанса набора `task`: экрану подключения больше и не нужно.
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks`, () => collection([])),
  );
});

afterEach(() => {
  server.events.removeAllListeners();
});

/**
 * Сверка фрагмента целиком, переводы строк включая: обычный нормализатор схлопнул бы
 * их в пробелы, и многострочный фрагмент не совпал бы сам с собой.
 */
const exact = { normalizer: (text: string) => text };

function installation(mcpUrl = ADDRESS) {
  server.use(http.get(`${API}/api/v1/installation`, () => data({ mcp_url: mcpUrl })));
}

/** Раздел клиента по его заголовку. */
function client(name: string): HTMLElement {
  return screen.getByRole('region', { name });
}

/**
 * Дождаться фрагментов: адрес пришёл, и раздел клиента по умолчанию — Claude Code —
 * показывает команду с ним.
 */
async function snippetsShown(mcpUrl = ADDRESS): Promise<void> {
  const claude = await screen.findByRole('region', {
    name: say.ui('snippets.clients.claudeCode'),
  });
  expect(
    within(claude).getByText(connectionSnippets({ mcpUrl, labelled: false }).claudePlugin, exact),
  ).toBeInTheDocument();
}

type ClientName = 'any' | 'claudeCode' | 'codex' | 'json';

/** Выбрать клиент на дорожке — ссылкой, как это делает человек. */
async function pick(user: ReturnType<typeof userEvent.setup>, name: ClientName): Promise<void> {
  const nav = screen.getByRole('navigation', { name: say.ui('snippets.clientNav') });
  await user.click(within(nav).getByRole('link', { name: say.ui(`snippets.clients.${name}`) }));
  expect(
    await screen.findByRole('region', { name: say.ui(`snippets.clients.${name}`) }),
  ).toBeInTheDocument();
}

describe('экран «Подключить агента»', () => {
  it('открывается из навигации ключом набора `task` и берёт адрес из ответа установки', async () => {
    installation();
    const user = userEvent.setup();
    renderApp('/tasks');

    await user.click(await screen.findByRole('link', { name: say.ui('app.connect') }));

    expect(address.current).toBe('/connect');
    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.connect') }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: say.ui('app.connect') })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByLabelText(say.ui('app.whereAmI'))).toHaveTextContent(say.ui('app.connect'));

    const expected = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    await snippetsShown();
    expect(
      within(client(say.ui('snippets.clients.claudeCode'))).getByText(expected.claudePlugin, exact),
    ).toBeInTheDocument();

    await pick(user, 'codex');
    const codex = client(say.ui('snippets.clients.codex'));
    expect(within(codex).getByText(expected.codexPlugin, exact)).toBeInTheDocument();
    expect(within(codex).getByText(expected.codexUrlFile ?? '', exact)).toBeInTheDocument();

    await pick(user, 'json');
    expect(
      within(client(say.ui('snippets.clients.json'))).getByText(expected.json, exact),
    ).toBeInTheDocument();

    await pick(user, 'any');
    const any = client(say.ui('snippets.clients.any'));
    expect(within(any).getByText(ADDRESS)).toBeInTheDocument();
    expect(within(any).getByText(expected.headers, exact)).toBeInTheDocument();

    // Запросов, требующих `main`, нет: только чтение, и из записи — ничего.
    expect(sent.filter((call) => !call.startsWith('GET '))).toEqual([]);
    expect(sent).toContain('GET /api/v1/installation');
    expect(sent.some((call) => /\/(tokens|participants)\b/.test(call))).toBe(false);
  });

  it('другой адрес установки — другой текст фрагментов', async () => {
    const other = 'http://10.0.0.7:18605/agents';
    installation(other);
    renderApp('/connect');

    await snippetsShown(other);
    expect(
      screen.getByText(connectionSnippets({ mcpUrl: other, labelled: false }).claudePlugin, exact),
    ).toBeInTheDocument();
    // По http вне своей машины плагин не подключится: экран говорит об этом.
    expect(screen.getByText(say.ui('snippets.plainHttpWarning'))).toBeInTheDocument();
    expect(screen.getByRole('main')).not.toHaveTextContent(ADDRESS);
  });

  it('на экране нет секрета: вместо токена подстановка', async () => {
    installation();
    const { container } = renderApp('/connect');

    await snippetsShown();
    expect(container).not.toHaveTextContent(SESSION);
    // Подстановка названа во вступлении, а не только стоит во фрагментах.
    expect(screen.getByRole('main')).toHaveTextContent(TOKEN_PLACEHOLDER);
  });

  it('флажок общего токена добавляет `X-Actor-Label` во фрагменты с ключом и держится адресом', async () => {
    installation();
    const user = userEvent.setup();
    renderApp('/connect');

    await snippetsShown();
    // Без флажка метки нет ни в одном фрагменте — о ней говорит только объяснение экрана.
    const clients: ClientName[] = ['claudeCode', 'codex', 'json', 'any'];
    for (const name of clients) {
      await pick(user, name);
      expect(client(say.ui(`snippets.clients.${name}`))).not.toHaveTextContent(LABEL_HEADER);
    }

    await pick(user, 'claudeCode');
    await user.click(screen.getByRole('checkbox', { name: new RegExp(LABEL_HEADER) }));

    expect(address.current).toBe('/connect?shared=true');
    const shared = connectionSnippets({ mcpUrl: ADDRESS, labelled: true });
    // Плагины входят по OAuth: метка им не нужна, и её нет ни в их фрагментах, ни в объяснении.
    expect(screen.getByText(shared.claudePlugin, exact)).toBeInTheDocument();
    expect(client(say.ui('snippets.clients.claudeCode'))).not.toHaveTextContent(LABEL_HEADER);
    await pick(user, 'codex');
    expect(address.current).toBe('/connect?shared=true&client=codex');
    expect(client(say.ui('snippets.clients.codex'))).not.toHaveTextContent(LABEL_HEADER);
    // Метка — во фрагментах с ключом, и смена клиента флажок не снимает.
    await pick(user, 'json');
    expect(screen.getByText(shared.json, exact)).toBeInTheDocument();
    expect(screen.getByText('nightly_agent')).toBeInTheDocument();
    await pick(user, 'any');
    expect(screen.getByText(shared.headers, exact)).toBeInTheDocument();
  });

  it('клиент — вид в адресе: умолчание Claude Code без параметра, прочие по `?client=`', async () => {
    installation();
    const user = userEvent.setup();
    renderApp('/connect?client=codex');

    const nav = await screen.findByRole('navigation', { name: say.ui('snippets.clientNav') });
    expect(
      await screen.findByRole('region', { name: say.ui('snippets.clients.codex') }),
    ).toBeInTheDocument();
    // На виду фрагменты одного клиента: соседних разделов в разметке нет.
    expect(
      screen.queryByRole('region', { name: say.ui('snippets.clients.claudeCode') }),
    ).not.toBeInTheDocument();
    expect(
      within(nav).getByRole('link', { name: say.ui('snippets.clients.codex') }),
    ).toHaveAttribute('aria-current', 'true');

    await pick(user, 'claudeCode');
    expect(address.current).toBe('/connect');
  });

  it('незнакомый клиент в адресе показывает умолчание', async () => {
    installation();
    renderApp('/connect?client=vim');

    await snippetsShown();
  });

  it('шаги подключения идут нумерованным списком по порядку', async () => {
    installation();
    renderApp('/connect');
    await snippetsShown();

    const steps = within(screen.getByRole('list', { name: say.connect('steps') })).getAllByRole(
      'listitem',
    );
    expect(
      steps.map((step) => within(step).getByRole('heading', { level: 2 }).textContent),
    ).toEqual([
      say.connect('token.title'),
      say.connect('snippets.title'),
      say.connect('tellAgent.title'),
    ]);
    // Место снятого шага установки скила — одна фраза под списком, а не шаг (UI-171).
    expect(screen.getByText(say.connect('discipline'))).toBeInTheDocument();
  });

  it('третий шаг показывает две фразы для агента, копирует их дословно и ссылкой ведёт на /start (TRK-367)', async () => {
    installation();
    const user = userEvent.setup();
    const { container } = renderApp('/connect');
    await snippetsShown();

    await screen.findByRole('heading', { name: say.start('phrases.file.title') });
    // Фразы учебной задачи больше нет (TRK-387): на третьем шаге только две фразы.
    expect(screen.queryByText(/START-1/)).not.toBeInTheDocument();

    const phrases: { key: 'file' | 'execute' }[] = [{ key: 'file' }, { key: 'execute' }];
    for (const { key } of phrases) {
      const label = say.start(`phrases.${key}.label`);
      await user.click(screen.getByRole('button', { name: say.ui('copyBlock.label', { label }) }));
      expect(await navigator.clipboard.readText()).toBe(say.start(`phrases.${key}.text`));
    }

    // Пункт «Начало» стоит и в боковой панели под тем же именем: ссылка ищется внутри
    // области содержимого, иначе имя совпало бы с двумя элементами разом.
    const main = screen.getByRole('main');
    expect(within(main).getByRole('link', { name: say.ui('app.start') })).toHaveAttribute(
      'href',
      '/start',
    );

    // Строки токена на экране нет и на третьем шаге — как и на всём остальном экране.
    expect(container).not.toHaveTextContent(SESSION);
  });

  it('вид с меткой открывается по адресу', async () => {
    installation();
    renderApp('/connect?shared=true');

    expect(await screen.findByRole('checkbox', { name: new RegExp(LABEL_HEADER) })).toBeChecked();
    expect(
      await screen.findByText(
        connectionSnippets({ mcpUrl: ADDRESS, labelled: true }).claudePlugin,
        exact,
      ),
    ).toBeInTheDocument();
  });

  it('кнопка копирования кладёт в буфер текст своего фрагмента', async () => {
    installation();
    const user = userEvent.setup();
    renderApp('/connect');
    await snippetsShown();

    await user.click(
      within(client(say.ui('snippets.clients.claudeCode'))).getByRole('button', {
        name: say.ui('copyBlock.label', { label: say.ui('snippets.claudeLabel') }),
      }),
    );

    expect(await navigator.clipboard.readText()).toBe(
      connectionSnippets({ mcpUrl: ADDRESS, labelled: false }).claudePlugin,
    );
  });

  it('отказ установки объясняется с повтором, а остальной экран на месте', async () => {
    let left = 1;
    server.use(
      http.get(`${API}/api/v1/installation`, () => {
        if (left > 0) {
          left -= 1;
          return failure('database_unavailable', 503, 'Database is not available');
        }
        return data({ mcp_url: ADDRESS });
      }),
    );
    const user = userEvent.setup();
    renderApp('/connect');

    expect(await screen.findByRole('alert')).toHaveTextContent(say.errors('database_unavailable'));
    // Откуда взять токен и фраза о дисциплине сервера человек читает и без адреса.
    expect(screen.getByRole('heading', { name: say.connect('token.title') })).toBeInTheDocument();
    expect(screen.getByText(say.connect('discipline'))).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: say.ui('query.retry') }));

    await snippetsShown();
  });

  it('говорит по-русски целиком, а код во фрагментах тот же', async () => {
    installation();
    renderApp('/connect', { language: 'ru' });

    expect(
      await screen.findByRole('heading', { level: 1, name: say.ui('app.connect') }),
    ).toHaveTextContent('Подключить агента');
    expect(
      await screen.findByText(
        connectionSnippets({ mcpUrl: ADDRESS, labelled: false }).claudePlugin,
        exact,
      ),
    ).toBeInTheDocument();
  });
});
