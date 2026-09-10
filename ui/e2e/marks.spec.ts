import { expect, test, type Page } from '@playwright/test';
import { contractStatuses, fontsReady, silenceJournal } from './contour';

/** Все статусы контракта разом видны в заголовках столбцов доски. */
const STATUSES = contractStatuses();

/** Вырезка одного знака статуса: только рисунок, без имени рядом. */
async function shotOf(page: Page, status: string): Promise<Buffer> {
  return page
    .getByRole('region', { name: status })
    .locator('[data-mark="status"] svg')
    .first()
    .screenshot();
}

test('статусы различаются формой: разница держится без цвета', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(page.getByRole('region', { name: 'done' })).toBeVisible();
  await fontsReady(page);

  // Цвет снят полностью: сначала обесцвечивание страницы, потом принудительно один
  // и тот же тон у всех знаков. Без второго шага проверка доказывала бы, что знаки
  // разной яркости, — а доказать нужно, что они разной формы.
  await page.addStyleTag({
    content: `
      html { filter: grayscale(1) !important; }
      [data-mark], [data-mark] * { color: #000 !important; }
    `,
  });

  const shots = new Map<string, Buffer>();
  for (const status of STATUSES) shots.set(status, await shotOf(page, status));

  const same: string[] = [];
  for (const [first, firstShot] of shots) {
    for (const [second, secondShot] of shots) {
      if (first >= second) continue;
      if (firstShot.equals(secondShot)) same.push(`${first} = ${second}`);
    }
  }

  // Каждый с каждым: при шести статусах контракта это пятнадцать пар.
  expect(same, 'формы этих статусов совпали').toEqual([]);
});

test('колонка «Приоритет» не выросла: знак вместо плашки занимает не больше места', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  const width = await page.evaluate(() => {
    const head = Array.from(document.querySelectorAll('thead th')).find(
      (node) => node.textContent === 'Приоритет',
    );
    return head === undefined ? null : head.getBoundingClientRect().width;
  });

  // Замер до правки на том же контуре: 94.8 px (плашка `critical` с рамкой и полями).
  // Порог задачи — не больше чем +8 px к нему.
  expect(width).not.toBeNull();
  expect(width as number).toBeLessThanOrEqual(94.8 + 8);
});
