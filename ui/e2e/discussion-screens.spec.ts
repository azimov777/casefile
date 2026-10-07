import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

/** Насколько документ шире окна. Больше нуля — страница разъехалась вширь. */
async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/**
 * Экраны обсуждений читаются без правок (TRK-672): доступность и телефон без прокрутки
 * вбок. Пишущий сценарий — `discussion.spec.ts`.
 */
const SCREENS: [string, string][] = [
  ['открытое обсуждение', '/discussions/DEMO~2'],
  ['закрытое обсуждение', '/discussions/DEMO~1'],
  ['входящая с обсуждениями', '/questions'],
  ['история с обсуждениями', '/questions?view=history'],
];

for (const [name, url] of SCREENS) {
  test(`доступность: ${name}`, async ({ page }) => {
    await silenceJournal(page);
    await page.goto(url);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('article').first()).toBeVisible();
    await fontsReady(page);

    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations).toEqual([]);
  });

  test(`на телефоне без прокрутки вбок: ${name}`, async ({ page }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(url);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('article').first()).toBeVisible();
    await fontsReady(page);

    expect(await overflow(page), `${url} на 390 px`).toBeLessThanOrEqual(0);
  });
}
