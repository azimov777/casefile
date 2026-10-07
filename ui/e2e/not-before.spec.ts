import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { silenceJournal } from './contour';

/*
 * Момент «можно взять с …» (TRK-593, TRK#47): демо-задача DEMO-9 отложена на неделю от
 * посева. Значок стоит на доске, человек на странице задачи нажимает «Снять» — значок
 * пропал и на странице, и на доске; «Отложить…» с моментом через день — значок вернулся.
 *
 * Сценарий пишущий: правит DEMO-9 и возвращает её отложенной. Снимки — только когда задан
 * `SHOTS_DIR`, в обеих темах.
 */

const KEY = 'DEMO-9';
const BOARD = '/tasks?project=DEMO&view=board';
const LIST = '/tasks?project=DEMO&view=list';

/** Значок отложенной задачи на карточке: знак признака с подписью «отложена…». */
function mark(scope: ReturnType<Page['locator']>) {
  return scope.locator('[data-mark="feature"]').filter({ hasText: /отложена/ });
}

function card(page: Page) {
  return page.getByRole('article').filter({ hasText: KEY });
}

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.SHOTS_DIR;
  if (dir === undefined || dir === '') return;
  mkdirSync(dir, { recursive: true });
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width: 1440, height: 900 });
    // Тема меняет цвета переходом: снимок до его конца — полупрозрачные карточки.
    await page.waitForTimeout(600);
    await page.screenshot({ path: resolve(dir, `${name}-${scheme}.png`), fullPage: true });
  }
  await page.emulateMedia({ colorScheme: 'light' });
}

/** Завтра в 09:00 по часам этого устройства, как его вводит человек. */
function tomorrowInput(): string {
  const at = new Date();
  at.setDate(at.getDate() + 1);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T09:00`;
}

test('значок отложенной задачи: снять на странице задачи, поставить снова', async ({ page }) => {
  await silenceJournal(page);

  await page.goto(LIST);
  await expect(page.getByRole('table').getByText(KEY, { exact: true })).toBeVisible();
  await expect(mark(page.getByRole('row').filter({ hasText: KEY }))).toBeVisible();
  await shot(page, 'list');

  await page.goto(BOARD);
  await expect(card(page)).toBeVisible();
  await expect(mark(card(page))).toBeVisible();
  await shot(page, 'board');

  await page.goto(`/tasks/${KEY}`);
  const cell = page.getByText('Взять в работу', { exact: true }).locator('xpath=..');
  await expect(cell).toContainText('Можно взять в работу с');
  await expect(mark(cell)).toBeVisible();
  await shot(page, 'task-with-moment');

  await cell.getByRole('button', { name: `Изменить момент задачи ${KEY}` }).click();
  await expect(page.getByLabel('Можно взять с')).toBeVisible();
  await shot(page, 'task-input-open');
  await page.getByRole('button', { name: 'Отмена' }).click();

  await cell.getByRole('button', { name: `Снять момент у задачи ${KEY}` }).click();
  await expect(mark(page.locator('main'))).toHaveCount(0);
  await expect(cell.getByRole('button', { name: `Отложить задачу ${KEY}` })).toBeVisible();

  await page.goto(BOARD);
  await expect(card(page)).toBeVisible();
  await expect(mark(card(page))).toHaveCount(0);

  await page.goto(`/tasks/${KEY}`);
  await cell.getByRole('button', { name: `Отложить задачу ${KEY}` }).click();
  await page.getByLabel('Можно взять с').fill(tomorrowInput());
  await page.getByRole('button', { name: 'Сохранить' }).click();
  await expect(cell).toContainText('Можно взять в работу с');
  await expect(mark(cell)).toBeVisible();

  await page.goto(BOARD);
  await expect(mark(card(page))).toBeVisible();
});
