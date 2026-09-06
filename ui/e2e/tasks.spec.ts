import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/**
 * Вход проверяется своим сценарием, здесь он только предусловие: токен кладётся
 * в хранилище до загрузки страницы, чтобы каждый сценарий не проходил форму заново.
 * Ставится на контекст, а не на вкладку: часть сценариев открывает вторую вкладку.
 */
test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

function rows(page: Page) {
  return page.locator('tbody tr');
}

function row(page: Page, key: string) {
  return page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: key }) });
}

test('отбор по статусу open даёт ровно открытые задачи демо и переживает перезагрузку', async ({
  page,
}) => {
  await page.goto('/tasks?queue=DEMO&status=open');

  await expect(rows(page)).toHaveCount(2);
  await expect(page.getByRole('rowheader', { name: 'DEMO-3' })).toBeVisible();
  await expect(page.getByRole('rowheader', { name: 'DEMO-4' })).toBeVisible();

  await page.reload();

  // Свёрнутый отбор называет условие словами, не заставляя разворачивать форму.
  await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText('статус open');

  await page.getByRole('button', { name: 'Изменить отбор' }).click();
  await expect(page.getByLabel('Очередь')).toHaveValue('DEMO');
  await expect(page.getByRole('checkbox', { name: 'open' })).toBeChecked();
  await expect(rows(page)).toHaveCount(2);
});

test('признаки строки берутся из выдачи списка, без запроса на задачу', async ({ page }) => {
  await silenceJournal(page);
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/tasks')) calls.push(request.url());
  });

  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(7);

  await expect(row(page, 'DEMO-6').getByText('заблокирована')).toBeVisible();
  await expect(row(page, 'DEMO-4').getByText('блокирующих 1')).toBeVisible();
  await expect(row(page, 'DEMO-4').getByText('вопросов 1')).toBeVisible();

  expect(calls.filter((url) => /\/api\/v1\/tasks\?/.test(url))).toHaveLength(1);
  expect(calls.filter((url) => /\/api\/v1\/tasks\/[^?]/.test(url))).toEqual([]);
});

test('опечатка в запросе объясняется позицией и списком допустимого, таблица остаётся', async ({
  page,
}) => {
  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(7);

  await page.getByRole('button', { name: 'Изменить отбор' }).click();
  await page.getByLabel('Запрос на языке бэкенда').fill('status: opne');
  await page.getByRole('button', { name: 'Применить' }).click();

  const problem = page.getByRole('alert');
  await expect(problem).toContainText('Ошибка в символе 9');
  await expect(problem).toContainText('open');
  await expect(rows(page)).toHaveCount(7);
});

test('сортировка живёт в адресе: вторая вкладка по той же ссылке показывает то же самое', async ({
  page,
  context,
}) => {
  await page.goto('/tasks?queue=DEMO');

  // Дожидаемся именно пересортированной выдачи, а не только смены адреса: до её
  // прихода таблица показывает прежний порядок, и снятое с неё значение сравнивалось
  // бы с порядком второй вкладки, которая ждать не обязана.
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/tasks?') && response.url().includes('sort=key'),
    ),
    page.getByLabel('Сортировка').selectOption('key'),
  ]);

  await expect(page).toHaveURL(/sort=key/);
  const first = await rows(page).first().locator('th').innerText();

  const copy = await context.newPage();
  await copy.goto(page.url());

  await expect(copy.getByLabel('Сортировка')).toHaveValue('key');
  expect(await rows(copy).first().locator('th').innerText()).toBe(first);
  await copy.close();
});

test('пустая выдача объясняется и предлагает сброс', async ({ page }) => {
  await page.goto('/tasks?queue=DEMO&text=такоготочнонет');

  await expect(page.getByText('Задач по этим условиям нет')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сбросить фильтры' })).toBeEnabled();
});

test('негодный курсор в адресе объясняется по-русски', async ({ page }) => {
  await page.goto('/tasks?queue=DEMO&cursor=неведомо');

  await expect(page.getByRole('alert')).toContainText('Курсор страницы не разбирается.');
});

test('доступность списка задач', async ({ page }) => {
  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(7);

  // Форму надо раскрыть: свёрнутую её `axe` не увидит, а проверять надо и её —
  // сценарий идёт в обеих темах, и поля формы в тёмной проверены только отсюда.
  await page.getByRole('button', { name: 'Изменить отбор' }).click();
  await expect(page.getByLabel('Запрос на языке бэкенда')).toBeVisible();

  const found = await new AxeBuilder({ page }).analyze();
  const serious = found.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => violation.id);

  expect(serious).toEqual([]);
});
