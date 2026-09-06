import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { readE2eToken } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

test('доступность входящей', async ({ page }) => {
  await page.goto('/questions');
  await expect(page.getByRole('heading', { name: 'Входящая' })).toBeVisible();

  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => violation.id);
  expect(serious).toEqual([]);
});

test('входящая показывает адресованный вопрос и отбирает блокирующие', async ({ page }) => {
  await page.goto('/questions');

  const header = page.getByRole('banner');
  await expect(header.getByText(/^Открытых вопросов: \d+$/)).toBeVisible();

  const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
  await expect(question).toBeVisible();
  await expect(question.getByText('блокирующий')).toBeVisible();
  await expect(question).toContainText('Сколько храним?');

  // Отбор живёт в адресе: ссылку на «только блокирующие» можно переслать, и она
  // открывает то же самое. Сам клик по флажку проверяет страничный тест — здесь важно,
  // что состояние читается из адреса, а не из памяти вкладки.
  await page.goto('/questions?blocking=true');
  await expect(page.getByRole('checkbox', { name: 'только блокирующие' })).toBeChecked();
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#4' })).toBeVisible();
});
