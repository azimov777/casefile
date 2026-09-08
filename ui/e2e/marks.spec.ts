import { expect, test, type Page } from '@playwright/test';
import { contractStatuses, fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Все статусы контракта разом видны в заголовках столбцов доски. */
const STATUSES = contractStatuses();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

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

test('счётчик скрытых тегов помещается в свою колонку, а не уезжает за край', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  // Счётчик «+N» — единственный доступ к тегам, которые не показаны. Уехав за край
  // ячейки, он исчезает вместе с этим доступом, и обрезание становится потерей данных.
  const overflow = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tbody tr'));
    return rows
      .map((row) => {
        const cell = row.children[5];
        if (cell === undefined) return 0;
        const box = cell.getBoundingClientRect();
        // Внутренний край ячейки: у неё горизонтальные поля по 12 px.
        const limit = box.right - 12;
        const parts = Array.from(cell.querySelectorAll('*')).filter(
          (node) => node.children.length === 0,
        );
        return parts.reduce(
          (worst, node) => Math.max(worst, node.getBoundingClientRect().right - limit),
          0,
        );
      })
      .reduce((worst, value) => Math.max(worst, value), 0);
  });

  // Полпикселя на округление подпиксельной раскладки — и ни пикселя больше.
  expect(overflow).toBeLessThanOrEqual(0.5);
});
