import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

/**
 * Экран «Начало» (`TRK-361`) читает бэкенд, но сам ничего не меняет, — открывается
 * прямо по адресу `/start`, минуя `/` и её решение по состоянию знакомства
 * (`start-onboarding.spec.ts`, проект «запись»). Поэтому эти сценарии — обычные
 * читающие, идут в обеих темах и не зависят от порядка прогона: учётную запись
 * владельца контура они не трогают.
 */
const LANGUAGE_STORAGE_KEY = 'tracker.language';

/** Насколько документ шире окна. Больше нуля — страница разъехалась вширь. */
async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

for (const lang of ['ru', 'en'] as const) {
  test(`на 390 px документ не расширяется вбок, блок трёх шагов виден: ${lang}`, async ({
    page,
  }) => {
    await silenceJournal(page);
    await page.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value),
      [LANGUAGE_STORAGE_KEY, lang],
    );
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto('/start');
    const main = page.getByRole('main');
    await expect(main).toBeVisible();
    await fontsReady(page);

    expect(await overflow(page)).toBeLessThanOrEqual(0);

    // Блок трёх шагов (`TRK-378`): виден сразу под заголовком, три шага по порядку,
    // внутри содержимого экрана (а не пункт «Начало» боковой панели — тот же случай,
    // что уронил слияние TRK-377).
    const steps = main.getByRole('list').first();
    await expect(steps).toBeVisible();
    await expect(steps.getByRole('listitem')).toHaveCount(3);
  });
}

test('на экране «Начало» нет нарушений `axe`', async ({ page }) => {
  await silenceJournal(page);

  await page.goto('/start');
  await expect(page.getByRole('main')).toBeVisible();
  await fontsReady(page);

  const found = await new AxeBuilder({ page }).analyze();
  expect(found.violations).toEqual([]);
});
