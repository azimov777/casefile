import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import {
  contractStatuses,
  fontsReady,
  readE2eToken,
  silenceJournal,
  tasksByStatus,
} from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

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
  }

  // Один запрос списка на отрисовку доски.
  expect(calls).toHaveLength(1);
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
