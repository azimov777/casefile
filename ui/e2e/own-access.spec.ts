import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  E2E_EMAIL,
  E2E_PASSWORD,
  LOGIN_URL,
  fontsReady,
  grantAccess,
  motionSettled,
} from './contour';

/**
 * Свои доступы людей (UI-123 поверх TRK-114, TRK-473): у каждого пользователя свои агенты
 * (`claude_<человек>`, TRK-475#14) — свои подключения OAuth и ключи; человек без флага
 * администратора видит в «Доступах» только их и выдаёт ключи только своим агентам;
 * администратор видит всё с именами хозяев и выдавших. Ключей людям нет (TRK-472).
 *
 * Режим входа по учётным записям — второй экземпляр интерфейса контура (`LOGIN_URL`,
 * `global-setup.ts`): настоящий nginx и настоящий API, без подмен. Подключение OAuth и
 * агента по клиенту собирает `grantAccess` теми же службами, что соберёт вход (контур
 * MCP-сервера не поднимает). Сценарий пишущий — заводит учётные записи, — поэтому идёт
 * проектом «запись» (имя файла кончается на `access.spec.ts`). Почта и имена уникальны на
 * прогон.
 */
test.use({ baseURL: LOGIN_URL });

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Почта').fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/tasks/);
}

/** Ключ сеанса администратора — завести товарища запросом, а не экраном «Люди». */
async function adminKey(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${LOGIN_URL}/api/v1/session`, {
    data: { email: E2E_EMAIL, password: E2E_PASSWORD },
  });
  expect(response.ok()).toBe(true);
  return ((await response.json()) as { data: { token: string } }).data.token;
}

async function bootstrapStatus(request: APIRequestContext, secret: string): Promise<number> {
  const response = await request.get(`${LOGIN_URL}/api/v1/bootstrap`, {
    headers: { Authorization: `Bearer ${secret}` },
  });
  return response.status();
}

async function violations(page: Page): Promise<string[]> {
  await fontsReady(page);
  await motionSettled(page.locator('body'));
  const found = await new AxeBuilder({ page }).analyze();
  return found.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact}): ${violation.nodes.map((node) => node.target).join(' ')}`,
  );
}

test('два пользователя и администратор: у каждого свои подключения и ключи, в выпуске только свои агенты', async ({
  page,
  browser,
  request,
}) => {
  const stamp = Date.now().toString(36);
  const password = `keys password ${stamp}`;
  const alice = { name: `alice_${stamp}`, email: `alice-${stamp}@example.com` };
  const bob = { name: `bob_${stamp}`, email: `bob-${stamp}@example.com` };
  const aliceAgent = `claude_${alice.name}`;
  const bobAgent = `claude_${bob.name}`;
  const aliceConnection = `Claude Code ${alice.name}`;
  const bobConnection = `Claude Code ${bob.name}`;
  const aliceKey = `ключ ${alice.name}`;
  const bobKey = `ключ ${bob.name}`;

  const admin = await adminKey(request);
  for (const person of [alice, bob]) {
    const created = await request.post(`${LOGIN_URL}/api/v1/accounts`, {
      headers: { Authorization: `Bearer ${admin}` },
      data: { email: person.email, name: person.name, description: '', is_admin: false, password },
    });
    expect(created.status()).toBe(201);
  }

  // У каждого своя строка подключения (`claude_alice`, `claude_bob`), у Боба — ещё и ключ.
  grantAccess({ human: alice.name, kind: 'oauth', client: 'claude', name: aliceConnection });
  grantAccess({ human: bob.name, kind: 'oauth', client: 'claude', name: bobConnection });
  grantAccess({ human: bob.name, kind: 'key', client: 'claude', name: bobKey });

  // Алиса входит и открывает «Доступы»: там только её, и сказано об этом словами.
  await signIn(page, alice.email, password);
  await page.goto('/access');
  await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();
  await expect(page.getByText('Ваши доступы:', { exact: false })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Чьи доступы показаны' })).toHaveCount(0);

  const connections = page.getByRole('region', { name: /^Подключения/ });
  const keys = page.getByRole('region', { name: /^Ключи агентов/ });
  const sessions = page.getByRole('region', { name: /^Сеансы входа/ });

  // Её подключение — в «Подключениях» с хозяином-агентом и «кто подключил»; Боба нет.
  await expect(connections.getByRole('article')).toHaveCount(1);
  const connection = connections.getByRole('article', { name: `Доступ «${aliceConnection}»` });
  await expect(connection.getByText(aliceAgent)).toBeVisible();
  await expect(connection.getByText(`кто подключил: ${alice.name}`)).toBeVisible();
  // Её вход — сеанс со сроком, ключей агентов у неё пока нет.
  await expect(sessions.getByRole('article')).toHaveCount(1);
  await expect(sessions.getByText('ключ этого сеанса')).toBeVisible();
  await expect(
    page.getByText('У вас пока нет ни одного ключа агента.', { exact: false }),
  ).toBeVisible();
  await expect(page.getByText(bobAgent)).toHaveCount(0);

  // Выпуск: свой агент есть, чужого агента и людей нет.
  await page.getByRole('button', { name: 'Выпустить ключ' }).click();
  const issueDialog = page.getByRole('dialog');
  const whom = issueDialog.getByLabel('За кого говорит ключ');
  await expect(whom.locator(`option[value="${aliceAgent}"]`)).toHaveCount(1);
  await expect(whom.locator(`option[value="${bobAgent}"]`)).toHaveCount(0);
  await expect(whom.locator(`option[value="${alice.name}"]`)).toHaveCount(0);
  await expect(whom.locator(`option[value="${bob.name}"]`)).toHaveCount(0);
  await expect(whom.locator('option[value="owner"]')).toHaveCount(0);
  await whom.selectOption(aliceAgent);
  await issueDialog.getByLabel('Имя ключа').fill(aliceKey);
  await issueDialog.getByRole('button', { name: 'Выпустить', exact: true }).click();

  const secretDialog = page.getByRole('dialog');
  await expect(secretDialog.getByText('Скопируйте секрет сейчас')).toBeVisible();
  const secret = (
    (await secretDialog
      .getByRole('figure', { name: 'Секрет токена, показан один раз' })
      .locator('pre code')
      .textContent()) ?? ''
  ).trim();
  expect(secret).toMatch(/^trk_/);
  await expect(secretDialog.getByRole('region', { name: 'Claude Code' })).toContainText(
    `Authorization: Bearer ${secret}`,
  );
  expect(await violations(page), 'окно секрета у человека').toEqual([]);
  await secretDialog.getByRole('button', { name: 'Секрет сохранён' }).click();

  // Ключ работает и говорит за её агента.
  expect(await bootstrapStatus(request, secret)).toBe(200);

  // В «Ключах агентов» — ровно её ключ и колонка «кто выдал»; ключа Боба на экране нет.
  await expect(keys.getByRole('article')).toHaveCount(1);
  const row = keys.getByRole('article', { name: `Доступ «${aliceKey}»` });
  await expect(row).toBeVisible();
  await expect(row.getByText(`кто выдал: ${alice.name}`)).toBeVisible();
  await expect(page.getByRole('article', { name: `Доступ «${bobKey}»` })).toHaveCount(0);
  await expect(page.getByRole('article', { name: `Доступ «${bobConnection}»` })).toHaveCount(0);
  // Перезагрузка второго показа секрета не даёт.
  await page.reload();
  await expect(row).toBeVisible();
  expect(await page.content()).not.toContain(secret);
  expect(await violations(page), 'экран своих доступов').toEqual([]);

  // Администратор во втором браузере видит все доступы установки, строки обоих — с именами.
  const context = await browser.newContext({ baseURL: LOGIN_URL, locale: 'ru-RU' });
  const adminPage = await context.newPage();
  await signIn(adminPage, E2E_EMAIL, E2E_PASSWORD);
  await adminPage.goto('/access');
  const view = adminPage.getByRole('navigation', { name: 'Чьи доступы показаны' });
  await expect(view.getByRole('link', { name: 'Все доступы установки' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  for (const [title, agent, who] of [
    [aliceConnection, aliceAgent, alice.name],
    [bobConnection, bobAgent, bob.name],
  ] as const) {
    const theirs = adminPage.getByRole('article', { name: `Доступ «${title}»` });
    await expect(theirs).toBeVisible();
    await expect(theirs.getByText(agent)).toBeVisible();
    await expect(theirs.getByText(`кто подключил: ${who}`)).toBeVisible();
    // Чужое подключение администратор отключить может.
    await expect(theirs.getByRole('button', { name: 'Отключить' })).toBeVisible();
  }
  for (const [title, agent, who] of [
    [aliceKey, aliceAgent, alice.name],
    [bobKey, bobAgent, bob.name],
  ] as const) {
    const theirs = adminPage.getByRole('article', { name: `Доступ «${title}»` });
    await expect(theirs).toBeVisible();
    await expect(theirs.getByText(agent)).toBeVisible();
    await expect(theirs.getByText(`кто выдал: ${who}`)).toBeVisible();
    await expect(theirs.getByRole('button', { name: 'Отозвать' })).toBeVisible();
  }

  // В выпуске у администратора оба агента с именами хозяев и ни одного человека.
  await adminPage.getByRole('button', { name: 'Выпустить ключ' }).click();
  const adminWhom = adminPage.getByRole('dialog').getByLabel('За кого говорит ключ');
  await expect(
    adminWhom.getByRole('option', { name: new RegExp(`^${aliceAgent} — .*хозяин ${alice.name}`) }),
  ).toHaveCount(1);
  await expect(
    adminWhom.getByRole('option', { name: new RegExp(`^${bobAgent} — .*хозяин ${bob.name}`) }),
  ).toHaveCount(1);
  await expect(adminWhom.locator(`option[value="${alice.name}"]`)).toHaveCount(0);
  await expect(adminWhom.locator('option[value="owner"]')).toHaveCount(0);
  await adminPage.keyboard.press('Escape');

  // «Мои» — в адресе, и доступов Алисы и Боба там нет.
  await view.getByRole('link', { name: 'Мои' }).click();
  await expect(adminPage).toHaveURL(/\/access\?tokens=mine$/);
  await expect(adminPage.getByRole('article', { name: `Доступ «${bobKey}»` })).toHaveCount(0);
  await expect(adminPage.getByRole('article', { name: `Доступ «${aliceKey}»` })).toHaveCount(0);
  await expect(adminPage.getByRole('article').first()).toBeVisible();
  await context.close();

  // Алиса отключает своё подключение и отзывает свой ключ: следующий же запрос с ключом —
  // отказ, а обе строки уходят в историю.
  await connection.getByRole('button', { name: 'Отключить' }).click();
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: 'Отключить', exact: true })
    .click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(connection).toHaveCount(0);

  await row.getByRole('button', { name: 'Отозвать' }).click();
  const confirm = page.getByRole('alertdialog');
  await confirm.getByRole('button', { name: 'Отозвать', exact: true }).click();
  // Окно закрывается по успеху отзыва; пока оно открыто, строка скрыта от дерева доступности
  // (`aria-hidden` у фона модального окна), и её «исчезновение» ещё ничего не значит.
  await expect(confirm).toHaveCount(0);
  const toggle = page.getByRole('button', { name: /^История: 2 снятых доступа/ });
  await expect(toggle).toBeVisible();
  await expect(row).toHaveCount(0);
  expect(await bootstrapStatus(request, secret)).toBe(401);
  await toggle.click();
  await expect(page.getByRole('article', { name: `Доступ «${aliceKey}»` })).toHaveAttribute(
    'data-revoked',
    'true',
  );
  await expect(page.getByRole('article', { name: `Доступ «${aliceConnection}»` })).toHaveAttribute(
    'data-revoked',
    'true',
  );
});
