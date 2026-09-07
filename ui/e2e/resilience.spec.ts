import { expect, test } from '@playwright/test';
import { readE2eToken, side } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/**
 * Отказ бэкенда подменяется в браузере, а не гашением контейнера: гасить бэкенд
 * посреди прогона значит ронять и остальные сценарии, идущие параллельно, — а нужен
 * ровно один отказавший запрос, после которого сервер снова жив.
 */
test('отказ шапки объясняется по-русски и чинится повтором, без перезагрузки', async ({ page }) => {
  // Отказывает, пока тест не скажет иначе: у 5xx политика запросов оставляет два
  // молчаливых повтора (`app/config/query-client.ts`), и починка после первого
  // отказа проверяла бы их, а не кнопку.
  let broken = true;

  await page.route('**/api/v1/bootstrap', async (route) => {
    if (!broken) return route.fallback();
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'database_unavailable', message: 'Database is not available', details: {} },
      }),
    });
  });

  await page.goto('/tasks?queue=DEMO');

  const panel = side(page);
  await expect(panel.getByRole('alert')).toHaveText('База данных недоступна.', {
    timeout: 15_000,
  });
  await expect(panel.getByText('owner')).toBeHidden();

  // Список рядом с панелью отказа не заметил: у каждого запроса своё состояние.
  await expect(page.getByRole('rowheader', { name: 'DEMO-1' })).toBeVisible();

  const before = page.url();
  broken = false;
  await panel.getByRole('button', { name: 'Повторить' }).click();

  await expect(panel.getByText('owner')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Повторить' })).toHaveCount(0);
  // Повтор — это `refetch`: адрес тот же, страница не перезагружалась.
  expect(page.url()).toBe(before);
});

test('отказ списка объясняется по коду и повторяется кнопкой', async ({ page }) => {
  const attempts: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/tasks?')) attempts.push(request.url());
  });

  // Негодный курсор — отказ по существу: 4xx не повторяется молча, и человек
  // видит объяснение сразу.
  await page.goto('/tasks?queue=DEMO&cursor=nonsense');

  const failure = page.getByRole('main').getByRole('alert');
  await expect(failure).toHaveText('Курсор страницы не разбирается.');

  const before = attempts.length;
  await page.getByRole('main').getByRole('button', { name: 'Повторить' }).click();

  await expect.poll(() => attempts.length).toBeGreaterThan(before);
  await expect(failure).toHaveText('Курсор страницы не разбирается.');
});
