import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  fontsReady,
  installWithoutKey,
  readE2eToken,
  readTaskToken,
  side,
  silenceJournal,
} from './contour';

/**
 * Экран «Подключить агента» (UI-105): адрес во фрагментах — тот, что отдала установка
 * контура, копирование кладёт в буфер текст фрагмента, экран работает и ключом
 * установки, и ключом набора `task`, введённым на `/login`.
 *
 * Контур MCP не поднимает, и адрес ему задан нарочно чужим (`TRACKER_MCP_PUBLIC_URL`
 * в `docker-compose.yml`): экран, зашивший умолчание `localhost:8100`, с ним бы
 * разошёлся. В живой MCP сценарий не ходит — подключение настоящего клиента
 * проверяется вне прогона (`UI-105`, проверка 3).
 *
 * Сценарий только читает и идёт в обеих темах: `axe` обязан пройти и там, и там.
 */

test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

/** Адрес MCP глазами бэкенда контура — тем же запросом, которым его читает экран. */
async function installationUrl(request: APIRequestContext, token: string): Promise<string> {
  const response = await request.get('/api/v1/installation', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { data: { mcp_url: string } };
  return body.data.mcp_url;
}

/** Раздел клиента на экране по его заголовку. */
function client(page: Page, name: string) {
  return page.getByRole('region', { name, exact: true });
}

/**
 * Текст фрагмента в разделе клиента: код внутри блока, а не код внутри объяснения —
 * в объяснениях свои `<code>` (имя сервера, переменная, флаг).
 */
function fragment(page: Page, name: string) {
  return client(page, name).locator('figure pre code');
}

/** Переход на экран из боковой панели — так, как его находит человек. */
async function openFromNavigation(page: Page): Promise<void> {
  await side(page).getByRole('link', { name: 'Подключить агента' }).click();
  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Подключить агента' })).toBeVisible();
  await expect(side(page).getByRole('link', { name: 'Подключить агента' })).toHaveAttribute(
    'aria-current',
    'page',
  );
}

/** Адрес во всех фрагментах — ровно тот, что отдала установка. */
async function expectAddress(page: Page, mcpUrl: string): Promise<void> {
  const any = client(page, 'Любой клиент MCP');
  await expect(any.getByRole('figure', { name: 'URL' }).locator('pre code')).toHaveText(mcpUrl);

  await expect(fragment(page, 'Claude Code')).toContainText(
    ` casefile "${mcpUrl}" --header "Authorization: Bearer <token>"`,
  );
  await expect(fragment(page, 'Codex').first()).toContainText(`url = "${mcpUrl}"`);

  const json = await fragment(page, 'JSON mcpServers').textContent();
  expect(JSON.parse(json ?? '')).toEqual({
    mcpServers: {
      casefile: { type: 'http', url: mcpUrl, headers: { Authorization: 'Bearer <token>' } },
    },
  });
}

test('ключ установки: экран из навигации, адрес из ответа установки, копирование в буфер', async ({
  page,
  request,
}) => {
  const token = readE2eToken();
  const mcpUrl = await installationUrl(request, token);
  // Условие, без которого сверка ничего не доказывает: адрес контура — не умолчание,
  // которое экран мог бы знать сам.
  expect(mcpUrl).not.toContain('localhost:8100');

  const writes: string[] = [];
  page.on('request', (sent) => {
    if (sent.url().includes('/api/') && sent.method() !== 'GET') writes.push(sent.url());
  });

  await page.goto('/tasks');
  await openFromNavigation(page);
  await expectAddress(page, mcpUrl);

  // Кнопка копирования кладёт в буфер ровно текст своего фрагмента.
  const claude = client(page, 'Claude Code');
  const shown = await fragment(page, 'Claude Code').textContent();
  await claude.getByRole('button', { name: 'Копировать: Команда Claude Code' }).click();
  await expect(
    claude.getByRole('button', { name: 'Скопировано: Команда Claude Code' }),
  ).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(shown);

  // Секрета на экране нет: ни ключа сеанса, ни какого-либо иного — только подстановка.
  await expect(page.getByRole('main')).not.toContainText(token);
  await expect(page.getByRole('main')).not.toContainText(/trk_[A-Za-z0-9_-]{8,}/);
  // Экран только читает: ни одного запроса записи.
  expect(writes).toEqual([]);
});

test('ключ набора `task`, введённый на `/login`: экран открывается и берёт тот же адрес', async ({
  page,
  request,
}) => {
  const token = readTaskToken();
  // Набор ключа проверяется у бэкенда, а не предполагается по имени файла.
  const session = await request.get('/api/v1/bootstrap', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(((await session.json()) as { data: { token: { scope: string } } }).data.token.scope).toBe(
    'task',
  );
  const mcpUrl = await installationUrl(request, token);

  await installWithoutKey(page);
  await page.goto('/login');
  await page.getByLabel('Токен участника').fill(token);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/tasks$/);

  await openFromNavigation(page);
  await expectAddress(page, mcpUrl);

  // Флажок общего токена добавляет метку во фрагменты и держится адресом. `click()`,
  // а не `check()`: состояние флажка приходит из адреса на кадр позже
  // (`docs/notes/testing.md`, «`check()` не ждёт флажок…»).
  const shared = page.getByRole('checkbox', { name: /X-Actor-Label/ });
  await shared.click();
  await expect(shared).toBeChecked();
  await expect(page).toHaveURL(/\/connect\?shared=true$/);
  await expect(fragment(page, 'Claude Code')).toContainText('--header "X-Actor-Label: <label>"');
});

test('на экране нет нарушений `axe` ни одного уровня — в обоих видах фрагментов', async ({
  page,
}) => {
  await silenceJournal(page);

  for (const path of ['/connect', '/connect?shared=true']) {
    await page.goto(path);
    await expect(fragment(page, 'JSON mcpServers')).toBeVisible();
    await fontsReady(page);

    const found = await new AxeBuilder({ page }).analyze();
    const violations = found.violations.map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.nodes.map((node) => node.target).join(' ')}`,
    );
    expect(violations, path).toEqual([]);
  }
});
