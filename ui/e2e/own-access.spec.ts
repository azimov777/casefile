import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { E2E_EMAIL, E2E_PASSWORD, LOGIN_URL, fontsReady, motionSettled } from './contour';

/**
 * Свои токены людей (UI-123 поверх TRK-114): человек без флага администратора выпускает
 * ключ своему агенту из интерфейса, видит только свои доступы и отзывает свой ключ;
 * администратор видит все токены установки и сужает их до своих.
 *
 * Режим входа по учётным записям — второй экземпляр интерфейса контура (`LOGIN_URL`,
 * `global-setup.ts`): настоящий nginx и настоящий API, без подмен. Сценарий пишущий —
 * заводит учётную запись, — поэтому идёт проектом «запись» (имя файла кончается на
 * `access.spec.ts`). Почта и имя уникальны на прогон.
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

test('человек выпускает ключ своему агенту, видит только свои и отзывает; администратор видит все', async ({
  page,
  browser,
  request,
}) => {
  const stamp = Date.now().toString(36);
  const email = `keys-${stamp}@example.com`;
  const name = `keys_${stamp}`;
  const password = `keys password ${stamp}`;
  const tokenName = `агент ${name}`;

  const admin = await adminKey(request);
  const created = await request.post(`${LOGIN_URL}/api/v1/accounts`, {
    headers: { Authorization: `Bearer ${admin}` },
    data: { email, name, description: '', is_admin: false, password },
  });
  expect(created.status()).toBe(201);

  // Товарищ входит и открывает «Доступы»: там только его, и сказано об этом словами.
  await signIn(page, email, password);
  await page.goto('/access');
  await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();
  await expect(page.getByText('Ваши доступы:', { exact: false })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Чьи токены показаны' })).toHaveCount(0);

  // Его вход — сеанс со сроком — стоит своим разделом, а ключей агентов у него пока нет.
  const sessions = page.getByRole('region', { name: /^Сеансы входа/ });
  await expect(sessions.getByRole('article')).toHaveCount(1);
  await expect(sessions.getByText('ключ этого сеанса')).toBeVisible();
  await expect(
    page.getByText('У вас пока нет ни одного ключа агента.', { exact: false }),
  ).toBeVisible();

  // Выпуск: себе можно, другого человека в выборе нет.
  await page.getByRole('button', { name: 'Выпустить токен' }).click();
  const issueDialog = page.getByRole('dialog');
  const whom = issueDialog.getByLabel('За кого говорит токен');
  await expect(whom.locator(`option[value="${name}"]`)).toHaveCount(1);
  await expect(whom.locator('option[value="owner"]')).toHaveCount(0);
  await whom.selectOption(name);
  await issueDialog.getByLabel('Имя токена').fill(tokenName);
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

  // Ключ работает и говорит за него.
  expect(await bootstrapStatus(request, secret)).toBe(200);

  // В действующих — ровно его ключ: чужих ключей установки на экране нет.
  const active = page.getByRole('region', { name: /^Действующие токены/ });
  await expect(active.getByRole('article')).toHaveCount(1);
  const row = active.getByRole('article', { name: `Доступ «${tokenName}»` });
  await expect(row).toBeVisible();
  // Возврат на экран и перезагрузка секрета не показывают.
  await page.reload();
  await expect(row).toBeVisible();
  expect(await page.content()).not.toContain(secret);
  expect(await violations(page), 'экран своих доступов').toEqual([]);

  // Администратор во втором браузере видит все токены установки, и ключ товарища среди них.
  const context = await browser.newContext({ baseURL: LOGIN_URL, locale: 'ru-RU' });
  const adminPage = await context.newPage();
  await signIn(adminPage, E2E_EMAIL, E2E_PASSWORD);
  await adminPage.goto('/access');
  const view = adminPage.getByRole('navigation', { name: 'Чьи токены показаны' });
  await expect(view.getByRole('link', { name: 'Все токены установки' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  const foreign = adminPage.getByRole('article', { name: `Доступ «${tokenName}»` });
  await expect(foreign).toBeVisible();
  // Чужой ключ администратор отозвать может: кнопка у строки есть.
  await expect(foreign.getByRole('button', { name: 'Отозвать' })).toBeVisible();
  // «Мои» — в адресе, и ключа товарища там нет.
  await view.getByRole('link', { name: 'Мои' }).click();
  await expect(adminPage).toHaveURL(/\/access\?tokens=mine$/);
  await expect(foreign).toHaveCount(0);
  await expect(adminPage.getByRole('article').first()).toBeVisible();
  await context.close();

  // Товарищ отзывает свой ключ: следующий же запрос с ним — отказ, а строка уходит в историю.
  await row.getByRole('button', { name: 'Отозвать' }).click();
  const confirm = page.getByRole('alertdialog');
  await confirm.getByRole('button', { name: 'Отозвать', exact: true }).click();
  // Окно закрывается по успеху отзыва; пока оно открыто, строка скрыта от дерева доступности
  // (`aria-hidden` у фона модального окна), и её «исчезновение» ещё ничего не значит.
  await expect(confirm).toHaveCount(0);
  const toggle = page.getByRole('button', { name: /^История: 1 отозванный токен/ });
  await expect(toggle).toBeVisible();
  await expect(row).toHaveCount(0);
  expect(await bootstrapStatus(request, secret)).toBe(401);
  await toggle.click();
  await expect(page.getByRole('article', { name: `Доступ «${tokenName}»` })).toHaveAttribute(
    'data-revoked',
    'true',
  );
});
