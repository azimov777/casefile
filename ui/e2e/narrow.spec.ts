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

/**
 * Полоса ширин, на которой боковая панель уже стоит, а места таблице ещё не хватает:
 * от `fold` (44rem) до `wide` (64rem). Ровно здесь колонка названия схлопывалась
 * в многоточие без всякого выхода (UI-66) — потому что ветку выбирала ширина окна,
 * а место отнимала панель.
 *
 * Края взяты обе штуки, а не только они: 1016 и 1017 стоят под самым порогом, где
 * прежняя арифметика давала названию 182 px, а 1024 — сразу за ним.
 */
const BAND = [704, 768, 800, 900, 960, 1000, 1016, 1017, 1024];

/**
 * Наименьшая ширина колонки названия. Это остаток от `min-w-list` после заданных ширин
 * остальных колонок; ниже него таблица не сжимается, а прокручивается.
 */
const TITLE_MIN = 184;

test('в полосе от 44rem до 64rem название не схлопывается ни на одной ширине', async ({ page }) => {
  await silenceJournal(page);

  for (const width of BAND) {
    await page.setViewportSize({ width, height: 720 });
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();
    await fontsReady(page);

    const scroller = frame(page);
    const title = await page.getByRole('columnheader', { name: 'Название' }).boundingBox();

    // Место названию отмерено, а не отобрано: 66 px на 900 px и ноль на 704 px — это
    // то, что было до UI-66.
    expect(Math.round(title?.width ?? 0), `название на ${width} px`).toBeGreaterThanOrEqual(
      TITLE_MIN,
    );

    // Всё, что не поместилось, достижимо прокруткой внутри рамки: последняя колонка
    // приезжает в рамку целиком, а страница вширь не едет.
    const hidden = await scroller.evaluate((node) => node.scrollWidth - node.clientWidth);
    const last = page.getByRole('columnheader', { name: 'Активность' });
    if (hidden > 0) {
      await scroller.evaluate((node) => {
        node.scrollLeft = node.scrollWidth;
      });
      await expect
        .poll(
          async () => {
            const frame = await scroller.boundingBox();
            const box = await last.boundingBox();
            return (frame?.x ?? 0) + (frame?.width ?? 0) - ((box?.x ?? 0) + (box?.width ?? 0));
          },
          { message: `последняя колонка на ${width} px` },
        )
        .toBeGreaterThanOrEqual(-1);
    } else {
      // Не поместиться нечему: таблица кончается внутри рамки, и обрезать её незачем.
      await expect(last).toBeInViewport();
    }

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

  test('прокрутка есть — и рамка называет себя прокручиваемой', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.getByRole('table')).toBeVisible();
    await fontsReady(page);

    const state = await frameState(page);
    expect(state.overflowX).toBe('auto');
    expect(state.hidden).toBeGreaterThan(0);
    expect(state.label).toBe('Задачи, таблица прокручивается вбок');

    // Названное областью обязано быть достижимо с клавиатуры: иначе имя обещает то,
    // до чего не добраться ничем, кроме мыши.
    const scroller = page.getByRole('region', { name: 'Задачи, таблица прокручивается вбок' });
    await scroller.focus();
    await expect(scroller).toBeFocused();
  });
});

test('имя рамки следует за шириной места, а не за загрузкой страницы', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('table')).toBeVisible();
  await fontsReady(page);

  const named = page.getByRole('region', { name: /таблица прокручивается вбок/ });
  await expect(named).toHaveCount(0);

  // Ширина меняется без перезагрузки: имя обязано появиться от наблюдателя размеров,
  // а не от нового кадра страницы. Замер, снятый один раз при загрузке, эту проверку
  // не проходит — а именно им подпись и была.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(named).toHaveCount(1);

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(named).toHaveCount(0);
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
