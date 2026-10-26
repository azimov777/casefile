import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  E2E_EMAIL,
  E2E_PASSWORD,
  LOGIN_URL,
  fontsReady,
  grantAccess,
  motionSettled,
  readE2eToken,
  side,
  silenceJournal,
} from './contour';

/**
 * Доступ агента к проектам на экране «Доступы» (TRK-748, решение владельца TRK~28#6):
 * у агента режим «все» / «все, кроме» / «только перечисленные» и список проектов.
 *
 * Сценарий пишущий — заводит агента и проекты, удалить которых нельзя, — и идёт в проекте
 * «запись» (имя кончается на `access.spec.ts`). Имена уникальны на прогон.
 */

const STAMP = Date.now().toString(36);
const AGENT = `pa_agent_${STAMP}`;
const KEY_A = `PA${STAMP}`.toUpperCase().slice(0, 14);
const KEY_B = `PB${STAMP}`.toUpperCase().slice(0, 14);

function auth() {
  return { Authorization: `Bearer ${readE2eToken()}` };
}

async function createProject(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post('/api/v1/projects', {
    headers: auth(),
    data: { key, title: `Доступ ${key}`, description: 'Сквозной тест TRK-748.' },
  });
  expect(response.status()).toBe(201);
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

test('человек ставит агенту «все, кроме» с одним проектом, после перезагрузки видит «Кроме 1» и возвращает «Все проекты»', async ({
  page,
  request,
}) => {
  await createProject(request, KEY_A);
  await createProject(request, KEY_B);
  const registered = await request.post('/api/v1/participants', {
    headers: { ...auth(), 'Idempotency-Key': `pa-${STAMP}` },
    data: { kind: 'agent', name: AGENT, description: 'Агент сквозного теста TRK-748' },
  });
  expect(registered.status()).toBe(201);

  await silenceJournal(page);
  await page.goto('/tasks');
  await side(page).getByRole('link', { name: 'Доступы' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();

  const row = page.getByRole('group', { name: `Агент ${AGENT}` });
  await expect(row.getByText('Все проекты')).toBeVisible();
  await row.getByRole('button', { name: 'Проекты' }).click();

  const dialog = page.getByRole('dialog', { name: `Проекты агента ${AGENT}` });
  // В режиме «все» списка нет.
  await expect(dialog.getByRole('radio', { name: /Все проекты, включая новые/ })).toBeChecked();
  await expect(dialog.getByRole('checkbox')).toHaveCount(0);

  await dialog.getByRole('radio', { name: /Все, кроме перечисленных/ }).check();
  await dialog.getByRole('checkbox', { name: new RegExp(KEY_A) }).check();
  expect(await violations(page), 'окно проектов агента').toEqual([]);
  await dialog.getByRole('button', { name: 'Сохранить' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row.getByText('Кроме 1')).toBeVisible();

  // Настройка живёт на сервере, а не в странице.
  await page.reload();
  const reloaded = page.getByRole('group', { name: `Агент ${AGENT}` });
  await expect(reloaded.getByText('Кроме 1')).toBeVisible();
  await reloaded.getByRole('button', { name: 'Проекты' }).click();
  const again = page.getByRole('dialog', { name: `Проекты агента ${AGENT}` });
  await expect(again.getByRole('checkbox', { name: new RegExp(KEY_A) })).toBeChecked();
  await expect(again.getByRole('checkbox', { name: new RegExp(KEY_B) })).not.toBeChecked();
  await page.keyboard.press('Escape');

  // Телефон: страница без горизонтальной прокрутки, окно проектов тоже.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(reloaded.getByText('Кроме 1')).toBeVisible();
  const overflow = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
  expect(await overflow(), 'страница «Доступы» на 390 px').toBeLessThanOrEqual(0);
  await reloaded.getByRole('button', { name: 'Проекты' }).click();
  await expect(page.getByRole('dialog', { name: `Проекты агента ${AGENT}` })).toBeVisible();
  expect(await overflow(), 'окно проектов на 390 px').toBeLessThanOrEqual(0);
  await page.screenshot({
    path: '/Users/azimov/PycharmProjects/agents/casefile-artifacts/TRK-748/access-390.png',
  });
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1280, height: 800 });

  // Возврат к «всем».
  await reloaded.getByRole('button', { name: 'Проекты' }).click();
  const back = page.getByRole('dialog', { name: `Проекты агента ${AGENT}` });
  await back.getByRole('radio', { name: /Все проекты, включая новые/ }).check();
  await expect(back.getByRole('checkbox')).toHaveCount(0);
  await back.getByRole('button', { name: 'Сохранить' }).click();
  await expect(reloaded.getByText('Все проекты')).toBeVisible();
});

test('человек без флага администратора не видит чужого агента, а чужой PUT получает agent_owned_by_another', async ({
  browser,
  request,
}) => {
  const password = `keys password ${STAMP}`;
  const alice = { name: `pa_alice_${STAMP}`, email: `pa-alice-${STAMP}@example.com` };
  const bob = { name: `pa_bob_${STAMP}`, email: `pa-bob-${STAMP}@example.com` };

  const session = await request.post(`${LOGIN_URL}/api/v1/session`, {
    data: { email: E2E_EMAIL, password: E2E_PASSWORD },
  });
  expect(session.ok()).toBe(true);
  const admin = ((await session.json()) as { data: { token: string } }).data.token;
  for (const person of [alice, bob]) {
    const created = await request.post(`${LOGIN_URL}/api/v1/accounts`, {
      headers: { Authorization: `Bearer ${admin}` },
      data: { email: person.email, name: person.name, description: '', is_admin: false, password },
    });
    expect(created.status()).toBe(201);
  }
  // Агенты `claude_<человек>` заводит выдача подключения: хозяин у каждого свой.
  grantAccess({ human: alice.name, kind: 'oauth', client: 'claude', name: `Claude ${alice.name}` });
  grantAccess({ human: bob.name, kind: 'oauth', client: 'claude', name: `Claude ${bob.name}` });

  const context = await browser.newContext({ baseURL: LOGIN_URL, locale: 'ru-RU' });
  const alicePage = await context.newPage();
  await alicePage.goto('/login');
  await alicePage.getByLabel('Почта').fill(alice.email);
  await alicePage.getByLabel('Пароль', { exact: true }).fill(password);
  await alicePage.getByRole('button', { name: 'Войти' }).click();
  await expect(alicePage).toHaveURL(/\/tasks/);
  await alicePage.goto('/access');

  await expect(alicePage.getByRole('group', { name: `Агент claude_${alice.name}` })).toBeVisible();
  await expect(alicePage.getByRole('group', { name: `Агент claude_${bob.name}` })).toHaveCount(0);

  // Мимо экрана сервер всё равно отказывает.
  const own = await request.post(`${LOGIN_URL}/api/v1/session`, {
    data: { email: alice.email, password },
  });
  const aliceKey = ((await own.json()) as { data: { token: string } }).data.token;
  const denied = await request.put(`${LOGIN_URL}/api/v1/participants/claude_${bob.name}/projects`, {
    headers: { Authorization: `Bearer ${aliceKey}` },
    data: { mode: 'except', projects: [] },
  });
  expect(denied.status()).toBeGreaterThanOrEqual(400);
  expect(((await denied.json()) as { error: { code: string } }).error.code).toBe(
    'agent_owned_by_another',
  );
  await context.close();
});
