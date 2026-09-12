import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal, tasksByStatus } from './contour';

/*
 * Playwright без окна запускает Chromium с `--hide-scrollbars`: полосы там нулевой
 * ширины и до правки, и после — измерить оформление такой прогон не может (UI-115#6).
 * Настоящую полосу видно только в окне, и это единственный файл в наборе, где оно есть:
 * headless по умолчанию быстрее и полосы прокрутки не касается ничем, кроме этого места.
 */
test.use({ headless: false });

/**
 * Системная полоса без оформления — историческая точка отсчёта: headed-прогоном на
 * этой же доске измерено 15 px и у столбца (по ширине), и у ряда (по высоте) — UI-115#6.
 *
 * Число не устойчиво на этой машине: у macOS «Show scroll bars» стоит в значении по
 * умолчанию «Automatically based on input device» (ключ `AppleShowScrollBars` не задан
 * ни в одном домене — проверено `defaults read`), и полоса переключается между
 * оверлейной (места не занимает вовсе) и классической (занимает системную ширину) по
 * тому, какое устройство ввода использовалось системой последним, — от кода это не
 * зависит и настоящим движением мыши и колеса из Playwright не переключается (замерено:
 * четыре headed-прогона подряд, до правки и после, дают один и тот же результат).
 * Поэтому граница ниже — потолок «не толще системной», а не жёсткое «между 0 и 15»:
 * когда система показывает оверлей, полосы нет и без нашего оформления, и это не
 * регресс; когда она показывает классику, `thin` обязана быть у́же неё.
 */
const SYSTEM_SCROLLBAR = 15;

const SHORT_WINDOW = { width: 1024, height: 420 };

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

test('оформление полосы применено, а место, которое она занимает, не выросло', async ({
  page,
  request,
}) => {
  const all = await tasksByStatus(request);
  const longest = [...all.entries()].sort(([, left], [, right]) => right.length - left.length)[0];
  expect(longest, 'в демо нет ни одной задачи').toBeDefined();
  const [status] = longest as [string, string[]];

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const measured = await page.evaluate((scrolled) => {
    const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
      (node) => node.getAttribute('aria-label') !== 'Отбор задач',
    ) as HTMLElement[];
    const mine = sections.find(
      (node) => node.getAttribute('aria-label') === scrolled,
    ) as HTMLElement;
    const row = sections[0]?.parentElement as HTMLElement;
    const mineStyle = getComputedStyle(mine);
    const rowStyle = getComputedStyle(row);
    return {
      // Столбец переполнен по вертикали — своя прокрутка (UI-68) должна быть заведена,
      // иначе ширину, разведённую полосой, сравнивать не с чем.
      columnOver: mine.scrollHeight - mine.clientHeight,
      columnBorder:
        Number.parseFloat(mineStyle.borderLeftWidth) +
        Number.parseFloat(mineStyle.borderRightWidth),
      columnBar: mine.offsetWidth - mine.clientWidth,
      // Ряд переполнен вбок (UI-94): на 1024px шесть столбцов доски не влезают.
      rowOver: row.scrollWidth - row.clientWidth,
      rowBorder:
        Number.parseFloat(rowStyle.borderTopWidth) + Number.parseFloat(rowStyle.borderBottomWidth),
      rowBar: row.offsetHeight - row.clientHeight,
      // Наследуемое оформление: не полагаемся на то, что оно есть, — читаем то, что
      // браузер посчитал для самого узла со своей прокруткой.
      columnScrollbarWidth: mineStyle.scrollbarWidth,
      columnScrollbarColor: mineStyle.scrollbarColor,
      rowScrollbarWidth: rowStyle.scrollbarWidth,
      rowScrollbarColor: rowStyle.scrollbarColor,
    };
  }, status);

  expect(measured.columnOver, `столбцу ${status} нечего прокручивать`).toBeGreaterThan(0);
  expect(measured.rowOver, 'ряду столбцов нечего прокручивать вбок').toBeGreaterThan(0);

  // Снимок столбца с полосой — доказательство для дела задачи (UI-116), а не только
  // числа: следующая правка внешнего вида полосы найдёт здесь, с чем сравнить взглядом.
  await test.info().attach('столбец с полосой прокрутки', {
    body: await column(page, status).screenshot(),
    contentType: 'image/png',
  });

  const report = JSON.stringify(measured);
  console.log(`[UI-116 ${status}]`, report);

  // Оформление дошло до обоих узлов вычисленным стилем — не только объявлением
  // в `reset.css`, а тем, что видит браузер на самой прокручиваемой рамке.
  expect(measured.columnScrollbarWidth, report).toBe('thin');
  expect(measured.rowScrollbarWidth, report).toBe('thin');
  expect(measured.columnScrollbarColor, report).not.toBe('auto');
  expect(measured.rowScrollbarColor, report).not.toBe('auto');

  // Место, которое фактически заняла полоса (граница в offsetWidth/offsetHeight не
  // в счёт): не отрицательное и не толще системной — то же самое верно и там, где
  // систему в данный момент прячет полосы сама (см. комментарий у SYSTEM_SCROLLBAR).
  const columnScrollbar = measured.columnBar - measured.columnBorder;
  const rowScrollbar = measured.rowBar - measured.rowBorder;
  expect(columnScrollbar, report).toBeGreaterThanOrEqual(0);
  expect(columnScrollbar, report).toBeLessThanOrEqual(SYSTEM_SCROLLBAR);
  expect(rowScrollbar, report).toBeGreaterThanOrEqual(0);
  expect(rowScrollbar, report).toBeLessThanOrEqual(SYSTEM_SCROLLBAR);
});
