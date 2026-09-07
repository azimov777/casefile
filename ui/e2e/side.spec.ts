import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Боковая панель на широком экране; на узком та же панель живёт в шторке. */
function side(page: Page) {
  return page.getByRole('complementary', { name: 'Разделы трекера' });
}

test('переход в другую очередь меняет только очередь', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board&status=open');
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();

  // В демо-контуре очередь одна, поэтому «все задачи» — вторая точка того же
  // перехода: она снимает очередь, не трогая ни вид, ни остальной отбор.
  await side(page).getByRole('link', { name: 'Все задачи' }).click();

  await expect(page).toHaveURL(/view=board/);
  await expect(page).toHaveURL(/status=open/);
  await expect(page).not.toHaveURL(/queue=/);
  await expect(side(page).getByRole('link', { name: 'Все задачи' })).toHaveAttribute(
    'aria-current',
    'page',
  );
});

test('очередь остаётся подсвеченной внутри задачи, а вид — доской при возврате', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');

  await page.getByRole('article').first().getByRole('link').first().click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-\d+$/);

  // Очередь задачи прочитана из её ключа: подсветка не пропадает от того, что
  // человек ушёл со списка.
  await expect(side(page).getByRole('link', { name: /DEMO/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(page.getByLabel('Где я')).toContainText('DEMO');

  await page.getByRole('link', { name: 'К списку с отбором' }).click();
  await expect(page).toHaveURL(/view=board/);
});

test('в панели нет действий, меняющих данные', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(side(page)).toBeVisible();

  // Человек наблюдает и отвечает, остальное делают агенты: заводить задачи и менять
  // статусы из панели нельзя, и проверяется это перечислением, а не на глаз.
  const buttons = await side(page).getByRole('button').allInnerTexts();
  expect(buttons).toEqual(['Выйти']);
});

test.describe('узкий экран', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('панель уезжает за кнопку, закрывается Esc и возвращает фокус', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    // Постоянного места панель здесь не занимает: содержание получает всю ширину.
    await expect(side(page)).toBeHidden();

    const opener = page.getByRole('button', { name: 'Показать разделы' });
    await expect(opener).toBeVisible();
    await opener.click();

    const sheet = page.getByRole('dialog', { name: 'Разделы трекера' });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole('link', { name: /Входящая/ })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Выйти' })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    // Фокус вернулся туда, откуда человек шторку открыл: иначе следующий Tab начал бы
    // обход страницы с начала.
    await expect(opener).toBeFocused();
  });

  test('страница не разъезжается вширь ни на одном экране', async ({ page }) => {
    await silenceJournal(page);

    for (const address of [
      '/tasks?queue=DEMO',
      '/tasks/DEMO-1',
      '/tasks/DEMO-1/case',
      '/questions',
    ]) {
      await page.goto(address);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `горизонтальная прокрутка на ${address}`).toBeLessThanOrEqual(0);
    }
  });

  test('доступность оболочки на узком экране', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    await page.getByRole('button', { name: 'Показать разделы' }).click();
    await expect(page.getByRole('dialog', { name: 'Разделы трекера' })).toBeVisible();

    const result = await new AxeBuilder({ page }).analyze();
    const serious = result.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => violation.id);
    expect(serious).toEqual([]);
  });
});
