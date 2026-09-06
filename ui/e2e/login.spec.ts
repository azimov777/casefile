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

test('пробел в конце токена не мешает, а карточка при отказе не едет', async ({ page }) => {
  await page.goto('/login');

  const field = page.getByLabel('Токен участника');
  const submit = page.getByRole('button', { name: 'Войти' });

  // Замер до отказа. Карточку входа уже чинили однажды: центрирование по вертикали
  // превращало рост карточки в сдвиг кнопки вверх (`docs/notes/ui.md`).
  const before = (await submit.boundingBox())?.y ?? -1;
  expect(before).toBeGreaterThan(0);

  await field.fill('trk_definitely_not_a_token');
  await submit.click();
  await expect(page.getByRole('alert')).toBeVisible();

  expect((await submit.boundingBox())?.y).toBe(before);

  // Токен, вставленный с лишним пробелом на конце, по-прежнему пускает: обрезка
  // работает, и правка проверки заголовка её не сломала.
  await field.fill(`${token} `);
  await submit.click();
  await expect(page.getByText('owner')).toBeVisible();
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
