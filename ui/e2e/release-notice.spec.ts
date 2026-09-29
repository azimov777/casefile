import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { side } from './contour';

/**
 * Плашка нового выпуска внизу боковой панели (TRK-416).
 *
 * Бэкенд контура — не `production`, в GitHub он не ходит и отвечает «обновления нет»:
 * это и есть второй сценарий, ничего не подменяя. Ответ «вышел новее» подменяется в
 * браузере — настоящий выпуск новее установки контур дать не может.
 */
const URL_080 = 'https://github.com/azimov777/casefile/releases/tag/v0.8.0';

async function newerRelease(page: Page) {
  await page.route('**/api/v1/installation/release', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          version: '0.7.0',
          latest_version: '0.8.0',
          latest_url: URL_080,
          update_available: true,
        },
      }),
    }),
  );
}

test('вышел выпуск новее — внизу панели ссылка на его страницу', async ({ page }) => {
  await newerRelease(page);
  await page.goto('/tasks?project=DEMO');

  const panel = side(page);
  const notice = panel.getByRole('link', { name: /Доступен выпуск v0\.8\.0/ });
  await expect(notice).toBeVisible();
  await expect(notice).toHaveAttribute('href', URL_080);
  await expect(notice).toContainText('У вас v0.7.0');

  // Внизу: под последним пунктом навигации, а не в её середине.
  const nav = panel.getByRole('navigation', { name: 'Разделы' });
  const navBox = await nav.boundingBox();
  const noticeBox = await notice.boundingBox();
  expect(navBox).not.toBeNull();
  expect(noticeBox).not.toBeNull();
  expect(noticeBox!.y).toBeGreaterThanOrEqual(navBox!.y + navBox!.height);

  const axe = await new AxeBuilder({ page }).include('aside').analyze();
  expect(axe.violations).toEqual([]);
});

test('обновления нет — плашки нет', async ({ page }) => {
  const answered = page.waitForResponse('**/api/v1/installation/release');
  await page.goto('/tasks?project=DEMO');

  const response = await answered;
  expect(response.status()).toBe(200);
  expect((await response.json()).data.update_available).toBe(false);

  await expect(side(page).getByText('owner')).toBeVisible();
  await expect(side(page).getByRole('link', { name: /Доступен выпуск/ })).toHaveCount(0);
});

test.describe('узкий экран', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('плашка в шторке панели и без прокрутки вбок', async ({ page }) => {
    await newerRelease(page);
    await page.goto('/tasks?project=DEMO');
    await page.getByRole('button', { name: /^Показать разделы/ }).click();

    const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
    const notice = sheet.getByRole('link', { name: /Доступен выпуск v0\.8\.0/ });
    await notice.scrollIntoViewIfNeeded();
    await expect(notice).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
