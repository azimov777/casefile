import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { fontsReady, side, signedInByHand, silenceJournal } from './contour';

/** Экраны, на которых оболочка обязана держаться одинаково. */
const SCREENS = ['/tasks?queue=DEMO', '/tasks/DEMO-6', '/tasks/DEMO-1/case', '/questions'];

/**
 * Рамка таблицы списка. Ищется от таблицы, а не по имени: имя и роль области у рамки
 * есть не на всякой ширине — она объявляет себя прокручиваемой ровно там, где
 * прокручивается, и это проверяют сценарии «рамка таблицы на … экране» (UI-91).
 */
function frame(page: Page): Locator {
  return page.getByRole('table').locator('xpath=..');
}

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
  // Выход есть только там, где человек входил руками: на локальной установке ключ
  // отдаёт она сама, и выходить некуда.
  await signedInByHand(page);
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();

  const opener = page.getByRole('button', { name: /Показать разделы/ });
  await opener.focus();
  await expect(opener).toBeFocused();
  await page.keyboard.press('Enter');

  const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
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
    /*
     * Карточка задачи (`/tasks/DEMO-6`) рисует `main` уже в состоянии загрузки, до
     * прихода пакета: `h1` там появляется только с ним. `axe`, попавший в этот миг,
     * ловит `page-has-heading-one` (moderate) — гонку измерения с загрузкой, а не
     * дефект экрана (`docs/notes/testing.md`, UI-100). На загруженном экране `h1`
     * есть везде из четырёх адресов.
     */
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations, address).toEqual([]);
  }
});

/**
 * Строка списка на узком экране — карточка той же разметки (UI-134). До неё таблица
 * прокручивалась вбок внутри рамки: на 390 px читались ключ, название до пятнадцати
 * знаков и статус, а остальное пряталось за 428 px прокрутки.
 */
test('на узком экране строка списка — карточка: название переносится, все значения на виду', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();
  await fontsReady(page);

  // Прокручивать вбок нечего ни странице, ни рамке.
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  expect(
    await frame(page).evaluate((node) => node.scrollWidth - node.clientWidth),
  ).toBeLessThanOrEqual(0);

  const rows = await page.locator('tbody tr').evaluateAll((nodes) =>
    nodes.map((row) => {
      const title = row.querySelector('[data-link="task"] span');
      const cells = Array.from(row.children).map((cell) => cell.getBoundingClientRect());
      const visible = cells.filter((box) => box.width > 0);
      const box = title?.getBoundingClientRect();
      const style = title === null ? null : getComputedStyle(title);
      return {
        display: getComputedStyle(row).display,
        // Все показанные ячейки — в окне, а не за его правым краем.
        inside: visible.every((cell) => cell.left >= 0 && cell.right <= window.innerWidth),
        titleWidth: Math.round(box?.width ?? 0),
        whiteSpace: style?.whiteSpace ?? '',
        // Сколько строк занимает название и не обрезано ли оно.
        lines: style === null ? 0 : Math.round((box?.height ?? 0) / parseFloat(style.lineHeight)),
        clipped: title === null ? true : title.scrollHeight > title.clientHeight + 1,
      };
    }),
  );

  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    expect(row.display).toBe('flex');
    expect(row.inside).toBe(true);
    // Название переносится, а не режется многоточием в одну строку.
    expect(row.whiteSpace).not.toBe('nowrap');
    expect(row.titleWidth).toBeGreaterThan(200);
    // Названия демо короче трёх строк и читаются целиком.
    expect(row.clipped).toBe(false);
  }
  // И хотя бы одно из них и правда стоит в две строки и больше: иначе проверка
  // переноса ничего не проверила бы.
  expect(Math.max(...rows.map((row) => row.lines))).toBeGreaterThanOrEqual(2);

  // Шапки на виду нет, но диктор по-прежнему называет колонки.
  await expect(page.getByRole('columnheader', { name: 'Название' })).toHaveCount(1);
  await expect(page.locator('thead')).toHaveCSS('position', 'absolute');

  // Карточка ведёт в задачу кликом по любому месту, как и строка таблицы.
  const first = page.locator('tbody tr').first();
  const key = (await first.locator('th').textContent())?.trim() ?? '';
  await first.locator('td').last().click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${key}$`));
});

/**
 * Полоса ширин, на которой боковая панель уже стоит, а места таблице ещё не хватает:
 * от `fold` (44rem) до `wide` (64rem). Ровно здесь колонка названия схлопывалась
 * в многоточие без всякого выхода (UI-66) — потому что ветку выбирала ширина окна,
 * а место отнимала панель. Телефонные 320 и 390 стоят в том же ряду с UI-134: там
 * строки — карточки, и название обязано получить своё место и в них.
 *
 * Края взяты обе штуки, а не только они: 1016 и 1017 стоят под самым порогом, где
 * прежняя арифметика давала названию 182 px, а 1024 — сразу за ним.
 */
const BAND = [320, 390, 704, 768, 800, 900, 960, 1000, 1016, 1017, 1024];

/**
 * Наименьшая ширина колонки названия. Это остаток от `min-w-list` после заданных ширин
 * остальных колонок; ниже него таблица не сжимается, а прокручивается.
 */
const TITLE_MIN = 184;

test('ни на одной ширине название не схлопывается, а рамка не прокручивается', async ({ page }) => {
  await silenceJournal(page);

  for (const width of BAND) {
    await page.setViewportSize({ width, height: 720 });
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();
    await fontsReady(page);

    // Место названию отмерено, а не отобрано: 66 px на 900 px и ноль на 704 px — это
    // то, что было до UI-66. Мерится ячейка первой строки: в карточках шапки на виду
    // нет, а ширину названию даёт строка.
    const title = await page.locator('tbody tr').first().locator('td').first().boundingBox();
    expect(Math.round(title?.width ?? 0), `название на ${width} px`).toBeGreaterThanOrEqual(
      TITLE_MIN,
    );

    // Прятать за прокруткой нечего: где столбцам не хватает места, строка — карточка
    // (UI-134), и последнее значение строки стоит в окне.
    const hidden = await frame(page).evaluate((node) => node.scrollWidth - node.clientWidth);
    expect(hidden, `рамка на ${width} px`).toBeLessThanOrEqual(0);
    await expect(page.locator('tbody tr').first().locator('td').last()).toBeInViewport();

    expect(await overflow(page), `документ на ${width} px`).toBeLessThanOrEqual(0);
  }
});

test('на широком экране таблица не прокручивается, а шапка липнет к верху', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();
  await fontsReady(page);

  const scroller = frame(page);
  // Прокручивать нечего: колонки помещаются, и обёртка остаётся `clip` — без этого
  // липкая шапка прилипала бы к ней вместо окна (требование UI-12).
  const overflowX = await scroller.evaluate((node) => node.scrollWidth - node.clientWidth);
  expect(overflowX).toBeLessThanOrEqual(0);

  await page.mouse.wheel(0, 600);
  const head = page.getByRole('columnheader', { name: 'Активность' });
  await expect(head).toBeInViewport();
});

/**
 * Состояние рамки, снятое у браузера, а не у разметки: ветку выбирает запрос
 * к контейнеру, и в разметке её не видно.
 */
async function frameState(page: Page): Promise<{
  overflowX: string;
  hidden: number;
  role: string | null;
  label: string | null;
  tabindex: string | null;
}> {
  return frame(page).evaluate((node) => ({
    overflowX: getComputedStyle(node).overflowX,
    hidden: node.scrollWidth - node.clientWidth,
    role: node.getAttribute('role'),
    label: node.getAttribute('aria-label'),
    tabindex: node.getAttribute('tabindex'),
  }));
}

/*
 * Подпись рамки обязана говорить правду на обоих краях развилки, и ширина здесь —
 * условие сценария, а не шаг внутри него: поэтому `test.use({ viewport })`, а не
 * `setViewportSize` (`docs/notes/tooling.md`, «Вьюпорт для замеров вёрстки задаёт
 * Playwright»).
 */
test.describe('рамка таблицы на широком экране', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('прокрутки нет — и про прокрутку не сказано ничего', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();
    await fontsReady(page);

    const state = await frameState(page);
    // Ветка `clip`, и прокручивать нечего: стрелки в этой рамке дают ноль.
    expect(state.overflowX).toBe('clip');
    expect(state.hidden).toBeLessThanOrEqual(0);

    // Ни имени, ни роли, ни остановки табом. Раньше здесь стояло имя «Задачи, таблица
    // прокручивается вбок» — обещание, которое человек проверял стрелками и не получал
    // ничего (UI-91).
    expect(state.role).toBeNull();
    expect(state.label).toBeNull();
    expect(state.tabindex).toBeNull();
    await expect(page.getByRole('region', { name: /прокручивается вбок/ })).toHaveCount(0);

    // Взамен таблицу диктору представляет её `caption`: роль таблицы, подписанные
    // колонки и число строк на месте.
    await expect(page.getByRole('table')).toHaveAccessibleName(/На этой странице \d+ задач/);
  });
});

test.describe('рамка таблицы на узком экране', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('прокрутки нет — и про прокрутку не сказано ничего', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();
    await fontsReady(page);

    // До UI-134 здесь была ветка `auto`: рамка прокручивалась на 428 px и называла себя
    // областью «Задачи, таблица прокручивается вбок». Теперь строки — карточки, и
    // прокручивать нечего на обеих ширинах.
    const state = await frameState(page);
    expect(state.overflowX).toBe('clip');
    expect(state.hidden).toBeLessThanOrEqual(0);
    expect(state.role).toBeNull();
    expect(state.label).toBeNull();
    expect(state.tabindex).toBeNull();
    await expect(page.getByRole('table')).toHaveAccessibleName(/На этой странице \d+ задач/);
  });
});

test('раскладка строки следует за шириной места, а не за загрузкой страницы', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();
  await fontsReady(page);

  const row = page.locator('tbody tr').first();
  await expect(row).toHaveCSS('display', 'table-row');

  // Ширина меняется без перезагрузки: карточкой строку делает запрос к контейнеру, а не
  // замер, снятый при загрузке.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(row).toHaveCSS('display', 'flex');

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(row).toHaveCSS('display', 'table-row');
});

test('на карточке замечание доступно до описи и одним действием из навигации', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tasks/DEMO-3');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-3');

  /*
   * Порядок чтения, а не только вид: блок замечаний стоит в разметке до описи дела.
   * Сверяется по заголовкам, а не по `aria-labelledby` секций: у DEMO-3 сводка,
   * вопросы и замечания пусты и делят одну слитую рамку без `aria-labelledby`
   * (UI-132) — заголовок при этом остаётся `<h2>` независимо от того, пуст блок
   * или нет.
   */
  const remarksBeforeCase = await page.evaluate(() => {
    const heading = (text: string) =>
      Array.from(document.querySelectorAll('main h2')).find((node) => node.textContent === text);
    const remarks = heading('Замечания');
    const caseHeading = heading('Дело');
    if (remarks === undefined || caseHeading === undefined) return false;
    return Boolean(remarks.compareDocumentPosition(caseHeading) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(remarksBeforeCase).toBe(true);

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

