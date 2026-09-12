import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal, tasksByStatus } from './contour';

/**
 * Системная полоса macOS — историческая точка отсчёта: headed-прогоном на этой же
 * доске измерено 15 px и у столбца (по ширине), и у ряда (по высоте) — UI-115#6.
 * Своя обязана быть у́же: об этом и была просьба владельца.
 *
 * Прогон видит полосу потому, что `playwright.config.ts` снимает `--hide-scrollbars`
 * (UI-116#29) — окно для этого больше не нужно, и `headless: false` здесь убран.
 */
const SYSTEM_SCROLLBAR = 15;

const SHORT_WINDOW = { width: 1024, height: 420 };

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

/** Доска с переполненным столбцом и с рядом, который не влезает вбок. */
async function board(page: Page, request: Parameters<typeof tasksByStatus>[0]): Promise<string> {
  const all = await tasksByStatus(request);
  const longest = [...all.entries()].sort(([, left], [, right]) => right.length - left.length)[0];
  expect(longest, 'в демо нет ни одной задачи').toBeDefined();
  const [status] = longest as [string, string[]];

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);
  return status;
}

/**
 * Замер полосы у двух узлов доски: у столбца со своей прокруткой (UI-68) — по ширине,
 * у ряда столбцов — по высоте.
 *
 * Ширина «заданная в стилях» не переписана сюда числом: её отдаёт сам браузер —
 * вычисленным стилем псевдоэлемента `::-webkit-scrollbar` и пробным узлом шириной
 * в токен `--ui-scrollbar`. Число в тесте разошлось бы с `reset.css` молча.
 */
function measure(page: Page, status: string) {
  return page.evaluate((scrolled) => {
    const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
      (node) => node.getAttribute('aria-label') !== 'Отбор задач',
    ) as HTMLElement[];
    const mine = sections.find(
      (node) => node.getAttribute('aria-label') === scrolled,
    ) as HTMLElement;
    const row = sections[0]?.parentElement as HTMLElement;

    const probe = document.createElement('div');
    probe.style.cssText = 'position:absolute;top:0;left:0;height:0;width:var(--ui-scrollbar)';
    probe.style.color = 'var(--color-faint)';
    document.body.append(probe);
    const declared = probe.getBoundingClientRect().width;
    // Цвет токена в том же виде, в каком его печатает вычисленный стиль ползунка:
    // `getPropertyValue` вернул бы `#676c7c`, а заливка приходит как `rgb(…)`.
    const token = getComputedStyle(probe).color;
    probe.remove();

    const room = (node: HTMLElement, style: CSSStyleDeclaration) => ({
      // Граница входит в `offsetWidth` наравне с полосой — её надо вычесть, иначе
      // мерилась бы рамка столбца, а не полоса.
      vertical:
        node.offsetWidth -
        node.clientWidth -
        Number.parseFloat(style.borderLeftWidth) -
        Number.parseFloat(style.borderRightWidth),
      horizontal:
        node.offsetHeight -
        node.clientHeight -
        Number.parseFloat(style.borderTopWidth) -
        Number.parseFloat(style.borderBottomWidth),
    });

    const mineStyle = getComputedStyle(mine);
    const rowStyle = getComputedStyle(row);
    return {
      declared,
      token,
      // Столбец переполнен по вертикали, ряд — вбок: иначе полосе неоткуда взяться.
      columnOver: mine.scrollHeight - mine.clientHeight,
      rowOver: row.scrollWidth - row.clientWidth,
      columnBar: room(mine, mineStyle).vertical,
      rowBar: room(row, rowStyle).horizontal,
      // Что браузер посчитал для самой прокручиваемой рамки, а не что написано в
      // `reset.css`: оформление обязано дойти до узла, а не остаться объявлением.
      columnWidth: getComputedStyle(mine, '::-webkit-scrollbar').width,
      rowHeight: getComputedStyle(row, '::-webkit-scrollbar').height,
      columnThumb: getComputedStyle(mine, '::-webkit-scrollbar-thumb').backgroundColor,
      rowThumb: getComputedStyle(row, '::-webkit-scrollbar-thumb').backgroundColor,
      // Стандартная пара под `@supports not selector(::-webkit-scrollbar)` до этого
      // движка доходить не должна: увидев её, он погасил бы наш ползунок (UI-116#28).
      standardWidth: mineStyle.scrollbarWidth,
      standardColor: mineStyle.scrollbarColor,
    };
  }, status);
}

test('полосу рисуем мы: толщина наша, цвет ползунка — токен темы', async ({ page, request }) => {
  const status = await board(page, request);
  const measured = await measure(page, status);
  const report = JSON.stringify(measured);
  console.log(`[UI-116 ${status}]`, report);

  await test.info().attach('после правки: столбец со своей полосой', {
    body: await column(page, status).screenshot(),
    contentType: 'image/png',
  });

  expect(measured.columnOver, `столбцу ${status} нечего прокручивать`).toBeGreaterThan(0);
  expect(measured.rowOver, 'ряду столбцов нечего прокручивать вбок').toBeGreaterThan(0);

  // Стандартная пара досталась бы только движку без псевдоэлементов; здесь её нет.
  expect(measured.standardWidth, report).toBe('auto');
  expect(measured.standardColor, report).toBe('auto');

  // Оформление дошло до обоих узлов и обе оси одинаковы.
  expect(measured.columnWidth, report).toBe(`${measured.declared}px`);
  expect(measured.rowHeight, report).toBe(`${measured.declared}px`);

  // Место, которое полоса заняла, — ровно то, что задано стилями: не системное и
  // не ноль. Оба конца важны: ноль был у оверлейной полосы (UI-116#8), системные
  // 15 px — то, что владелец назвал толстым.
  expect(measured.columnBar, report).toBe(measured.declared);
  expect(measured.rowBar, report).toBe(measured.declared);
  expect(measured.declared, report).toBeGreaterThan(0);
  expect(measured.declared, report).toBeLessThan(SYSTEM_SCROLLBAR);

  // Цвет ползунка — точное значение токена темы, своё в каждой теме.
  expect(measured.columnThumb, report).toBe(measured.token);
  expect(measured.rowThumb, report).toBe(measured.token);
});

/**
 * Запасной путь для движков без `::-webkit-scrollbar` (Firefox). Прогнать его
 * настоящим Firefox набор не может — в нём один Chromium, — но проверить, что пара
 * значений применима и что именно она делает, можно и здесь: объявленная на живой
 * странице, она перебивает псевдоэлементы (старшинство — находка UI-116#28) и
 * возвращает ту самую системную полосу, ради ухода от которой задача и заведена.
 *
 * Снимок отсюда — «до правки» для дела UI-116: ровно то, что рисует `main`.
 */
test('запасной путь: стандартная пара применима и отменяет наш ползунок', async ({
  page,
  request,
}) => {
  const status = await board(page, request);

  await page.addStyleTag({
    content:
      ':root { scrollbar-color: var(--color-faint) transparent } * { scrollbar-width: thin }',
  });
  const fallback = await measure(page, status);
  console.log(`[UI-116 запасной путь ${status}]`, JSON.stringify(fallback));

  await test.info().attach('до правки: столбец с системной полосой', {
    body: await column(page, status).screenshot(),
    contentType: 'image/png',
  });

  // Пара дошла до узла со своей прокруткой — значит движку без псевдоэлементов
  // достанется оформленная полоса, а не голая системная.
  expect(fallback.standardWidth).toBe('thin');
  expect(fallback.standardColor).not.toBe('auto');

  // И она же гасит наш ползунок: место, которое он занимал, больше не наше.
  expect(fallback.columnBar).not.toBe(fallback.declared);
});
