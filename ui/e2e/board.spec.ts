import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/**
 * Значения статуса берутся из контракта, а не перечисляются здесь: перечисление уже
 * менялось (2026-09-05 из него убрали статус) и может измениться снова, а доска обязана
 * пережить это без правок — в том числе в тестах.
 */
function contractStatuses(): string[] {
  const contract = JSON.parse(
    readFileSync(resolve(process.cwd(), '../tracker/openapi.json'), 'utf8'),
  ) as { components: { schemas: { TaskStatus: { enum: string[] } } } };
  return contract.components.schemas.TaskStatus.enum;
}

/** Какие задачи демо в каком статусе — по правде бэкенда, а не по памяти теста. */
async function tasksByStatus(request: APIRequestContext): Promise<Map<string, string[]>> {
  const response = await request.get('/api/v1/tasks?queue=DEMO&fields=status&limit=100', {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: { key: string; status: string }[] };

  const byStatus = new Map<string, string[]>();
  for (const task of body.data) {
    byStatus.set(task.status, [...(byStatus.get(task.status) ?? []), task.key]);
  }
  return byStatus;
}

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
  const expected = await tasksByStatus(request);

  await page.goto('/tasks?queue=DEMO&view=board&assignee=demo_agent');
  await expect(column(page, 'open')).toBeVisible();

  // В столбцах остались только задачи этого исполнителя: их меньше, чем всего в статусе.
  const openKeys = expected.get('open') ?? [];
  await expect(column(page, 'open').getByRole('article')).not.toHaveCount(openKeys.length);
  await expect(
    column(page, 'open').getByRole('article').filter({ hasText: 'DEMO-4' }),
  ).toBeVisible();

  await page.getByRole('radio', { name: 'Таблица' }).click();

  await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText(
    'исполнитель demo_agent',
  );
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('rowheader', { name: 'DEMO-4' })).toBeVisible();
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

test('у карточек столбца подвал на одном месте, а название не длиннее двух строк', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
  await fontsReady(page);

  const measured = await column(page, 'open').evaluate((node) => {
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
