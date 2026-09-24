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
  await page.goto('/tasks?project=DEMO&view=board&collapsed=');
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

    // Тот же приём для цвета ползунка (UI-157): пробный узел с той же заливкой,
    // что назначает `reset.css`, а не переписанное сюда числом имя цвета — иначе
    // `oklab(…)`, который печатает вычисленный стиль, разошёлся бы с процентом
    // прозрачности в `theme.css` молча.
    const thumbProbe = document.createElement('div');
    thumbProbe.style.cssText =
      'position:absolute;top:0;left:0;background-color:var(--ui-scrollbar-thumb)';
    document.body.append(thumbProbe);
    const thumbToken = getComputedStyle(thumbProbe).backgroundColor;
    thumbProbe.remove();

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
    const head = mine.querySelector('h2') as HTMLElement;
    return {
      declared,
      token,
      thumbToken,
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
      // Верхняя граница дорожки столбца — не выше нижнего края заголовка (UI-157):
      // высота заголовка и отступ дорожки, назначенный тем же замером
      // (`[data-board-column]`, `reset.css`).
      headHeight: head.getBoundingClientRect().height,
      trackMarginTop: Number.parseFloat(
        getComputedStyle(mine, '::-webkit-scrollbar-track').marginTop,
      ),
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
  expect(measured.columnThumb, report).toBe(measured.thumbToken);
  expect(measured.rowThumb, report).toBe(measured.thumbToken);

  /*
   * Верхняя граница дорожки столбца не выше нижнего края его заголовка (UI-157):
   * отступ дорожки — не меньше высоты заголовка. Строгое «не меньше», а не
   * равенство: `margin-top` целое число CSS-пикселей, а высота заголовка —
   * дробная (шрифт), и округление обязано идти в пользу заголовка, а не полосы,
   * которая тогда зашла бы на подпись на доли пикселя.
   */
  expect(measured.trackMarginTop, report).toBeGreaterThanOrEqual(Math.floor(measured.headHeight));
  // И не заметно больше — иначе дорожка ушла бы вниз в пустоту под заголовком,
  // забрав у полосы место, которое ей не мешало (запас — сама сборка `margin-top`
  // целым числом, `Math.ceil` от дробной высоты).
  expect(measured.trackMarginTop, report).toBeLessThanOrEqual(Math.ceil(measured.headHeight) + 1);
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

/**
 * Отношение контраста по WCAG — то же число, которое считает `axe` (формула
 * повторена в нескольких сквозных файлах проекта, своей общей утилиты для неё нет).
 */
function contrast(front: string, back: string): number {
  const channel = (part: number) => {
    const value = part / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (color: string) => {
    const [r, g, b] = (color.match(/[\d.]+/g) ?? []).map(Number) as [number, number, number];
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const first = luminance(front);
  const second = luminance(back);
  return (
    Math.round(((Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)) * 100) / 100
  );
}

/**
 * Контраст ползунка к фону столбца ниже прежнего, но не ниже порога органа
 * управления (UI-157). Владелец в Safari 18.6 назвал полосу слишком выразительной;
 * прежний сплошной `--color-faint` держал контраст далеко с запасом от порога
 * (WCAG 1.4.11, 3.0) — числа записаны находкой в деле задачи, а не только здесь,
 * потому что «до» этот прогон, идущий на уже поправленном коде, снять не может.
 *
 * `getComputedStyle` возвращает ползунок в `oklab(…)`, потому что в этом цветовом
 * пространстве смешан токен (`theme.css`): цвет читается через канву, а не разбором
 * строки — `oklab` не раскладывается на компоненты той же регуляркой, что `rgb`.
 */
test('контраст ползунка ниже прежнего, но не ниже порога органа управления', async ({
  page,
  request,
}) => {
  const status = await board(page, request);

  const measured = await page.evaluate((scrolled) => {
    const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
      (node) => node.getAttribute('aria-label') !== 'Отбор задач',
    ) as HTMLElement[];
    const mine = sections.find((node) => node.getAttribute('aria-label') === scrolled) as Element;

    /*
     * Ползунок полупрозрачен (UI-157), и его настоящий цвет на экране — не свой
     * канал сам по себе, а смесь с тем, что под ним: рисуем на канве сперва
     * непрозрачную поверхность, потом полупрозрачный ползунок поверх неё (то же
     * «source-over», которым рисует сам браузер), и читаем итог — только тогда
     * числа отвечают на вопрос «что видно», а не «чем красили».
     */
    const onto = (back: string, front: string) => {
      const canvas = document.createElement('canvas');
      canvas.width = 1;
      canvas.height = 1;
      const ctx = canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
      ctx.fillStyle = back;
      ctx.fillRect(0, 0, 1, 1);
      ctx.fillStyle = front;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
      return `rgb(${r}, ${g}, ${b})`;
    };

    const surfaces = () => {
      const probe = document.createElement('div');
      document.body.append(probe);
      const read = (cls: string) => {
        probe.className = cls;
        const color = getComputedStyle(probe).backgroundColor;
        return color;
      };
      const result = {
        ground: read('bg-ground'),
        surface: read('bg-surface'),
        sunken: read('bg-sunken'),
      };
      probe.remove();
      return result;
    };

    const thumb = getComputedStyle(mine, '::-webkit-scrollbar-thumb').backgroundColor;
    const back = surfaces();
    return {
      thumb: {
        ground: onto(back.ground, thumb),
        surface: onto(back.surface, thumb),
        sunken: onto(back.sunken, thumb),
      },
      surfaces: back,
    };
  }, status);

  const ratios = {
    ground: contrast(measured.thumb.ground, measured.surfaces.ground),
    surface: contrast(measured.thumb.surface, measured.surfaces.surface),
    sunken: contrast(measured.thumb.sunken, measured.surfaces.sunken),
  };
  const report = JSON.stringify({ ...measured, ratios });
  console.log(`[UI-157 контраст ${status}]`, report);
  await test.info().attach(`контраст ползунка (${status})`, {
    body: report,
    contentType: 'application/json',
  });

  // Порог органа управления — WCAG 1.4.11, 3.0 (тот же, что `theme.test.ts` держит
  // для сплошного `--color-faint`, но у полупрозрачного ползунка своей проверки
  // не было).
  expect(Math.min(ratios.ground, ratios.surface, ratios.sunken), report).toBeGreaterThanOrEqual(3);
});
