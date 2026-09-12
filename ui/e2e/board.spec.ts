import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { contractStatuses, fontsReady, silenceJournal, tasksByStatus } from './contour';

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

test('доска показывает по столбцу на каждый статус контракта с теми же задачами, что и бэкенд', async ({
  page,
  request,
}) => {
  await silenceJournal(page);
  const calls: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks?')) calls.push(call.url());
  });

  const expected = await tasksByStatus(request);
  const statuses = contractStatuses();

  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, statuses[0] as string)).toBeVisible();
  await expect(column(page, 'open').getByRole('article').first()).toBeVisible();

  /*
   * По запросу на столбец и один на число выдачи (UI-70). Раскрытый столбец читает
   * свою первую страницу, свёрнутый — только своё число: сотню закрытых задач ради
   * счётчика в заголовке никто не читает. Число выдачи спрашивается отдельно, потому
   * что сложить его из шести столбцов нельзя — свёрнутые не читают вовсе.
   */
  await expect
    .poll(() => calls.length, { message: 'запросов на отрисовку доски' })
    .toBe(statuses.length + 1);
  const counting = calls.filter((url) => new URL(url).searchParams.get('limit') === '1');
  expect(counting, 'число выдачи и числа свёрнутых столбцов').toHaveLength(3);

  for (const status of statuses) {
    const section = column(page, status);
    await expect(section).toBeVisible();

    // Свёрнутый столбец сначала разворачиваем: карточек в нём не видно намеренно.
    const toggle = section.getByRole('button');
    if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();

    const keys = expected.get(status) ?? [];
    // Карточка, а не ссылка: ссылка теперь одна на карточку и названа названием
    // задачи, а не ключом — в задачу ведёт вся карточка (`task-card.tsx`).
    await expect(section.getByRole('article')).toHaveCount(keys.length);
    for (const key of keys) {
      await expect(section.getByRole('article').filter({ hasText: key })).toBeVisible();
    }

    // Число в заголовке — от бэкенда и точное: «из ?» после UI-70 остаётся только
    // на случай, когда выдачу не посчитали вовсе.
    await expect(toggle).toContainText(String(keys.length));
  }
});

test('раскрытие столбца не сужает соседей и не двигает карточки, которые читают', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, 'open').getByRole('article').first()).toBeVisible();

  const widths = () =>
    page.evaluate(() =>
      Array.from(document.querySelectorAll('section[aria-label]'))
        .filter((node) => node.getAttribute('aria-label') !== 'Отбор задач')
        .map((node) => Math.round(node.getBoundingClientRect().width)),
    );
  const cardTop = () =>
    column(page, 'open')
      .getByRole('article')
      .first()
      .boundingBox()
      .then((box) => Math.round(box?.y ?? Number.NaN));

  // Замеры «до» и «после» обязаны быть сняты одним шрифтом: Fira приходит с внешнего
  // хоста и после подстановки двигает карточку на пиксель — точное сравнение падало бы
  // не от раскрытия столбца, а от того, что шрифт успел прийти между замерами.
  await fontsReady(page);
  const before = { widths: await widths(), card: await cardTop() };

  // Раскрытие свёрнутого столбца раньше сужало все остальные (265 → 190 px), и текст
  // карточек в столбце, который человек читал, переносился по-другому.
  await column(page, 'done').getByRole('button').click();
  await expect(column(page, 'done').getByRole('article').first()).toBeVisible();

  expect((await widths()).slice(0, before.widths.length - 2)).toEqual(
    before.widths.slice(0, before.widths.length - 2),
  );
  expect(await cardTop()).toBe(before.card);

  await column(page, 'done').getByRole('button').click();
  await expect(column(page, 'done').getByRole('article')).toHaveCount(0);
  expect(await cardTop()).toBe(before.card);
});

test('свёрнутые столбцы живут в адресе: переживают перезагрузку и пересылку ссылки', async ({
  page,
  context,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');

  // Развернули закрытые, свернули открытые: состояние, которого нет в умолчании.
  await column(page, 'done').getByRole('button').click();
  await column(page, 'open').getByRole('button').click();

  await expect(page).toHaveURL(/collapsed=/);
  const address = page.url();

  await page.reload();
  await expect(column(page, 'done').getByRole('button')).toHaveAttribute('aria-expanded', 'true');
  await expect(column(page, 'open').getByRole('button')).toHaveAttribute('aria-expanded', 'false');

  const copy = await context.newPage();
  await silenceJournal(copy);
  await copy.goto(address);
  await expect(copy.locator('section[aria-label="done"] button')).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await expect(copy.locator('section[aria-label="open"] button')).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  await copy.close();
});

test('закрытые и отменённые свёрнуты, показывают число и раскрываются кликом', async ({ page }) => {
  // С архивом: отменённая `DEMO-7` без записей агента в архиве сразу (UI-97), и
  // раскрывать без него было бы нечего — а проверяется здесь раскрытие, не архив.
  await page.goto('/tasks?queue=DEMO&view=board&archive=shown');

  for (const status of ['done', 'cancelled']) {
    const toggle = column(page, status).getByRole('button');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(toggle).toContainText(/\d/);
    await expect(column(page, status).getByRole('article')).toHaveCount(0);

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(column(page, status).getByRole('article').first()).toBeVisible();
  }
});

test('столбец ожидания развёрнут, а знак в его заголовке тот же, что в строке списка', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');

  // Свёрнуто по умолчанию то, что **уже не в работе**. Ждущее из работы не вышло:
  // оно ждёт хода человека, и прятать от него единственный адресованный ему столбец
  // доска не вправе (`DEFAULT_COLLAPSED`).
  const toggle = column(page, 'waiting').getByRole('button');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(column(page, 'waiting').getByRole('article').first()).toBeVisible();

  // Один словарь знаков на список, карточку и доску (решение Д20): рисунок в заголовке
  // столбца и рисунок в строке таблицы совпадают до символа. Разойдясь, они дали бы
  // человеку два разных знака для одного и того же статуса.
  const head = await column(page, 'waiting')
    .locator('[data-mark="status"] svg')
    .first()
    .innerHTML();

  await page.goto('/tasks?queue=DEMO&status=waiting');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  const row = await page.locator('tbody [data-mark="status"] svg').first().innerHTML();

  expect(row).toBe(head);
});

test('карточка ведёт в задачу, а «назад» возвращает на доску', async ({ page }) => {
  await page.goto('/tasks?queue=DEMO&view=board');

  await column(page, 'in_progress')
    .getByRole('article')
    .filter({ hasText: 'DEMO-6' })
    .getByRole('link')
    .click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-6$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-6');

  await page.goBack();
  await expect(page).toHaveURL(/view=board/);
  await expect(column(page, 'in_progress')).toBeVisible();
});

test('фильтр по исполнителю действует на доске и переживает переключение в таблицу', async ({
  page,
  request,
}) => {
  const all = await tasksByStatus(request);
  const mine = await tasksByStatus(request, { assignee: 'demo_agent' });

  // Столбец, где у исполнителя есть задачи, но не все задачи статуса: только на таком
  // видно, что фильтр сузил выдачу, а не что он ничего не сделал. Какой это столбец,
  // решает состав демо, а не память теста, — ключи здесь не выписаны намеренно.
  const narrowed = [...mine].find(([status, keys]) => keys.length < (all.get(status) ?? []).length);
  expect(narrowed, 'в демо нет статуса, где у demo_agent часть задач').toBeDefined();
  const [status, keys] = narrowed as [string, string[]];

  // `collapsed=` — «ничего не свёрнуто»: столбцом сужения может оказаться и тот,
  // что свёрнут по умолчанию, и тогда карточек в нём не видно намеренно.
  await page.goto('/tasks?queue=DEMO&view=board&assignee=demo_agent&collapsed=');
  await expect(column(page, status)).toBeVisible();

  await expect(column(page, status).getByRole('article')).toHaveCount(keys.length);
  for (const key of keys) {
    await expect(column(page, status).getByRole('article').filter({ hasText: key })).toBeVisible();
  }

  await page.getByRole('link', { name: 'Таблица' }).click();

  await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText(
    'исполнитель demo_agent',
  );
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('rowheader', { name: keys[0] as string })).toBeVisible();
});

test('доска прокручивается внутри себя, а не уводит вбок страницу', async ({ page }) => {
  await silenceJournal(page);

  for (const width of [1440, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(column(page, 'waiting')).toBeVisible();
    await fontsReady(page);

    const measured = await page.evaluate(() => {
      const columns = document.querySelector('section[aria-label="backlog"]')?.parentElement;
      return {
        page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        board: (columns?.scrollWidth ?? 0) - (columns?.clientWidth ?? 0),
      };
    });

    // Столбцы не влезли — это нормально и решается прокруткой самой доски. Ненормально,
    // когда вбок уезжает страница: тогда вместе со столбцами уплывают панель и шапка,
    // а вернуть их можно только обратной прокруткой.
    expect(measured.board, `на ${width}px доске нечего прокручивать`).toBeGreaterThan(0);
    expect(measured.page, `на ${width}px страница уехала вбок`).toBe(0);
  }
});

test('доступность доски', async ({ page }) => {
  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, 'open')).toBeVisible();

  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

test('столбцы одной ширины при любом сочетании свёрнутых и развёрнутых', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, 'open')).toBeVisible();
  await fontsReady(page);

  const widths = () =>
    page.evaluate(() =>
      Array.from(document.querySelectorAll('section[aria-label]'))
        .filter((node) => node.getAttribute('aria-label') !== 'Отбор задач')
        .map((node) => Math.round(node.getBoundingClientRect().width * 10) / 10),
    );

  // Свёрнутый столбец раньше превращался в пилюлю по ширине содержимого, и ряд
  // читался как набор разных вещей (решение Д19). По умолчанию свёрнуты `done`
  // и `cancelled` — то есть замер идёт как раз на смешанном сочетании.
  const mixed = await widths();
  expect(mixed.length).toBeGreaterThanOrEqual(5);
  expect(Math.max(...mixed) - Math.min(...mixed)).toBeLessThanOrEqual(1);

  // Раскрытие столбца не меняет ширины соседей.
  await column(page, 'done').getByRole('button').click();
  await expect(column(page, 'done').getByRole('article').first()).toBeVisible();

  const opened = await widths();
  expect(Math.max(...opened) - Math.min(...opened)).toBeLessThanOrEqual(1);
  expect(opened).toEqual(mixed);
});

test('столбцы одной высоты при резко разной длине', async ({ page, request }) => {
  // Столбец и есть отбор по статусу: если длинный и короткий стоят рядом одной
  // высоты по числу карточек, короткий гаснет пустотой, неотличимой от соседа
  // (UI-67). Какой статус самый длинный и какой самый короткий, решает состав
  // демо, а не память теста, — числа здесь не выписаны намеренно.
  const all = await tasksByStatus(request);
  const byLength = [...all.entries()].sort(([, left], [, right]) => right.length - left.length);
  const longest = byLength[0];
  const shortest = byLength[byLength.length - 1];
  expect(longest, 'в демо нет ни одной задачи').toBeDefined();
  expect(shortest, 'в демо нет ни одного статуса').toBeDefined();
  const [longStatus, longKeys] = longest as [string, string[]];
  const [shortStatus, shortKeys] = shortest as [string, string[]];

  await silenceJournal(page);
  // `collapsed=` — все столбцы развёрнуты, включая обычно свёрнутые `done` и `cancelled`.
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, longStatus).getByRole('article')).toHaveCount(longKeys.length);
  await fontsReady(page);

  const heights = await page.evaluate(() =>
    Array.from(document.querySelectorAll('section[aria-label]'))
      .filter((node) => node.getAttribute('aria-label') !== 'Отбор задач')
      .map((node) => Math.round(node.getBoundingClientRect().height * 10) / 10),
  );

  expect(heights.length).toBeGreaterThanOrEqual(5);
  // Расхождение нулевое: столбец растянут по самому длинному (`items-stretch`
  // на ряду), а не по числу собственных карточек.
  expect(
    Math.max(...heights) - Math.min(...heights),
    JSON.stringify({
      longStatus,
      longKeys: longKeys.length,
      shortStatus,
      shortKeys: shortKeys.length,
      heights,
    }),
  ).toBe(0);
});

test('у карточек столбца подвал на одном месте, а название не длиннее двух строк', async ({
  page,
  request,
}) => {
  // Самый населённый столбец демо: подвал и переносы имеет смысл мерить там, где
  // карточек больше одной, а какой это столбец — знает бэкенд. Выписанный здесь
  // `open` однажды остался с одной карточкой (TRK-15), и замер сравнивать стало не с чем.
  const all = await tasksByStatus(request);
  const fullest = [...all].sort(([, left], [, right]) => right.length - left.length)[0];
  expect(fullest, 'в демо нет ни одной задачи').toBeDefined();
  const [status, keys] = fullest as [string, string[]];
  expect(keys.length).toBeGreaterThan(1);

  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const measured = await column(page, status).evaluate((node) => {
    const cards = Array.from(node.querySelectorAll('article'));
    return cards.map((card) => {
      const box = card.getBoundingClientRect();
      const foot = card.lastElementChild?.getBoundingClientRect();
      const title = card.querySelector('p');
      const lineHeight = Number.parseFloat(getComputedStyle(title as Element).lineHeight);
      return {
        fromBottom: Math.round((box.bottom - (foot?.bottom ?? box.bottom)) * 10) / 10,
        titleLines:
          Math.round(((title?.getBoundingClientRect().height ?? 0) / lineHeight) * 10) / 10,
      };
    });
  });

  expect(measured.length).toBeGreaterThan(1);
  const distances = measured.map((card) => card.fromBottom);
  expect(Math.max(...distances) - Math.min(...distances)).toBeLessThanOrEqual(1);
  for (const card of measured) expect(card.titleLines).toBeLessThanOrEqual(2);
});

/**
 * Высота окна, при которой самый длинный столбец демо заведомо не помещается в доску.
 *
 * Доска забирает остаток окна под заголовком с отбором, а карточка занимает около
 * сотни пикселей: на низком окне переполняется даже столбец из двух задач. Числом,
 * а не подбором под состав демо: длину столбцов решает бэкенд, и выписанное здесь
 * «две карточки» устарело бы вместе с ним.
 */
const SHORT_WINDOW = { width: 1024, height: 420 };

test('столбец прокручивается сам, а соседние столбцы и страница стоят на месте', async ({
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

  const measure = () =>
    page.evaluate((scrolled) => {
      const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
        (node) => node.getAttribute('aria-label') !== 'Отбор задач',
      );
      const mine = sections.find((node) => node.getAttribute('aria-label') === scrolled);
      return {
        // Страница целиком: доска обязана помещаться в окно, иначе прокрутки
        // окажется две и колесо будет двигать то одну, то другую.
        pageScroll: Math.round(window.scrollY),
        pageHeight: document.documentElement.scrollHeight,
        windowHeight: document.documentElement.clientHeight,
        column: {
          over: (mine?.scrollHeight ?? 0) - (mine?.clientHeight ?? 0),
          top: mine?.scrollTop ?? 0,
        },
        // Соседи: их место на экране и их собственная прокрутка.
        others: sections
          .filter((node) => node !== mine)
          .map((node) => ({
            x: Math.round(node.getBoundingClientRect().x),
            y: Math.round(node.getBoundingClientRect().y),
            top: node.scrollTop,
          })),
      };
    }, status);

  const before = await measure();
  expect(before.pageHeight, 'доска не поместилась в окно').toBe(before.windowHeight);
  expect(before.column.over, `столбцу ${status} нечего прокручивать`).toBeGreaterThan(0);

  // Докручиваем столбец до самого конца: до этого места человек доезжает колесом,
  // и именно здесь прокрутка цеплялась за страницу в WebKit (UI-68).
  await column(page, status).evaluate((node) => {
    node.scrollTop = node.scrollHeight;
  });
  await expect.poll(async () => (await measure()).column.top).toBeGreaterThan(0);

  const after = await measure();
  expect(after.pageScroll, 'страница поехала следом за столбцом').toBe(before.pageScroll);
  expect(after.pageHeight).toBe(before.pageHeight);
  expect(after.others, 'соседние столбцы сдвинулись').toEqual(before.others);
});

test('ниже точки остановки доска остаётся на прокрутке страницы', async ({ page, request }) => {
  const all = await tasksByStatus(request);
  const longest = [...all.entries()].sort(([, left], [, right]) => right.length - left.length)[0];
  const [status] = longest as [string, string[]];

  await silenceJournal(page);
  /*
   * Окно той же высоты, что у сценария выше, и другой ширины: решает именно ширина.
   * Уже `fold` (44rem) доске остаётся полторы карточки — заголовок с отбором занимает
   * там треть экрана, — и прокрутка страницы отдаёт столбцу весь экран. На телефоне
   * это дороже, чем видеть соседей (UI-68).
   */
  await page.setViewportSize({ width: 320, height: SHORT_WINDOW.height });
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const measured = await column(page, status).evaluate((node) => ({
    over: node.scrollHeight - node.clientHeight,
    pageOver: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));

  // Столбец здесь не прокручиваемая область вовсе: он ровно своей высоты, а в окно
  // не помещается страница целиком — как это и было до UI-68.
  expect(measured.over).toBe(0);
  expect(measured.pageOver).toBeGreaterThan(0);
  // И это не повод странице поехать вбок.
  expect(measured.sideways).toBe(0);
});

/**
 * Самый длинный столбец демо: его решает состав демо, а не память сценария. Прокрутка
 * меряется там, где ей есть куда ехать, и выписанный здесь статус устарел бы вместе
 * с бэкендом (так уже было с `open` — TRK-15).
 */
async function longestColumn(request: APIRequestContext): Promise<string> {
  const all = await tasksByStatus(request);
  const longest = [...all.entries()].sort(([, left], [, right]) => right.length - left.length)[0];
  expect(longest, 'в демо нет ни одной задачи').toBeDefined();
  return (longest as [string, string[]])[0];
}

/** Заголовки всех шести столбцов и сами столбцы, снятые одним кадром. */
function heads(page: Page) {
  return page.evaluate(() => {
    const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
      (node) => node.getAttribute('aria-label') !== 'Отбор задач',
    );
    const rect = (node: Element) => {
      const box = node.getBoundingClientRect();
      return {
        top: Math.round(box.top),
        bottom: Math.round(box.bottom),
        left: Math.round(box.left),
        right: Math.round(box.right),
      };
    };
    return {
      window: { width: window.innerWidth, height: window.innerHeight },
      columns: sections.map((node) => ({
        status: node.getAttribute('aria-label') as string,
        head: rect(node.querySelector('h2') as Element),
        column: rect(node),
        scrolled: Math.round(node.scrollTop),
        sideways: node.scrollWidth - node.clientWidth,
      })),
    };
  });
}

/** Докручивает столбец до конца прочитанного — тем же движением, что и человек колесом. */
async function scrollColumn(page: Page, status: string): Promise<void> {
  await column(page, status).evaluate((node) => {
    node.scrollTop = node.scrollHeight;
  });
  await expect
    .poll(() => column(page, status).evaluate((node) => Math.round(node.scrollTop)), {
      message: `столбец ${status} не прокрутился`,
    })
    .toBeGreaterThan(0);
}

/**
 * Отношение контраста по WCAG для двух цветов вычисленного стиля — то же число,
 * которое считает `axe`. Токены сверяет `theme.test.ts`, а здесь меряется то, что
 * действительно нарисовано: прилипшая шапка обязана иметь свой фон, и контраст к нему
 * считается по нему, а не по поверхности под ней.
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

test('на любой глубине прокрутки видно, какой столбец перед глазами', async ({ page, request }) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  await scrollColumn(page, status);

  const measured = await heads(page);
  expect(measured.columns).toHaveLength(contractStatuses().length);

  const report = JSON.stringify(measured);
  for (const seen of measured.columns) {
    // По вертикали заголовок обязан быть на экране целиком: за этим задача и делалась.
    expect(seen.head.top, report).toBeGreaterThanOrEqual(0);
    expect(seen.head.bottom, report).toBeLessThanOrEqual(measured.window.height);
    /*
     * И стоять он обязан у верхней рамки **своего** столбца, а не в двенадцати
     * пикселях под ней: поле столбца лежит внутри его области прокрутки, и щель
     * над прилипшим заголовком была бы окном, сквозь которое едут карточки.
     * Единица — рамка столбца.
     */
    expect(seen.head.top - seen.column.top, report).toBeLessThanOrEqual(2);
    expect(seen.head.top - seen.column.top, report).toBeGreaterThanOrEqual(0);
    // Отрицательные поля заголовка не имеют права развести столбец вбок.
    expect(seen.sideways, report).toBe(0);
  }

  const scrolled = measured.columns.find((seen) => seen.status === status);
  expect(scrolled?.scrolled, `столбцу ${status} нечего прокручивать`).toBeGreaterThan(0);
});

test('прилипшая шапка не просвечивает карточками и читается в своей теме', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  await scrollColumn(page, status);

  const measured = await column(page, status).evaluate((node) => {
    const head = node.querySelector('h2') as HTMLElement;
    const box = head.getBoundingClientRect();
    const cards = Array.from(node.querySelectorAll('article'));
    /*
     * Кто нарисован в полосе шапки: она обязана перекрывать карточку целиком, а не
     * пустить её поверх себя. Точек много и по всей ширине: карточка позиционирована,
     * а её название и исполнитель подняты ещё и `z-1` над растяжкой ссылки — одна
     * точка посередине прошла бы мимо них.
     */
    const points = [0.1, 0.3, 0.5, 0.7, 0.9].flatMap((across) =>
      [0.3, 0.7].map((down) => ({
        x: box.left + box.width * across,
        y: box.top + box.height * down,
      })),
    );
    return {
      background: getComputedStyle(head).backgroundColor,
      column: getComputedStyle(node).backgroundColor,
      // Все цвета, которыми в шапке что-то написано: знак статуса, название статуса
      // и счётчик набраны разными уровнями текста, и контраст меряется у каждого.
      colors: [
        ...new Set(
          [head, ...Array.from(head.querySelectorAll('button, span'))].map(
            (text) => getComputedStyle(text).color,
          ),
        ),
      ],
      onTop: points.filter((point) => head.contains(document.elementFromPoint(point.x, point.y)))
        .length,
      points: points.length,
      // И карточка в этот момент действительно проезжает под шапкой.
      under: cards.filter((card) => {
        const rect = card.getBoundingClientRect();
        return rect.top < box.bottom && rect.bottom > box.top;
      }).length,
    };
  });

  await test.info().attach(`шапка на проезжающей карточке (${status})`, {
    body: await column(page, status).screenshot(),
    contentType: 'image/png',
  });

  const report = JSON.stringify(measured);
  expect(measured.under, `под шапкой ${status} нет ни одной карточки: ${report}`).toBeGreaterThan(
    0,
  );
  expect(measured.onTop, report).toBe(measured.points);
  // Свой фон, и он непрозрачный: `rgba(…, 0)` пустил бы карточки сквозь шапку.
  expect(measured.background, report).not.toMatch(/, ?0\)$/);
  expect(measured.background, report).toBe(measured.column);
  // Контраст считается к фону самой шапки — той поверхности, на которой лежит текст.
  const ratios = measured.colors.map((color) => contrast(color, measured.background));
  expect(Math.min(...ratios), `${report} ${JSON.stringify(ratios)}`).toBeGreaterThanOrEqual(4.5);

  // `axe` смотрит на доску в том же прокрученном состоянии: контраст прилипшей шапки
  // он считает сам и по нарисованному.
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

test('кнопка прилипшей шапки работает с глубины прокрутки: мышью и клавиатурой', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  const cards = column(page, status).getByRole('article');
  const toggle = column(page, status).getByRole('button');
  await expect(cards.first()).toBeVisible();
  await fontsReady(page);

  // Мышью: нажатие идёт по тому месту, где кнопка нарисована сейчас, — то есть
  // по прилипшей шапке, а не по её месту в потоке.
  await scrollColumn(page, status);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(cards).toHaveCount(0);
  await toggle.click();
  await expect(cards.first()).toBeVisible();

  // Клавиатурой: до кнопки доходят табуляцией, ею же столбец и прокручивают —
  // своего `tabIndex` у прокручиваемого столбца нет (UI-68).
  // Фокус после нажатия мышью остался на кнопке, а мышиный фокус обводки не рисует:
  // путь клавиатурой начинается с начала страницы, как у человека.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  const focused = () =>
    page.evaluate(() => {
      const active = document.activeElement;
      return {
        tag: active?.tagName ?? '',
        column: active?.closest('section[aria-label]')?.getAttribute('aria-label') ?? '',
        ring: active === null ? false : active.matches(':focus-visible'),
        outline: active === null ? '0px' : getComputedStyle(active).outlineWidth,
      };
    });

  let stops = 0;
  let at = await focused();
  while (stops < 100 && !(at.tag === 'BUTTON' && at.column === status)) {
    await page.keyboard.press('Tab');
    stops += 1;
    at = await focused();
  }
  expect(at, `остановок Tab до кнопки столбца ${status}: ${stops}`).toMatchObject({
    tag: 'BUTTON',
    column: status,
  });
  // Фокус видно: обводка рисуется `:focus-visible` (`shared/styles/reset.css`).
  expect(at.ring, JSON.stringify(at)).toBe(true);
  expect(Number.parseFloat(at.outline), JSON.stringify(at)).toBeGreaterThan(0);

  // Столбец прокручивается с той же кнопки: `End` и `PageDown` двигают ближайшую
  // прокручиваемую область, а это он сам.
  await page.keyboard.press('End');
  await page.keyboard.press('PageDown');
  await page.keyboard.press('PageDown');
  await expect
    .poll(() => column(page, status).evaluate((node) => Math.round(node.scrollTop)))
    .toBeGreaterThan(0);

  // С этой глубины шапка по-прежнему у верхней рамки столбца, а фокус — на ней.
  const deep = await heads(page);
  const mine = deep.columns.find((seen) => seen.status === status);
  expect(mine?.head.top ?? -1, JSON.stringify(deep)).toBeGreaterThanOrEqual(
    mine?.column.top ?? Number.NaN,
  );
  expect((mine?.head.top ?? 0) - (mine?.column.top ?? 0), JSON.stringify(deep)).toBeLessThanOrEqual(
    2,
  );

  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(cards).toHaveCount(0);
  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(cards.first()).toBeVisible();
});

test('при прокрутке ряда вбок заголовок едет вместе со своим столбцом', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  await scrollColumn(page, status);

  // Ряд уезжает вбок до упора: шесть столбцов на этой ширине не помещаются.
  const shifted = await page.evaluate(() => {
    const row = document.querySelector('section[aria-label="backlog"]')
      ?.parentElement as HTMLElement;
    row.scrollLeft = row.scrollWidth;
    return { over: row.scrollWidth - row.clientWidth, left: Math.round(row.scrollLeft) };
  });
  expect(shifted.over, 'ряду нечего прокручивать вбок').toBeGreaterThan(0);
  expect(shifted.left, 'ряд не уехал вбок').toBeGreaterThan(0);

  const measured = await heads(page);
  const report = JSON.stringify({ shifted, ...measured });
  for (const seen of measured.columns) {
    // Заголовок принадлежит своему столбцу и стоит ровно над ним — не над соседним
    // и не отдельной полосой поверх ряда.
    expect(Math.abs(seen.head.left - seen.column.left), report).toBeLessThanOrEqual(2);
    expect(Math.abs(seen.column.right - seen.head.right), report).toBeLessThanOrEqual(2);
    expect(seen.head.top - seen.column.top, report).toBeLessThanOrEqual(2);
  }
});

/**
 * Окно ниже точки остановки, в котором странице есть что прокручивать: столбцы демо
 * коротки, и на 420 px доска помещается целиком.
 */
const NARROW_WINDOW = { width: 320, height: 320 };

/**
 * Ждёт, пока каждый столбец доски получит ответ на свой первый запрос.
 *
 * Высоту ряда задаёт самый длинный столбец (`items-stretch`), а с ней и то, куда
 * странице есть ехать. Столбцы читают каждый своим запросом, и первая карточка одного
 * из них не значит, что прочитана доска: под нагрузкой ответы расходятся на сотню
 * миллисекунд, и `open` бывает нарисован, пока длинные столбцы ещё в пути (UI-113).
 * Число в заголовке столбца приходит вместе с его ответом, а до него там «0 из ?», —
 * поэтому ждётся число в конце заголовка, у каждого столбца.
 */
async function boardRead(page: Page): Promise<void> {
  for (const status of contractStatuses()) {
    await expect(
      column(page, status).getByRole('button'),
      `столбец ${status} не дождался ответа`,
    ).toHaveText(/\d$/);
  }
}

/**
 * Уводит страницу вглубь доски — туда, где до UI-94 заголовки уезжали за верх окна
 * вместе со своими столбцами. Глубина — сколько даёт страница, но не больше, чем
 * заголовку есть куда ехать внутри своего столбца. Отдаёт эту глубину.
 *
 * Сколько даёт страница, знает только прочитанная доска (`boardRead`). Недочитанная
 * отдавала отрицательную глубину: страница уезжала до своего тогдашнего дна, не доходя
 * до верха доски, прокрутка совпадала с заказанной, а заголовки оставались посреди окна
 * на верху своих столбцов — и падение читалось как «прижим не сработал» (UI-113).
 * Поэтому глубина здесь же и проверяется.
 */
async function sinkBoard(page: Page): Promise<number> {
  await boardRead(page);
  const room = await page.evaluate(() => {
    const first = document.querySelector('section[aria-label="backlog"]') as HTMLElement;
    const board = (first.parentElement as HTMLElement).parentElement as HTMLElement;
    const top = Math.round(board.getBoundingClientRect().top + window.scrollY);
    const head = (first.querySelector('h2') as HTMLElement).getBoundingClientRect().height;
    const max = document.documentElement.scrollHeight - document.documentElement.clientHeight;
    const deeper = Math.min(max - top, Math.round(first.getBoundingClientRect().height - 2 * head));
    window.scrollTo(0, top + deeper);
    return { asked: top + deeper, deeper, top, max };
  });
  // Меньше высоты заголовка — не глубина: заголовок уехал бы за край наполовину,
  // и сценарий этого не отличил бы.
  expect(
    room.deeper,
    `странице некуда уехать вглубь доски: ${JSON.stringify(room)}`,
  ).toBeGreaterThanOrEqual(40);
  await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(room.asked);
  return room.deeper;
}

/** Ряд столбцов: сколько ему ехать вбок, где он сейчас и где его края. */
function row(page: Page) {
  return page.evaluate(() => {
    const node = document.querySelector('section[aria-label="backlog"]')
      ?.parentElement as HTMLElement;
    const box = node.getBoundingClientRect();
    return {
      over: node.scrollWidth - node.clientWidth,
      overY: node.scrollHeight - node.clientHeight,
      left: Math.round(node.scrollLeft),
      edges: { left: Math.round(box.left), right: Math.round(box.right) },
      // Страница целиком: вбок она не едет ни при какой прокрутке ряда.
      sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      pageY: Math.round(window.scrollY),
    };
  });
}

/**
 * Ждёт, пока все шесть заголовков встанут у верха окна. Сдвиг прижима браузер
 * пересчитывает к кадру после прокрутки, а не в том же вызове, — снятое сразу число
 * ловило бы заголовок ещё на старом месте.
 */
async function pinned(page: Page) {
  await expect
    .poll(
      async () =>
        (await heads(page)).columns
          .filter((seen) => seen.head.top < 0 || seen.head.top > 2)
          .map((seen) => `${seen.status}: ${seen.head.top}`),
      { message: 'заголовки не встали у верха окна' },
    )
    .toEqual([]);
  return heads(page);
}

test('ниже точки остановки заголовок прижат к верху окна на любой глубине прокрутки страницы', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  /*
   * Ниже `fold` своей прокрутки у столбца нет — едет страница, — а `sticky` там липнуть
   * не к чему: порт прокрутки заголовка не окно, а ряд столбцов (`overflow-x-auto`
   * делает его прокручиваемым по обеим осям), и по вертикали ряд не едет. До UI-94
   * заголовок поэтому уезжал вместе со столбцом. Держит его у верха окна прижим по шкале
   * доски (`pin-top`), и сценарий стережёт именно его: на глубине видно, какой столбец
   * перед глазами.
   */
  await page.setViewportSize(NARROW_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const deeper = await sinkBoard(page);

  const how = await column(page, status).evaluate((node) => {
    const style = getComputedStyle(node.querySelector('h2') as Element);
    return { position: style.position, animation: style.animationName };
  });
  // Держит прижим, а не липкость: липкое здесь стояло бы на месте вместе с рядом.
  expect(how.position, JSON.stringify(how)).not.toBe('sticky');
  expect(how.animation, JSON.stringify(how)).toBe('pin-top');

  const measured = await pinned(page);
  const lane = await row(page);
  const report = JSON.stringify({ deeper, lane, ...measured });
  expect(measured.columns).toHaveLength(contractStatuses().length);
  for (const seen of measured.columns) {
    // Столбец ушёл за верх окна, а его заголовок — нет: у верха окна, в пикселе рамки.
    expect(seen.column.top, report).toBeLessThan(0);
    expect(seen.head.top, report).toBeGreaterThanOrEqual(0);
    expect(seen.head.top, report).toBeLessThanOrEqual(2);
    // Над своим столбцом, а не над соседним, и не ниже его конца.
    expect(Math.abs(seen.head.left - seen.column.left), report).toBeLessThanOrEqual(2);
    expect(Math.abs(seen.column.right - seen.head.right), report).toBeLessThanOrEqual(2);
    expect(seen.head.bottom, report).toBeLessThanOrEqual(seen.column.bottom);
    // Столбец при этом прокручиваемой областью не стал: едет страница (UI-68).
    expect(seen.scrolled, report).toBe(0);
  }
  // Ряд по вертикали так и не едет: прижатый заголовок второй прокрутки не заводит.
  expect(lane.overY, report).toBe(0);
  expect(lane.sideways, report).toBe(0);

  // Прижатая шапка — та же кнопка: нажатие идёт туда, где она нарисована сейчас,
  // а не туда, где её место в потоке, — и клавиатура доходит до неё же.
  const toggle = column(page, 'backlog').getByRole('button');
  const box = await toggle.boundingBox();
  expect(box?.y ?? -1, report).toBeGreaterThanOrEqual(0);
  await page.mouse.click(
    (box?.x ?? 0) + (box?.width ?? 0) / 2,
    (box?.y ?? 0) + (box?.height ?? 0) / 2,
  );
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
});

test('ниже точки остановки все шесть столбцов достижимы вбок тем же жестом, а заголовок едет над своим', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.setViewportSize(NARROW_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  await sinkBoard(page);
  await pinned(page);
  const before = await row(page);
  expect(before.over, 'ряду нечего прокручивать вбок').toBeGreaterThan(0);
  expect(before.left).toBe(0);

  /*
   * Жест тот же, что до прижима: прокрутка вбок над рядом — колесо вбок, то есть то же,
   * что смахивание двумя пальцами по тачпаду. Шагами, как рука, и над серединой окна:
   * верх ряда давно за верхом окна, а под курсором обязан оказаться сам ряд.
   */
  await page.mouse.move(NARROW_WINDOW.width / 2, NARROW_WINDOW.height / 2);
  for (let moved = 0; moved <= before.over; moved += 120) {
    await page.mouse.wheel(120, 0);
  }
  await expect
    .poll(async () => (await row(page)).left, { message: 'ряд не доехал вбок до упора' })
    .toBe(before.over);

  const after = await row(page);
  const measured = await pinned(page);
  const report = JSON.stringify({ before, after, ...measured });
  // Последний столбец встал целиком у правого края ряда: доехать можно до каждого.
  const last = measured.columns.at(-1);
  expect(last?.status, report).toBe(contractStatuses().at(-1));
  expect(Math.abs((last?.column.right ?? 0) - after.edges.right), report).toBeLessThanOrEqual(1);
  expect(last?.column.left ?? -1, report).toBeGreaterThanOrEqual(after.edges.left);
  for (const seen of measured.columns) {
    // Заголовок уехал вбок вместе со своим столбцом и остался у верха окна.
    expect(Math.abs(seen.head.left - seen.column.left), report).toBeLessThanOrEqual(2);
    expect(Math.abs(seen.column.right - seen.head.right), report).toBeLessThanOrEqual(2);
  }
  // Вбок уехал ряд, а не страница, и вниз-вверх страница от этого не сдвинулась.
  expect(after.sideways, report).toBe(0);
  expect(after.pageY, report).toBe(before.pageY);
});

test('страница не едет вбок ни на узкой доске, ни на точке остановки', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);
  await silenceJournal(page);

  // 320 — ниже `fold`, где заголовки прижаты к окну; 704 — сама точка остановки, где
  // столбец уже прокручивается сам. Вбок страница не едет ни в покое, ни на глубине,
  // ни после прокрутки ряда до упора — это ловили дважды (UI-40, UI-48).
  for (const width of [320, 704]) {
    await page.setViewportSize({ width, height: NARROW_WINDOW.height });
    await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
    await expect(column(page, status).getByRole('article').first()).toBeVisible();
    await fontsReady(page);

    const seen: Record<string, number> = { rest: (await row(page)).sideways };

    await page.evaluate((scrolled) => {
      const node = document.querySelector(`section[aria-label="${scrolled}"]`) as HTMLElement;
      if (getComputedStyle(node).overflowY === 'auto') node.scrollTop = node.scrollHeight;
      else window.scrollTo(0, document.documentElement.scrollHeight);
    }, status);
    seen.deep = (await row(page)).sideways;

    await page.evaluate(() => {
      const node = document.querySelector('section[aria-label="backlog"]')
        ?.parentElement as HTMLElement;
      node.scrollLeft = node.scrollWidth;
    });
    const lane = await row(page);
    expect(lane.left, `на ${width}px ряд не уехал вбок`).toBeGreaterThan(0);
    seen.side = lane.sideways;

    expect(seen, `на ${width}px страница уехала вбок`).toEqual({ rest: 0, deep: 0, side: 0 });
  }
});

/**
 * Запас прокрутки вбок у каждого столбца и у ряда, снятый одним кадром.
 *
 * Считается дважды и по-разному, потому что числа значат разное. `scrollWidth -
 * clientWidth` — целые: доля пикселя в них пропадает, а полосу браузер по доле рисует.
 * `scrollLeft`, доведённый до упора, — та самая величина запаса, дробная: её браузер
 * и спрашивает, решая, нужна ли полоса. Первое сравнимо с числами задачи, второе строже.
 */
function lanes(page: Page) {
  return page.evaluate(() => {
    const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
      (node) => node.getAttribute('aria-label') !== 'Отбор задач',
    ) as HTMLElement[];
    const room = (node: HTMLElement) => {
      const was = node.scrollLeft;
      node.scrollLeft = 1e6;
      const reached = node.scrollLeft;
      node.scrollLeft = was;
      return Math.round(reached * 100) / 100;
    };
    const lane = sections[0]?.parentElement as HTMLElement;
    return {
      columns: sections.map((node) => ({
        status: node.getAttribute('aria-label') as string,
        // Так эту величину называет задача: целыми, как её отдаёт браузер.
        over: node.scrollWidth - node.clientWidth,
        room: room(node),
        overflowX: getComputedStyle(node).overflowX,
        clientWidth: node.clientWidth,
        // Боковые поля самого столбца — того узла, который прокручивается (UI-117).
        sides: [getComputedStyle(node).paddingLeft, getComputedStyle(node).paddingRight],
      })),
      row: { over: lane.scrollWidth - lane.clientWidth, room: room(lane) },
    };
  });
}

test('столбец доски не прокручивается вбок ни на одной ширине, а ряд — прокручивается', async ({
  page,
}) => {
  await silenceJournal(page);

  /*
   * 640 — ниже точки остановки, где своей прокрутки у столбца нет вовсе; 704 — сама
   * точка, с которой она включается; 1024 — шире неё. Ширина окна столбцу ширины не
   * меняет (она задана `--ui-board-column`), но меняет ветку: с `fold` у столбца
   * `overflow-y: auto`, а по правилу CSS вторая ось рядом с ним вычисляется в `auto`
   * — то есть любое переполнение вправо становится полосой прокрутки (UI-115).
   */
  for (const width of [640, 704, 1024]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
    await boardRead(page);
    await fontsReady(page);

    const measured = await lanes(page);
    const report = `на ${width}px ${JSON.stringify(measured)}`;
    expect(measured.columns).toHaveLength(contractStatuses().length);

    for (const seen of measured.columns) {
      // Столбцу вбок ехать некуда: карточки укладываются в его ширину.
      expect(seen.over, report).toBeLessThanOrEqual(0);
      expect(seen.room, report).toBe(0);
      /*
       * И не появится от того, чего этот прогон не видит. Область прокрутки считается
       * не по содержимому: к объединению padding-бокса с рамками потомков прибавляется
       * своё боковое поле контейнера (`css-overflow-3`). Заголовок столбца намеренно
       * растянут `-mx-3` на весь padding-бокс, то есть достаёт до края объединения, —
       * значит любое боковое поле на самом прокручиваемом узле становится запасом
       * прокрутки вбок. Safari 18.6 так и считает (у владельца было 246/258 у всех
       * шести столбцов), Chromium и WebKit 26.5 — нет, и потому этот прогон поймать
       * дефект замером не может: он ловит его условие (UI-117).
       */
      expect(seen.sides, report).toEqual(['0px', '0px']);
    }

    // А ряду — есть: шесть столбцов не влезают ни в одну из этих ширин, и это
    // та самая прокрутка вбок, которую завели UI-68 и UI-94.
    expect(measured.row.over, report).toBeGreaterThan(0);
    expect(measured.row.room, report).toBeGreaterThan(0);
  }
});

test('прижатая шапка не просвечивает карточками, и `axe` на узкой доске чист', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(NARROW_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  // Самый длинный столбец — в окно, тем же рядом вбок: под его шапкой есть кому ехать.
  await column(page, status).evaluate((node) => {
    const lane = node.parentElement as HTMLElement;
    lane.scrollLeft += node.getBoundingClientRect().left - lane.getBoundingClientRect().left;
  });
  await sinkBoard(page);
  await pinned(page);

  const measured = await column(page, status).evaluate((node) => {
    const head = node.querySelector('h2') as HTMLElement;
    const box = head.getBoundingClientRect();
    // Точки по всей ширине шапки: название и исполнитель карточки подняты `z-1` над
    // растяжкой ссылки, и одна точка посередине прошла бы мимо них.
    const points = [0.1, 0.3, 0.5, 0.7, 0.9].flatMap((across) =>
      [0.3, 0.7].map((down) => ({
        x: box.left + box.width * across,
        y: box.top + box.height * down,
      })),
    );
    return {
      background: getComputedStyle(head).backgroundColor,
      column: getComputedStyle(node).backgroundColor,
      onTop: points.filter((point) => head.contains(document.elementFromPoint(point.x, point.y)))
        .length,
      points: points.length,
      under: Array.from(node.querySelectorAll('article')).filter((card) => {
        const rect = card.getBoundingClientRect();
        return rect.top < box.bottom && rect.bottom > box.top;
      }).length,
    };
  });

  await test.info().attach(`прижатая шапка на проезжающей карточке (${status})`, {
    body: await page.screenshot(),
    contentType: 'image/png',
  });

  const report = JSON.stringify(measured);
  expect(measured.under, `под шапкой ${status} нет ни одной карточки: ${report}`).toBeGreaterThan(
    0,
  );
  expect(measured.onTop, report).toBe(measured.points);
  expect(measured.background, report).not.toMatch(/, ?0\)$/);
  expect(measured.background, report).toBe(measured.column);

  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

/**
 * Столбцы одним кадром глазами знака края: есть ли что прокручивать, стоит ли знак
 * и где именно он стоит. `over` — то же самое условие, по которому знак обязан быть
 * нарисован, снятое у браузера, а не у скрипта страницы.
 */
function edges(page: Page) {
  return page.evaluate(() => {
    const sections = Array.from(document.querySelectorAll('section[aria-label]')).filter(
      (node) => node.getAttribute('aria-label') !== 'Отбор задач',
    );
    return sections.map((node) => {
      const sign = node.querySelector('[data-edge]');
      const box = node.getBoundingClientRect();
      const mark = sign?.getBoundingClientRect() ?? null;
      return {
        status: node.getAttribute('aria-label') as string,
        // Есть ли что прокручивать — и сколько.
        over: node.scrollHeight - node.clientHeight,
        room: node.clientHeight,
        content: node.scrollHeight,
        scrolled: Math.round(node.scrollTop),
        cards: node.querySelectorAll('article').length,
        sign: sign !== null,
        // Знак стоит у нижней рамки столбца: единица — сама рамка.
        gap: mark === null ? null : Math.round(box.bottom - mark.bottom),
        height: mark === null ? null : Math.round(mark.height),
        width: mark === null ? null : Math.round(box.width - mark.width),
      };
    });
  });
}

/**
 * Ждёт, пока знак сойдётся с прокруткой во всех столбцах, и отдаёт снятый после этого
 * кадр. Ждать приходится: знак ставит наблюдатель пересечения, и его слово приходит
 * через кадр после того, как содержимое или окно изменились.
 */
async function settledEdges(page: Page, message: string) {
  await expect
    .poll(
      async () =>
        (await edges(page))
          .filter((seen) => seen.sign !== seen.over > 0)
          .map((seen) => `${seen.status}: знак ${String(seen.sign)} при запасе ${seen.over}`),
      { message },
    )
    .toEqual([]);
  return edges(page);
}

/** Окно, в котором столбцы демо помещаются целиком: прокручивать в них нечего. */
const TALL_WINDOW = { width: 1024, height: 1400 };

test('знак края есть у переполненного столбца и его нет там, где прокручивать нечего', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const low = await settledEdges(page, 'на низком окне знак разошёлся с прокруткой');
  await test.info().attach('знак края на низком окне', {
    body: JSON.stringify(low, null, 2),
    contentType: 'application/json',
  });
  const crowded = low.filter((seen) => seen.over > 0);
  const report = JSON.stringify(low);
  expect(
    crowded.length,
    `на окне ${SHORT_WINDOW.height} никому нечего прокручивать: ${report}`,
  ).toBeGreaterThan(0);

  for (const seen of crowded) {
    // Знак прижат к нижней рамке своего столбца и достаёт до боковых: между ним
    // и рамкой не должно оставаться щели, сквозь которую видно уезжающую карточку.
    expect(seen.gap, report).toBeLessThanOrEqual(2);
    expect(seen.gap, report).toBeGreaterThanOrEqual(0);
    expect(seen.width, report).toBeLessThanOrEqual(2);
    // Высота знака — нижнее поле столбца: место, где содержимое бывает только
    // на прокрутке.
    expect(seen.height, report).toBe(12);
  }

  /*
   * Высокое окно: столбцы демо помещаются целиком, и знака нет ни у одного — то же
   * обещание, которое чинили рамке таблицы (UI-91). Проверяется именно столбец
   * с карточками, а не пустой: пустому и обещать нечего.
   */
  await page.setViewportSize(TALL_WINDOW);
  const tall = await settledEdges(page, 'на высоком окне знак разошёлся с прокруткой');
  await test.info().attach('знак края на высоком окне', {
    body: JSON.stringify(tall, null, 2),
    contentType: 'application/json',
  });
  const roomy = tall.filter((seen) => seen.over === 0 && seen.cards > 0);
  expect(
    roomy.length,
    `на окне ${TALL_WINDOW.height} ни один столбец не поместился целиком: ${JSON.stringify(tall)}`,
  ).toBeGreaterThan(0);
  for (const seen of roomy) expect(seen.sign, JSON.stringify(seen)).toBe(false);

  /*
   * И то же самое на обычном рабочем окне — том, на котором мерили пробу прокрутки
   * (UI-68#10): видимая высота столбца там 674 px, и знак её не трогает.
   */
  await page.setViewportSize({ width: 1440, height: 900 });
  const usual = await settledEdges(page, 'на рабочем окне знак разошёлся с прокруткой');
  await test.info().attach('видимая высота столбца и знак на 1440×900', {
    body: JSON.stringify(usual, null, 2),
    contentType: 'application/json',
  });
});

test('докрутили до конца — знак снят: столбец кончился, и это видно', async ({ page, request }) => {
  const longest = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, longest).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const start = await settledEdges(page, 'знак разошёлся с прокруткой до первого жеста');
  const crowded = start
    .filter((seen) => seen.over > 0)
    .sort((left, right) => left.content - right.content);
  const shortest = crowded[0];
  expect(shortest, `нечего прокручивать: ${JSON.stringify(start)}`).toBeDefined();
  const status = (shortest as { status: string }).status;

  /*
   * Докручиваем, пока столбец не кончится. Не одним жестом: прокрутка до конца зовёт
   * следующую страницу (UI-70), и конец наступает тогда, когда приводить больше нечего.
   * Знак при этом гаснет сам — по тому же наблюдателю, что и зажёгся.
   */
  await expect
    .poll(
      async () => {
        await column(page, status).evaluate((node) => {
          node.scrollTop = node.scrollHeight;
        });
        return (await edges(page)).find((seen) => seen.status === status)?.sign ?? true;
      },
      { message: `столбец ${status} не кончается`, timeout: 20_000 },
    )
    .toBe(false);

  const ended = (await edges(page)).find((seen) => seen.status === status);
  const at = JSON.stringify(ended);
  // Столбец действительно докручен до дна, а не остановился где-то посередине.
  expect((ended?.scrolled ?? 0) + (ended?.room ?? 0), at).toBeGreaterThanOrEqual(
    (ended?.content ?? 0) - 1,
  );

  // Назад к началу — знак вернулся: он говорит о содержимом за краем, а не о том,
  // трогали ли столбец.
  await column(page, status).evaluate((node) => {
    node.scrollTop = 0;
  });
  await expect
    .poll(async () => (await edges(page)).find((seen) => seen.status === status)?.sign, {
      message: `столбец ${status} вернулся в начало, а знак не вернулся`,
    })
    .toBe(true);

  /*
   * И высоты знак не занимает: со знаком и без него у столбца та же видимая высота
   * и то же содержимое. Замер снят на одном и том же столбце в двух состояниях —
   * ничего, кроме знака, между ними не менялось.
   */
  const back = (await edges(page)).find((seen) => seen.status === status);
  const both = JSON.stringify({ ended, back });
  await test.info().attach(`столбец ${status} со знаком и без него`, {
    body: JSON.stringify({ ended, back }, null, 2),
    contentType: 'application/json',
  });
  expect(back?.room, both).toBe(ended?.room);
  expect(back?.content, both).toBe(ended?.content);
});

test('знак края читается в своей теме и не съедает нажатие по карточке под ним', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);
  await settledEdges(page, 'знак разошёлся с прокруткой');

  const measured = await column(page, status).evaluate((node) => {
    const sign = node.querySelector('[data-edge]') as HTMLElement;
    const box = sign.getBoundingClientRect();
    const cards = Array.from(node.querySelectorAll('article'));
    const points = [0.1, 0.3, 0.5, 0.7, 0.9].map((across) => ({
      x: box.left + box.width * across,
      y: box.top + box.height * 0.5,
    }));
    return {
      background: getComputedStyle(sign).backgroundColor,
      column: getComputedStyle(node).backgroundColor,
      card: getComputedStyle(cards[0] as Element).backgroundColor,
      shadow: getComputedStyle(sign).boxShadow,
      position: getComputedStyle(sign).position,
      raised: Number(getComputedStyle(sign).zIndex),
      /*
       * Выше ли знак всего, что поднимает над собой карточка: она позиционирована ради
       * растянутой ссылки, а название и исполнитель стоят в ней `relative z-1` — при
       * равном `z-index` победил бы тот, кто ниже в разметке, то есть карточка (UI-69).
       */
      inCard: Math.max(
        ...Array.from((cards[0] as Element).querySelectorAll('*')).map(
          (inner) => Number(getComputedStyle(inner).zIndex) || 0,
        ),
      ),
      // Под знаком в этот момент действительно проезжает карточка.
      under: cards.filter((card) => {
        const rect = card.getBoundingClientRect();
        return rect.top < box.bottom && rect.bottom > box.top;
      }).length,
      // Нажатие сквозь знак проходит: под ним лежат последние пиксели карточки-ссылки.
      through: points.filter((point) => {
        const hit = document.elementFromPoint(point.x, point.y);
        return hit !== null && hit.closest('article') !== null;
      }).length,
      points: points.length,
    };
  });

  await test.info().attach(`знак края у столбца ${status}`, {
    body: await column(page, status).screenshot(),
    contentType: 'image/png',
  });

  const report = JSON.stringify(measured);
  expect(measured.under, `под знаком ${status} нет ни одной карточки: ${report}`).toBeGreaterThan(
    0,
  );
  expect(measured.position, report).toBe('sticky');
  expect(measured.raised, report).toBeGreaterThan(measured.inCard);
  expect(measured.through, report).toBe(measured.points);
  // Заливка своя и непрозрачная: сквозь `rgba(…, 0)` карточка просвечивала бы, и знак
  // читался бы «кончилось» ровно там, где не кончилось.
  expect(measured.background, report).not.toMatch(/, ?0\)$/);
  expect(measured.background, report).toBe(measured.column);

  /*
   * Знак нарисован цветом дважды: линией у своего верхнего края и тенью над ней.
   * Контраст считается у линии и к обеим поверхностям, на которые она ложится: к
   * карточке, которая уходит под край, и к заливке столбца — в промежутке между
   * карточками. Второе и есть худший случай: карточка кончилась у самого края, и под
   * линией нет ничего, кроме заливки.
   */
  const colors = (measured.shadow.match(/rgba?\([^)]*\)/g) ?? []).filter(
    // Tailwind собирает `box-shadow` из своих пустых слоёв (кольцо, внутренняя тень)
    // и нашего: прозрачные слои — не цвет, которым что-то нарисовано.
    (color) => !/, ?0\)$/.test(color),
  );
  expect(colors.length, report).toBe(2);
  const ratios = {
    card: contrast(colors[0] as string, measured.card),
    column: contrast(colors[0] as string, measured.column),
  };
  await test.info().attach(`контраст линии знака (${status})`, {
    body: JSON.stringify(
      { line: colors[0], card: measured.card, column: measured.column, ratios },
      null,
      2,
    ),
    contentType: 'application/json',
  });
  /*
   * Порог — не AA для текста: знак не текст и не элемент управления, а оформление
   * границы, и держится он на тех же линиях, что и все границы в проекте. Порог
   * стережёт другое: линия `--t-line` давала поверх заливки 1.06 в светлой теме
   * и 1.10 в тёмной и не была видна вовсе, а сильная линия даёт не меньше 1.29.
   */
  expect(
    Math.min(ratios.card, ratios.column),
    `${report} ${JSON.stringify(ratios)}`,
  ).toBeGreaterThanOrEqual(1.25);

  // `axe` смотрит на доску со знаком: он декоративный и в дереве доступности его нет.
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

test('знак края не добавляет остановок Tab: до первой карточки их столько же, сколько без него', async ({
  page,
  request,
}) => {
  const longest = await longestColumn(request);

  await silenceJournal(page);
  await page.setViewportSize(SHORT_WINDOW);
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, longest).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  /*
   * Остановки от начала страницы до ссылки первой карточки. Знак стоит внутри столбца,
   * и появись у него остановка — она попала бы ровно на этот путь.
   */
  const stops = async () => {
    /*
     * Точка, с которой браузер продолжает обход, живёт отдельно от фокуса, и `blur()`
     * её не двигает: второй проход считал бы шаги от той ссылки, на которой кончился
     * первый (замерено: 2 вместо 9). Сбрасывает её фокус на теле страницы.
     */
    await page.evaluate(() => {
      document.body.setAttribute('tabindex', '-1');
      document.body.focus();
      document.body.removeAttribute('tabindex');
      (document.activeElement as HTMLElement | null)?.blur();
    });

    let count = 0;
    let at = { card: false, edge: false };
    while (count < 100 && !at.card) {
      await page.keyboard.press('Tab');
      count += 1;
      at = await page.evaluate(() => {
        const active = document.activeElement;
        return {
          card: active?.closest('article') != null,
          // Знак фокуса не принимает вовсе: у него нет ни роли, ни `tabindex`.
          edge: active?.hasAttribute('data-edge') ?? false,
        };
      });
      expect(at.edge, 'фокус встал на знак края').toBe(false);
    }
    expect(at.card, `до карточки не дошли за ${count} остановок`).toBe(true);
    return count;
  };

  const low = await settledEdges(page, 'знак разошёлся с прокруткой на низком окне');
  expect(
    low.filter((seen) => seen.sign).length,
    `знака нет ни у одного столбца, сравнивать не с чем: ${JSON.stringify(low)}`,
  ).toBeGreaterThan(0);
  const withSign = await stops();

  /*
   * Тот же путь на том же экране без знака: в высоком окне столбцы помещаются целиком,
   * и знака нет ни у одного. Разметка при этом та же самая — меняется только окно.
   */
  await page.setViewportSize(TALL_WINDOW);
  const tall = await settledEdges(page, 'знак разошёлся с прокруткой на высоком окне');
  expect(
    tall.filter((seen) => seen.sign).length,
    `в высоком окне знак остался: ${JSON.stringify(tall)}`,
  ).toBe(0);
  const withoutSign = await stops();

  await test.info().attach('остановки Tab до первой карточки', {
    body: JSON.stringify({ withSign, withoutSign }),
    contentType: 'application/json',
  });
  expect(withSign, `остановок со знаком ${withSign}, без знака ${withoutSign}`).toBe(withoutSign);
});

test('ниже точки остановки знака края нет: своей прокрутки у столбца там нет', async ({
  page,
  request,
}) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  // То же окно, что у проверки липкости: ниже `fold` прокручивается страница, а столбец
  // прокручиваемой областью не является вовсе (UI-68).
  await page.setViewportSize({ width: 320, height: 320 });
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const measured = await edges(page);
  const report = JSON.stringify(measured);
  for (const seen of measured) {
    expect(seen.over, report).toBe(0);
    expect(seen.sign, report).toBe(false);
  }
  // И это не потому, что прокручивать нечего вовсе: страница длиннее окна.
  const room = await page.evaluate(
    () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
  );
  expect(room, report).toBeGreaterThan(0);
});
