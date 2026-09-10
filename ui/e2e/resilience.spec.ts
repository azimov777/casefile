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

  /*
   * Отказ подменяется в браузере, как и у шапки выше. Раньше он добывался негодным
   * курсором прямо из адреса, но курсор из адреса таблицы ушёл вместе с кнопкой «Ещё»
   * (UI-65), а негодный номер страницы читается как первая — выжать 4xx из адреса
   * списка больше нечем. Код взят настоящий: так отвечает разбор отбора.
   */
  await page.route('**/api/v1/tasks?*', async (route) => {
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'search_field_unknown', message: 'Search field is unknown', details: {} },
      }),
    });
  });

  // 4xx не повторяется молча: человек видит объяснение сразу.
  await page.goto('/tasks?queue=DEMO');

  const failure = page.getByRole('main').getByRole('alert');
  await expect(failure).toHaveText('Такого поля отбора нет.');

  const before = attempts.length;
  await page.getByRole('main').getByRole('button', { name: 'Повторить' }).click();

  await expect.poll(() => attempts.length).toBeGreaterThan(before);
  await expect(failure).toHaveText('Такого поля отбора нет.');
});
