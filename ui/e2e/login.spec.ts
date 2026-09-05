import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { readE2eToken } from './contour';

const token = readE2eToken();

test('вход с токеном демо показывает участника и счётчик вопросов', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));

  await page.goto('/login');
  await page.getByLabel('Токен участника').fill(token);
  await page.getByRole('button', { name: 'Войти' }).click();

  await expect(page).toHaveURL(/\/tasks$/);
  await expect(page.getByText('owner')).toBeVisible();
  await expect(page.getByText(/^Открытых вопросов: \d+$/)).toBeVisible();

  // Токен только в заголовке: ни в адресе, ни в параметрах запросов его быть не должно.
  expect(page.url()).not.toContain(token);
  expect(requests.filter((url) => url.includes(token))).toEqual([]);
});

test('неверный токен объясняется по-русски и не сохраняется', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Токен участника').fill('trk_definitely_not_a_token');
  await page.getByRole('button', { name: 'Войти' }).click();

  await expect(page.getByRole('alert')).toHaveText('Токен неизвестен или отозван.');
  expect(await page.evaluate(() => window.localStorage.getItem('tracker.token'))).toBeNull();
});

test('доступность экрана входа и оболочки', async ({ page }) => {
  await page.goto('/login');
  const onLogin = await new AxeBuilder({ page }).analyze();
  expect(serious(onLogin.violations)).toEqual([]);

  await page.getByLabel('Токен участника').fill(token);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page.getByText('owner')).toBeVisible();

  const onTasks = await new AxeBuilder({ page }).analyze();
  expect(serious(onTasks.violations)).toEqual([]);
});

/** Нарушения уровня serious и выше: их приложение обязано не допускать. */
function serious(violations: { id: string; impact?: string | null }[]) {
  return violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => violation.id);
}
