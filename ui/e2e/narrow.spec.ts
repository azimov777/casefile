import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { readE2eToken, side, silenceJournal } from './contour';

const token = readE2eToken();

/** Экраны, на которых оболочка обязана держаться одинаково. */
const SCREENS = ['/tasks?queue=DEMO', '/tasks/DEMO-6', '/tasks/DEMO-1/case', '/questions'];

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Насколько документ шире окна. Больше нуля — страница разъехалась вширь. */
async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

for (const width of [320, 390, 768]) {
  test(`оболочка не расширяет документ на ${width} px`, async ({ page }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width, height: 720 });

    for (const address of SCREENS) {
      await page.goto(address);
      // Ждём саму страницу, а не только оболочку: замер до прихода выдачи ничего
      // не значит — расширить документ может как раз содержимое.
      await expect(page.getByRole('main')).toBeVisible();
      expect(await overflow(page), `${address} на ${width} px`).toBeLessThanOrEqual(0);
    }
  });
}

test('при увеличении текста вдвое полоса растёт, а не уезжает за край', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();

  const before = await page.getByRole('banner').boundingBox();

  // Увеличение текста, а не масштаба страницы: кегли заданы в `rem`, и корневой
  // размер — то, чем человек их увеличивает в настройках браузера.
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%';
  });

  // Высота задана минимумом, а строка переносится: полоса опускается вниз, а не
  // прячет содержимое за правым краем. Замер через `poll`: смена корневого кегля
  // пересобирает раскладку не в том же кадре, и снятое сразу число ловит середину.
  await expect
    .poll(async () => (await page.getByRole('banner').boundingBox())?.height ?? 0)
    .toBeGreaterThan(before?.height ?? 0);
  await expect.poll(() => overflow(page)).toBeLessThanOrEqual(0);

  // Всё, ради чего человек сюда пришёл, остаётся доступным.
  await expect(page.getByRole('button', { name: /Показать разделы/ })).toBeVisible();
  await expect(page.getByRole('banner').getByText(/на связи|подключаемся|нет связи/)).toBeVisible();
});

test('на узком экране разделы, входящая и выход достижимы клавиатурой', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();

  const opener = page.getByRole('button', { name: /Показать разделы/ });
  await opener.focus();
  await expect(opener).toBeFocused();
  await page.keyboard.press('Enter');

  const sheet = page.getByRole('dialog', { name: 'Разделы трекера' });
  await expect(sheet).toBeVisible();

  // Внутри шторки табом обходится всё служебное: очереди, входящая, выход.
  await expect(sheet.getByRole('link', { name: /Входящая/ })).toBeVisible();
  await expect(sheet.getByRole('button', { name: 'Выйти' })).toBeVisible();

  const focusable = await sheet
    .locator('a, button')
    .evaluateAll((nodes) => nodes.filter((node) => node.getBoundingClientRect().width > 0).length);
  expect(focusable).toBeGreaterThan(2);
});

test('состояние потока видно на узком экране, не открывая панель', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks?queue=DEMO');

  // Панель уехала, но свежесть показанного осталась на виду: узнавать «нет связи»
  // открытием меню человек стал бы уже после того, как поверил экрану.
  await expect(side(page)).toBeHidden();
  await expect(page.getByRole('banner').getByText(/на связи|подключаемся|нет связи/)).toBeVisible();
});

test('доступность узкого экрана на всех пяти экранах', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });

  for (const address of SCREENS) {
    await page.goto(address);
    await expect(page.getByRole('main')).toBeVisible();

    const result = await new AxeBuilder({ page }).analyze();
    const serious = result.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => violation.id);
    expect(serious, address).toEqual([]);
  }
});
