import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady } from './contour';

/*
 * Входящая: раздел «Решения ждут проверки» (TRK-759) на живом бэкенде с демо-данными.
 *
 * Сценарий пишущий — подтверждает решение DEMO — и потому идёт в проекте «запись».
 */

const section = (page: Page) => page.getByRole('region', { name: /^Решения ждут проверки/ });

test('Входящая: решения DEMO в разделе, «Подтвердить» убирает строку, число после перезагрузки меньше', async ({
  page,
}) => {
  await page.goto('/questions');
  const count = section(page).locator('[data-decisions-count]');
  await expect(count).toBeVisible();
  const before = Number(await count.getAttribute('data-decisions-count'));
  expect(before).toBeGreaterThan(1);

  // Раздел стоит после «Требуют внимания» и перед замечаниями.
  const headings = await page.getByRole('heading', { level: 2 }).allTextContents();
  const at = (prefix: string) => headings.findIndex((text) => text.startsWith(prefix));
  expect(at('Требуют внимания')).toBeGreaterThanOrEqual(0);
  expect(at('Решения ждут проверки')).toBeGreaterThan(at('Требуют внимания'));
  expect(at('Мои замечания')).toBeGreaterThan(at('Решения ждут проверки'));

  // Решения DEMO в списке, проект — ссылкой.
  const first = section(page).locator('li[data-decision^="DEMO"]').first();
  await expect(first).toBeVisible();
  await expect(first.locator('[data-project-link]')).toHaveText('DEMO');
  const ref = (await first.getAttribute('data-decision')) ?? '';

  // Ссылка решения открывает его проект на вкладке «Решения».
  await first.locator(`a[href*="entry="]`).first().click();
  await expect(page).toHaveURL(/\/projects\/DEMO/);
  await page.goBack();

  // «Подтвердить»: строка уходит из раздела, после перезагрузки число меньше на 1.
  const row = section(page).locator(`li[data-decision="${ref}"]`);
  await row.locator('button[aria-expanded]').click();
  await row.getByRole('button', { name: /^Подтвердить решение/ }).click();
  await expect(row).toHaveCount(0);
  await page.reload();
  await expect(section(page).locator('[data-decisions-count]')).toHaveAttribute(
    'data-decisions-count',
    String(before - 1),
  );
  await expect(section(page).locator(`li[data-decision="${ref}"]`)).toHaveCount(0);

  // Значок «Входящей» неподтверждённых решений не считает.
  const badge = page.getByRole('link', { name: /^Входящая/ });
  await expect(badge).not.toContainText(String(before - 1));
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`Входящая на 390 px (${colorScheme}): без прокрутки вбок и нарушений доступности`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/questions');
    const first = section(page).locator('li[data-decision]').first();
    await expect(first).toBeVisible();
    await first.locator('button[aria-expanded]').click();
    await fontsReady(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
    ).toBeLessThanOrEqual(0);
  });
}
