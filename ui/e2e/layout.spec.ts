import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Заводит задачу в демо-проекте и возвращает её ключ. */
async function makeTask(
  request: APIRequestContext,
  title: string,
  sections: Record<string, unknown> = {},
): Promise<string> {
  // Разделы лежат верхним уровнем запроса, а не во вложенном `sections`: так их
  // описывает контракт (`TaskCreate` в `openapi.json`). Вложенный объект даёт 422.
  const created = await request.post('/api/v1/tasks', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      project: 'DEMO',
      title,
      description: 'Заведена сквозным тестом ради проверки раскладки карточки.',
      ...sections,
    },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { data: { key: string } }).data.key;
}

async function addEntry(
  request: APIRequestContext,
  key: string,
  body: Record<string, unknown>,
): Promise<number> {
  const response = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { no: number } }).data.no;
}

/** Высота окна: по ней считается «первый экран». */
async function viewportHeight(page: Page): Promise<number> {
  return page.evaluate(() => window.innerHeight);
}

/**
 * Задача, на которой видно, ради чего карточку открывают: одна открытая просьба,
 * сводка из четырёх частей и дело из восьми записей.
 */
async function busyTask(request: APIRequestContext): Promise<string> {
  const key = await makeTask(request, 'Задача для проверки раскладки карточки');

  await addEntry(request, key, {
    type: 'summary',
    payload: {
      done: 'Разобрался, где теряется запись: граница выборки хвоста считает строго больше.',
      remaining: 'Поправить условие и написать тест на разрыв соединения посреди выдачи.',
      blockers: 'Ничего',
      next_step: 'Переписать условие выборки хвоста в journal_page',
    },
  });

  for (let index = 0; index < 6; index += 1) {
    await addEntry(request, key, {
      type: 'note',
      title: `Заметка ${index + 1} ради длины дела`,
      body: 'Тело заметки: в описи видно только заголовок.',
    });
  }

  await addEntry(request, key, {
    type: 'question',
    title: 'Считать ли пропуск записи ошибкой контракта?',
    body: 'Нужен ответ, чтобы продолжить.',
    payload: { addressees: ['owner'], blocking: false },
  });

  return key;
}

/**
 * Задача с делом длиннее `LONG_INDEX` (12 записей, `task-page.tsx`): опись
 * показывает прыжки по себе, и есть с чем сверять левый край (UI-127).
 */
async function longCaseTask(request: APIRequestContext): Promise<string> {
  const key = await makeTask(request, 'Задача с длинной описью ради проверки шапки блока «Дело»');

  for (let index = 0; index < 14; index += 1) {
    await addEntry(request, key, {
      type: 'note',
      title: `Запись ${index + 1} ради длинной описи`,
      body: 'Тело записи: в описи видно только заголовок.',
    });
  }

  return key;
}

test.describe('карточка задачи на широком экране', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('на первом экране видно сводку, вопросы и начало описи', async ({ page, request }) => {
    const key = await busyTask(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    // Всё три ради чего карточку открывают — на первом экране, без прокрутки.
    // Раньше опись лежала за пятью разделами задания, на 1300-м пикселе.
    await expect(page.getByRole('heading', { name: 'Последняя сводка' })).toBeInViewport();
    await expect(page.getByRole('heading', { name: 'Открытые вопросы' })).toBeInViewport();
    await expect(page.getByText(/^В деле \d+ запис/)).toBeInViewport();
    await expect(page.locator('tbody tr').first()).toBeInViewport();
  });

  test('длинное задание видно целиком и ничем не обрезано', async ({ page, request }) => {
    const long = (label: string) =>
      Array.from(
        { length: 12 },
        (_, line) => `${label}: строка ${line + 1} длинного раздела.`,
      ).join('\n\n');

    const key = await makeTask(request, 'Задача с длинными разделами', {
      goal: long('Цель'),
      context: long('Контекст'),
      constraints: long('Ограничения'),
      output: long('Выход'),
      checks: Array.from({ length: 10 }, (_, index) => `Обзорная проверка номер ${index + 1}`),
    });

    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    // Последняя проверка присутствует на странице: ни гармошек, ни «первых N строк».
    await expect(page.getByText('Обзорная проверка номер 10')).toBeVisible();
    await expect(page.getByText('Цель: строка 12 длинного раздела.')).toBeVisible();

    // Ни один блок не прячет содержимое переполнением.
    const overflowing = await page.evaluate(() =>
      Array.from(document.querySelectorAll('main section'))
        .filter((node) => node.scrollHeight > node.clientHeight + 1)
        .map((node) => node.getAttribute('aria-labelledby') ?? 'без имени'),
    );
    expect(overflowing).toEqual([]);
  });

  test('пустые сводка, вопросы и замечания не рисуют трёх рамок и не съедают первый экран (UI-132)', async ({
    page,
    request,
  }) => {
    const key = await makeTask(request, 'Задача без сводки, вопросов и замечаний');
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    // Честность пустого состояния на месте: тексты никуда не делись.
    await expect(page.getByText('Сводки ещё нет', { exact: false })).toBeVisible();
    await expect(page.getByText('Вопросов без ответа нет', { exact: false })).toBeVisible();
    await expect(page.getByText('Неразобранных замечаний нет', { exact: false })).toBeVisible();

    // Свежая задача не рисует три отдельных рамки: ровно одна секция несёт все три
    // заголовка сразу, потому что подряд идущие пустые состояния сшиты в одну (UI-132).
    // Ни у одной из трёх больше нет собственной рамки с `aria-labelledby`.
    await expect(page.locator('[aria-labelledby="summary"]')).toHaveCount(0);
    await expect(page.locator('[aria-labelledby="questions"]')).toHaveCount(0);
    await expect(page.locator('[aria-labelledby="remarks"]')).toHaveCount(0);

    const frame = page
      .locator('main div')
      .filter({ hasText: 'Сводки ещё нет' })
      .filter({ hasText: 'Вопросов без ответа нет' })
      .filter({ hasText: 'Неразобранных замечаний нет' })
      .last();
    await expect(frame).toBeVisible();
    expect((await frame.boundingBox())?.height ?? 0).toBeLessThan((await viewportHeight(page)) / 4);
  });
});

test.describe('карточка задачи на узком экране', () => {
  test.use({ viewport: { width: 900, height: 800 } });

  test('всё складывается в одну колонку без горизонтальной прокрутки', async ({
    page,
    request,
  }) => {
    const key = await busyTask(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    await expect(page.getByRole('heading', { name: 'Последняя сводка' })).toBeVisible();

    // Одна колонка: блоки идут в порядке разметки, каждый следующий ниже предыдущего.
    const tops = await page.evaluate(() =>
      Array.from(document.querySelectorAll('main section')).map(
        (node) => node.getBoundingClientRect().top,
      ),
    );
    for (const [index, top] of tops.entries()) {
      if (index === 0) continue;
      expect(top).toBeGreaterThan(tops[index - 1] as number);
    }

    const scroll = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(scroll.width).toBe(scroll.client);
  });
});

test.describe('шапка блока «Дело»', () => {
  test('число записей, прыжки по описи и переход в ленту стоят вровень с заголовком и первой колонкой (UI-127)', async ({
    page,
    request,
  }) => {
    const key = await longCaseTask(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    const section = page.locator('section[aria-labelledby="case"]');
    const title = page.locator('#case');
    const toLatest = section.getByRole('button', { name: 'К свежей записи' });
    const toTop = section.getByRole('button', { name: 'В начало описи' });
    const openCase = section.getByRole('link', { name: 'Открыть всё дело лентой' });
    /*
     * Первая колонка — по номеру первой записи, а не по заголовку столбца: на 390 px
     * опись раскладывается строками-карточками, и шапка таблицы там только у диктора
     * (`sr-only`, UI-134). Номер записи виден на обеих ширинах.
     */
    const firstColumn = section.getByRole('rowheader').first();

    await expect(toLatest).toBeVisible();
    await expect(toTop).toBeVisible();

    /**
     * Левый край заголовка, обеих кнопок описи и первой колонки таблицы — одно и то
     * же число: у всех один источник поля (`BLOCK_HEAD`, `INDEX_NAV`, `CELL`), а не
     * свои `px-3` россыпью. Справа за тем же полем стоит переход в ленту. Числа идут
     * в дело задачи, а не только в исход теста: `console.log` — их не нужно
     * пересчитывать из отчёта Playwright.
     *
     * У заголовка и у кнопок поле держит родитель (`BLOCK_HEAD`/`INDEX_NAV`), а у
     * своей рамки-box они его не несут — их `boundingBox().x` и есть видимый край.
     * У ячейки `th` наоборот: поле — её собственный `px-3` (`CELL`), и рамка ячейки
     * начинается на крае таблицы, без отступа. Сравнивать нужно не рамку ячейки,
     * а край её текста — рамку плюс её же `padding-left`. В карточке описи (390 px)
     * поле несёт строка (`ROW`), у ячейки оно ноль, и та же сумма даёт край текста.
     */
    async function measure() {
      const [sectionBox, titleBox, latestBox, topBox, columnBox, linkBox, columnPadding] =
        await Promise.all([
          section.boundingBox(),
          title.boundingBox(),
          toLatest.boundingBox(),
          toTop.boundingBox(),
          firstColumn.boundingBox(),
          openCase.boundingBox(),
          firstColumn.evaluate((node) => parseFloat(getComputedStyle(node).paddingLeft)),
        ]);
      for (const box of [sectionBox, titleBox, latestBox, topBox, columnBox, linkBox]) {
        expect(box).not.toBeNull();
      }
      return {
        section: sectionBox!,
        title: titleBox!,
        toLatest: latestBox!,
        toTop: topBox!,
        firstColumnText: (columnBox!.x as number) + columnPadding,
        openCase: linkBox!,
      };
    }

    async function assertAligned(label: string) {
      const box = await measure();

      // Левый край: заголовок, первая кнопка строки прыжков (она открывает строку —
      // вторая идёт правее по той же строке, а не своим отступом) и текст первой
      // колонки совпадают до пикселя.
      expect(box.toLatest.x).toBeCloseTo(box.title.x, 0);
      expect(box.firstColumnText).toBeCloseTo(box.title.x, 0);

      // Вторая кнопка строки не съезжает за пределы блока и не наезжает на первую:
      // она правее первой на её ширину плюс зазор строки (`gap-2`, 8px).
      expect(box.toTop.x).toBeGreaterThan(box.toLatest.x + box.toLatest.width);

      // Ничто не упирается в рамку блока: слева и справа — то же поле, что у
      // заголовка и у ячеек таблицы (`px-3`), а не голый край рамки.
      const leftField = box.title.x - box.section.x;
      const rightField = box.section.x + box.section.width - (box.openCase.x + box.openCase.width);
      expect(leftField).toBeGreaterThanOrEqual(8);
      expect(rightField).toBeCloseTo(leftField, 0);

      console.log(`[UI-127 ${label}]`, {
        sectionX: box.section.x,
        titleX: box.title.x,
        toLatestX: box.toLatest.x,
        toTopX: box.toTop.x,
        firstColumnTextX: box.firstColumnText,
        openCaseRight: box.openCase.x + box.openCase.width,
        leftField,
        rightField,
      });
    }

    /**
     * Снимок для дела: `locator.screenshot()` перед съёмкой сам подкручивает узел
     * так, что его верх упирается в самый верх области прокрутки, — а туда же
     * прибита липкая `TaskNav`, и она перекрывает шапку блока на снимке. Ручная
     * прокрутка этого не лечит: тот же внутренний скролл сотрёт её перед съёмкой.
     * Поэтому здесь `page.screenshot({ clip })` по свежему прямоугольнику блока
     * после собственной прокрутки с запасом на высоту навигации — сам вызов уже
     * ничего не подкручивает.
     */
    async function screenshotHead(path: string) {
      await section.scrollIntoViewIfNeeded();
      // Липкая навигация задачи, а не переключатель вида и не справка о разделах:
      // у неё своя подпись (`task.nav.label`, `TaskNav`).
      const nav = page.getByRole('navigation', { name: /Навигация по задаче/ });
      const navBox = await nav.boundingBox();
      if (navBox !== null) {
        await page.evaluate((dy) => window.scrollBy(0, dy), -(navBox.height + 8));
      }
      const clip = await section.boundingBox();
      expect(clip).not.toBeNull();
      await page.screenshot({ path: test.info().outputPath(path), clip: clip! });
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await assertAligned('1440 светлая');
    await screenshotHead('case-head-1440-light.png');

    await page.emulateMedia({ colorScheme: 'dark' });
    await assertAligned('1440 тёмная');
    await screenshotHead('case-head-1440-dark.png');

    await page.setViewportSize({ width: 390, height: 844 });
    await assertAligned('390 тёмная');
    await screenshotHead('case-head-390-dark.png');

    await page.emulateMedia({ colorScheme: 'light' });
    await assertAligned('390 светлая');
    await screenshotHead('case-head-390-light.png');
  });
});
