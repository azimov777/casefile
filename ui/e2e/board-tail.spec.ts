import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

/**
 * Ширины, на которых владелец замерял хвост: обе меньше суммарной ширины шести
 * столбцов доски демо (`--ui-board-column` × 6 плюс промежутки — 1548 px), поэтому
 * на обеих у ряда гарантированно есть своя горизонтальная полоса прокрутки, и низ
 * доски — это низ именно её, а не пустого столбца.
 */
const SIZES = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
];

/**
 * Пиксельное значение переменной темы, снятое пробным узлом, а не переписанное сюда
 * числом: разойдясь с `theme.css`, оно осталось бы зелёным на переписанном вручную
 * значении (тот же приём, что в `scrollbar.spec.ts`, «Полосы прокрутки в прогоне»).
 */
function cssVarPixels(page: Page, name: string): Promise<string> {
  return page.evaluate((token) => {
    const probe = document.createElement('div');
    probe.style.cssText = `position:absolute;height:0;width:0;padding-bottom:var(${token})`;
    document.body.append(probe);
    const value = getComputedStyle(probe).paddingBottom;
    probe.remove();
    return value;
  }, name);
}

/**
 * Низ доски задач: под полосой прокрутки столбцов остаётся тот же скромный зазор,
 * что и у правого края доски (`px-4` в `app-shell.tsx`), а не общий хвост страницы
 * `--ui-page-tail` (3rem), рассчитанный на экраны, которые прокручиваются сами
 * (UI-129). До правки замер этим же сценарием показывал около 48 px пустоты под
 * полосой на обеих ширинах — числа были сняты и подшиты в дело задачи.
 *
 * Полосы прокрутки видны и в этом headless-прогоне: `playwright.config.ts` снимает
 * `--hide-scrollbars` (UI-116), окно ради них не нужно.
 */
test('под полосой прокрутки столбцов остаётся зазор доски, а не хвост страницы', async ({
  page,
}) => {
  await silenceJournal(page);

  for (const [index, size] of SIZES.entries()) {
    await page.setViewportSize(size);
    await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
    await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
    await fontsReady(page);

    const boardTail = await cssVarPixels(page, '--ui-board-tail');

    const measured = await page.evaluate(() => {
      const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
        (node) => node.getAttribute('aria-label') !== 'Отбор задач',
      );
      const row = sections[0]?.parentElement as HTMLElement;
      const rowBox = row.getBoundingClientRect();
      return {
        rowOver: row.scrollWidth - row.clientWidth,
        gapToWindow: window.innerHeight - rowBox.bottom,
        scrollHeight: document.scrollingElement?.scrollHeight ?? 0,
        innerHeight: window.innerHeight,
      };
    });

    const report = `${size.width}x${size.height}: ${JSON.stringify({ ...measured, boardTail })}`;

    // Полоса действительно нарисована: ряду есть что прокручивать вбок.
    expect(measured.rowOver, report).toBeGreaterThan(0);

    // Проверка задачи (UI-129): не больше 16 px, а не хвост страницы.
    expect(Math.round(measured.gapToWindow), report).toBeLessThanOrEqual(16);
    // И это именно `--ui-board-tail`, а не число, случайно попавшее в 16 px: два
    // источника (отступ обёртки и вычитание в `tasks-board.tsx`) обязаны сойтись
    // до пикселя, иначе один из них ушёл от токена (see theme.css, `--ui-board-tail`).
    expect(Math.round(measured.gapToWindow), report).toBe(Math.round(parseFloat(boardTail)));

    // Страница по-прежнему не прокручивается.
    expect(measured.scrollHeight, report).toBeLessThanOrEqual(measured.innerHeight);

    if (index === 0) {
      await test.info().attach(`доска без хвоста страницы (${size.width}x${size.height})`, {
        body: await page.screenshot(),
        contentType: 'image/png',
      });
    }
  }
});

/**
 * Правило замены задачи: у таблицы и у карточки задачи хвост остался прежним
 * (`--ui-page-tail`) — сузился только у доски, отмеченной признаком `data-board`.
 */
test('у таблицы задач и у карточки нижний хвост страницы не изменился', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto('/tasks?queue=DEMO');
  await page.locator('table tbody tr').first().waitFor();
  await fontsReady(page);

  const pageTail = await cssVarPixels(page, '--ui-page-tail');

  const table = await page.evaluate(() => {
    const wrapper = document.querySelector('main')?.parentElement as HTMLElement;
    return {
      paddingBottom: getComputedStyle(wrapper).paddingBottom,
      hasBoardMark: wrapper.querySelector('[data-board]') !== null,
    };
  });
  expect(table.paddingBottom, JSON.stringify({ table, pageTail })).toBe(pageTail);
  expect(table.hasBoardMark).toBe(false);

  await test.info().attach('нижний хвост таблицы задач', {
    body: await page.screenshot(),
    contentType: 'image/png',
  });

  await page.goto('/tasks/DEMO-1');
  await page.getByRole('heading', { level: 1 }).waitFor();
  await fontsReady(page);

  const card = await page.evaluate(() => {
    const main = document.querySelector('main') as HTMLElement;
    const wrapper = main.parentElement as HTMLElement;
    return {
      paddingBottom: getComputedStyle(wrapper).paddingBottom,
      hasBoardMark: wrapper.querySelector('[data-board]') !== null,
    };
  });
  expect(card.paddingBottom, JSON.stringify({ card, pageTail })).toBe(pageTail);
  expect(card.hasBoardMark).toBe(false);

  await test.info().attach('нижний хвост карточки задачи', {
    body: await page.screenshot(),
    contentType: 'image/png',
  });
});
