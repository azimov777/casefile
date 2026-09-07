import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, side, silenceJournal } from './contour';

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

test('таблица прокручивается вбок внутри рамки, а не прячет колонки', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();
  await fontsReady(page);

  const scroller = page.getByRole('region', { name: /таблица прокручивается вбок/ });
  const last = page.getByRole('columnheader', { name: 'Активность' });

  // До прокрутки последняя колонка за правым краем рамки — но она существует и
  // доступна, а не отрезана: раньше `overflow-x: clip` не давал до неё добраться.
  const box = await scroller.boundingBox();
  const before = await last.boundingBox();
  expect((before?.x ?? 0) + (before?.width ?? 0)).toBeGreaterThan(
    (box?.x ?? 0) + (box?.width ?? 0),
  );

  // Прокрутка идёт внутри рамки: страница вширь не едет.
  await scroller.evaluate((node) => {
    node.scrollLeft = node.scrollWidth;
  });
  await expect
    .poll(async () => {
      const after = await last.boundingBox();
      return (after?.x ?? 0) + (after?.width ?? 0);
    })
    .toBeLessThanOrEqual((box?.x ?? 0) + (box?.width ?? 0) + 1);
  expect(await overflow(page)).toBeLessThanOrEqual(0);

  // И то же самое доступно с клавиатуры: область фокусируется и ходит стрелками.
  await scroller.evaluate((node) => {
    node.scrollLeft = 0;
  });
  await scroller.focus();
  await expect(scroller).toBeFocused();
  // Стрелками, а не `End`: `End` уводит прокрутку по вертикали, а вбок область ходит
  // именно стрелками — это и есть клавиатурный доступ к правым колонкам.
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect.poll(() => scroller.evaluate((node) => node.scrollLeft)).toBeGreaterThan(0);
});

test('на широком экране таблица не прокручивается, а шапка липнет к верху', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();
  await fontsReady(page);

  const scroller = page.getByRole('region', { name: /таблица прокручивается вбок/ });
  // Прокручивать нечего: колонки помещаются, и обёртка остаётся `clip` — без этого
  // липкая шапка прилипала бы к ней вместо окна (требование UI-12).
  const overflowX = await scroller.evaluate((node) => node.scrollWidth - node.clientWidth);
  expect(overflowX).toBeLessThanOrEqual(0);

  await page.mouse.wheel(0, 600);
  const head = page.getByRole('columnheader', { name: 'Активность' });
  await expect(head).toBeInViewport();
});

test('на карточке замечание доступно до описи и одним действием из навигации', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks/DEMO-3');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-3');

  // Порядок чтения, а не только вид: блок замечаний стоит в разметке до описи дела.
  const order = await page.evaluate(() =>
    Array.from(document.querySelectorAll('main section[aria-labelledby]')).map((node) =>
      node.getAttribute('aria-labelledby'),
    ),
  );
  expect(order.indexOf('remarks')).toBeGreaterThan(-1);
  expect(order.indexOf('remarks')).toBeLessThan(order.indexOf('case'));

  // И то же самое — одним действием из липкой навигации, с любой глубины прокрутки.
  await page.mouse.wheel(0, 4000);
  const action = page
    .getByRole('navigation', { name: /Навигация по задаче/ })
    .getByRole('button', { name: 'Оставить замечание' });
  await expect(action).toBeInViewport();
  await action.click();
  await expect(page.getByLabel(/^Замечание$/)).toBeVisible();
});

test('сводка на узком экране идёт подписью над текстом', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });

  // Сводка есть не у каждой задачи демо, а проверять надо именно её: берём первую,
  // по которой кто-то отчитывался.
  const parts = page.locator('section[aria-labelledby="summary"] dl > div');
  for (const key of ['DEMO-1', 'DEMO-2', 'DEMO-3', 'DEMO-4', 'DEMO-5', 'DEMO-6', 'DEMO-7']) {
    await page.goto(`/tasks/${key}`);
    await expect(page.getByRole('heading', { name: 'Последняя сводка' })).toBeVisible();
    await fontsReady(page);
    if ((await parts.count()) > 0) break;
  }
  expect(await parts.count()).toBeGreaterThan(0);

  // Подпись части и её текст стоят друг под другом, а не двумя колонками: колонка
  // подписей в 8rem ужимала текст примерно до 190 px и растягивала сводку.
  const stacked = await parts.evaluateAll((nodes) =>
    nodes.map((part) => {
      const term = part.querySelector('dt')?.getBoundingClientRect();
      const value = part.querySelector('dd')?.getBoundingClientRect();
      if (term === undefined || value === undefined) return null;
      return { below: value.top >= term.bottom - 1, wide: Math.round(value.width) };
    }),
  );

  for (const part of stacked) {
    expect(part).not.toBeNull();
    expect(part?.below).toBe(true);
    // Значение занимает ширину блока, а не остаток от колонки подписей.
    expect(part?.wide).toBeGreaterThan(250);
  }
});
