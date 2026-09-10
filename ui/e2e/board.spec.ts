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
  await page.goto('/tasks?queue=DEMO&view=board');

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
  const serious = result.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => violation.id);
  expect(serious).toEqual([]);
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
        head: rect(node.querySelector('h3') as Element),
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
    const head = node.querySelector('h3') as HTMLElement;
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
  const serious = result.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => violation.id);
  expect(serious).toEqual([]);
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

test('ниже точки остановки липкость снята: липнуть там не к чему', async ({ page, request }) => {
  const status = await longestColumn(request);

  await silenceJournal(page);
  /*
   * Ниже `fold` своей прокрутки у столбца нет, а порт прокрутки заголовка — всё равно
   * не окно: ряд столбцов ходит вбок (`overflow-x-auto`), и по спецификации это делает
   * его прокручиваемым по обеим осям. По вертикали ряду прокручивать нечего, поэтому
   * липкое там не двигается вовсе — а страница тем временем уезжает. Липкость снята
   * (`fold:sticky`), и сценарий стережёт именно это: обещать человеку неработающее
   * поведение хуже, чем не обещать.
   *
   * Окно ниже обычного: столбцы демо коротки, и на 420 px доска помещается целиком —
   * прокручивать было бы нечего.
   */
  await page.setViewportSize({ width: 320, height: 320 });
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  await expect(column(page, status).getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const DEEPER = 24;
  const room = await page.evaluate((deeper) => {
    const board = document.querySelector('section[aria-label="backlog"]') as HTMLElement;
    const row = board.parentElement as HTMLElement;
    const top = board.getBoundingClientRect().top + window.scrollY;
    window.scrollTo(0, Math.round(top) + deeper);
    return {
      over: document.documentElement.scrollHeight - document.documentElement.clientHeight,
      asked: Math.round(top) + deeper,
      position: getComputedStyle(board.querySelector('h3') as Element).position,
      rowOver: row.scrollHeight - row.clientHeight,
    };
  }, DEEPER);
  expect(room.over, 'странице нечего прокручивать').toBeGreaterThanOrEqual(room.asked);
  await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(room.asked);

  // Липкости здесь нет, и причина названа числом: ряду по вертикали прокручивать нечего.
  expect(room.position, JSON.stringify(room)).toBe('static');
  expect(room.rowOver, JSON.stringify(room)).toBe(0);

  const measured = await heads(page);
  const report = JSON.stringify({ room, ...measured });
  for (const seen of measured.columns) {
    // Заголовок уезжает вместе со своим столбцом — как и было до задачи.
    expect(seen.column.top, report).toBeLessThan(0);
    expect(seen.head.top - seen.column.top, report).toBe(1);
    // И столбец при этом прокручиваемой областью не стал: ниже точки остановки едет
    // страница.
    expect(seen.scrolled, report).toBe(0);
  }
});
