import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
  contractStatuses,
  fontsReady,
  outsideArchive,
  readE2eToken,
  shellReady,
  silenceJournal,
} from './contour';

/**
 * Родитель задачи на карточке доски и в строке списка (UI-119) — на демо-данных, как
 * они есть: сценарий только читает. Длинное название родителя и отказ второму родителю
 * заводит себе пишущий `parents-long.spec.ts`.
 */

interface Parent {
  key: string;
  title: string;
}

interface Row {
  key: string;
  title: string;
  status: string;
  parent: Parent | null;
}

/** Столбцы, раскрытые на доске по умолчанию: `done` и `cancelled` свёрнуты. */
const OPEN_COLUMNS = new Set(['backlog', 'open', 'in_progress', 'waiting']);

/**
 * Задача демо с родителем, её родитель и задача верхнего уровня — по правде бэкенда,
 * а не по памяти теста. Какая задача демо чья, решает сид бэкенда, и ключи, выписанные
 * здесь руками, разошлись бы с ним молча.
 */
async function family(request: APIRequestContext): Promise<{ child: Row; top: Row }> {
  const query = new URLSearchParams({ project: 'DEMO', limit: '100', query: outsideArchive() });
  for (const field of ['title', 'status', 'parent']) query.append('fields', field);
  const response = await request.get(`/api/v1/tasks?${query.toString()}`, {
    headers: { Authorization: `Bearer ${readE2eToken()}` },
  });
  expect(response.status()).toBe(200);
  const rows = ((await response.json()) as { data: Row[] }).data;

  const shown = rows.filter((row) => OPEN_COLUMNS.has(row.status));
  const child = shown.find((row) => row.parent !== null);
  const top = shown.find((row) => row.parent === null);
  if (child === undefined || top === undefined) {
    throw new Error(
      `В демо нет пары «с родителем и без» на раскрытых столбцах: ${JSON.stringify(rows)}`,
    );
  }
  return { child, top };
}

/** Карточка задачи — по её собственной ссылке: подпись родителя несёт чужой ключ. */
function cardOf(page: Page, row: Row): Locator {
  return page
    .getByRole('article')
    .filter({ has: page.getByRole('link', { name: row.title, exact: true }) });
}

function rowOf(page: Page, row: Row): Locator {
  return page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: row.key }) });
}

function caption(scope: Locator): Locator {
  return scope.locator('[data-mark="parents"]');
}

test('на доске у задачи с родителем видны его ключ и название, и клик по ним ведёт в родителя', async ({
  page,
  request,
}) => {
  const { child, top } = await family(request);
  const parent = child.parent as Parent;
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO&view=board');
  await shellReady(page);

  const card = cardOf(page, child);
  await expect(card).toBeVisible();
  const shown = caption(card);
  await expect(shown).toBeVisible();
  await expect(shown).toContainText(parent.key);
  await expect(shown).toContainText(parent.title);
  // Подпись — первая строка карточки, над ключом.
  expect(
    await card.evaluate((node) => node.firstElementChild?.getAttribute('data-mark') ?? null),
  ).toBe('parents');

  // У задачи верхнего уровня подписи нет вовсе, и ссылка на карточке одна — своя.
  await expect(caption(cardOf(page, top))).toHaveCount(0);
  await expect(cardOf(page, top).getByRole('link')).toHaveCount(1);

  /*
   * Попадание — как у человека. Над подписью лежит сама поднятая ссылка на родителя,
   * над ключом — растяжка ссылки названия. Отсюда и подсказка: у неподнятого узла
   * карточки своей подсказки не бывает, её даёт то, во что попал курсор.
   */
  const hit = async (target: Locator) => {
    await target.scrollIntoViewIfNeeded();
    const box = await target.boundingBox();
    if (box === null) throw new Error('Узел не на экране');
    return page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.closest('a')?.getAttribute('href') ?? null,
      [box.x + box.width / 2, box.y + box.height / 2] as const,
    );
  };
  expect(await hit(shown.getByRole('link'))).toBe(`/tasks/${parent.key}`);
  expect(await hit(card.getByText(child.key, { exact: true }))).toBe(`/tasks/${child.key}`);

  // Клик по подписи ведёт в родителя: ссылка поднята над растяжкой карточки.
  await shown.getByRole('link').click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${parent.key}$`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText(parent.key);

  // Остальная карточка по-прежнему ведёт в саму задачу: и ключ, и пустое поле. Их
  // перекрывает растяжка, поэтому клик — координатами, как у человека.
  await page.goBack();
  await expect(cardOf(page, child)).toBeVisible();
  await cardOf(page, child).getByText(child.key, { exact: true }).click({ force: true });
  await expect(page).toHaveURL(new RegExp(`/tasks/${child.key}$`));

  await page.goBack();
  await expect(cardOf(page, child)).toBeVisible();
  await cardOf(page, child).click({ position: { x: 6, y: 6 }, force: true });
  await expect(page).toHaveURL(new RegExp(`/tasks/${child.key}$`));
});

test('в таблице родитель — плашка «родитель KEY»: нажатие открывает панель «Родитель задачи X», высота строк одна', async ({
  page,
  request,
}) => {
  const { child, top } = await family(request);
  const parent = child.parent as Parent;
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await shellReady(page);

  const row = rowOf(page, child);
  const badge = caption(row);
  await expect(badge).toBeVisible();
  // Словом, а не одной стрелкой: в какую сторону связь, сказано (UI-152).
  await expect(badge).toHaveText(new RegExp(`родитель\\s*${parent.key}`));
  await expect(caption(rowOf(page, top))).toHaveCount(0);

  /*
   * Высота строки задана токеном и от плашки не растёт (решение Д4). Меряется после
   * подстановки шрифта: Fira меняет метрику, и замер до неё сравнивал бы гарнитуры.
   */
  await fontsReady(page);
  const heights = await page
    .locator('tbody tr')
    .evaluateAll((rows) => rows.map((node) => node.getBoundingClientRect().height));
  await test.info().attach('высоты строк таблицы', {
    body: JSON.stringify({ heights }),
    contentType: 'application/json',
  });
  expect(new Set(heights).size, `высоты строк: ${JSON.stringify(heights)}`).toBe(1);

  // Название задачи с родителем и без стоит на одном месте и одной ширины: гнездо
  // под плашку одно у всех строк (UI-152).
  const title = (scope: Locator) =>
    scope.locator('a[data-link="task"] span').evaluate((node) => {
      const box = node.getBoundingClientRect();
      const tr = (node.closest('tr') as Element).getBoundingClientRect();
      return { left: box.left, top: box.top - tr.top, width: box.width };
    });
  const [mine, plain] = [await title(row), await title(rowOf(page, top))];
  expect(mine.left).toBe(plain.left);
  expect(mine.width).toBe(plain.width);
  // Четверть пикселя по высоте даёт `truncate` у одного из названий, а не родитель.
  expect(Math.abs(mine.top - plain.top)).toBeLessThanOrEqual(0.5);

  // Нажатие раскрывает панель, а не уводит в задачу.
  await badge.click();
  const panel = page.getByRole('dialog');
  await expect(panel).toBeVisible();
  await expect(page).toHaveURL(/\/tasks\?/);
  await expect(badge).toHaveAttribute('aria-expanded', 'true');
  // Панель называет задачу строки: чей это родитель, а не чей ребёнок.
  await expect(panel).toContainText(`Родитель задачи ${child.key}`);
  await expect(panel.getByRole('link')).toHaveText(`${parent.key} · ${parent.title}`);

  // Клик по тексту панели не всплывает через портал в обработчик строки.
  await panel.getByText(`Родитель задачи`).click();
  await expect(page).toHaveURL(/\/tasks\?/);

  // Esc закрывает панель и возвращает фокус на плашку.
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(badge).toBeFocused();

  // Ссылка в панели ведёт в родителя.
  await badge.click();
  await page.getByRole('dialog').getByRole('link').click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${parent.key}$`));

  // Клик по остальной строке — в саму задачу.
  await page.goBack();
  await expect(rowOf(page, child)).toBeVisible();
  await rowOf(page, child).getByRole('cell').last().click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${child.key}$`));
});

/**
 * Запросы к списку задач за отрисовку экрана, пока они не перестанут приходить.
 * Живой поток заглушён: он перечитывает показанное по кадрам журнала и сделал бы число
 * случайным, а проверяется здесь то, что родитель приезжает строкой, а не запросом.
 */
async function calmCalls(calls: string[]): Promise<string[]> {
  let previous = -1;
  await expect
    .poll(
      () => {
        const stable = calls.length === previous && calls.length > 0;
        previous = calls.length;
        return stable;
      },
      { intervals: [500, 500, 500, 500, 500], timeout: 15_000 },
    )
    .toBe(true);
  return [...calls];
}

test('родителя приносит та же выдача: запросов столько же, на родителя — ни одного', async ({
  page,
  request,
}) => {
  const { child } = await family(request);
  const parent = child.parent as Parent;
  await silenceJournal(page);

  const calls: string[] = [];
  page.on('request', (call) => {
    const url = new URL(call.url());
    if (url.pathname.startsWith('/api/v1/tasks')) calls.push(`${url.pathname}${url.search}`);
  });

  // Доска: по запросу на столбец и один на число выдачи — как до UI-119 (UI-70).
  await page.goto('/tasks?project=DEMO&view=board');
  await expect(caption(cardOf(page, child))).toBeVisible();
  const board = await calmCalls(calls);

  // Таблица: одна страница выдачи — как до UI-119.
  calls.length = 0;
  await page.goto('/tasks?project=DEMO');
  await expect(caption(rowOf(page, child))).toBeVisible();
  const table = await calmCalls(calls);

  await test.info().attach('запросы к задачам', {
    body: JSON.stringify({ board, table }, null, 2),
    contentType: 'application/json',
  });

  const single = (list: string[]) => list.filter((path) => /^\/api\/v1\/tasks\/[^/?]+/.test(path));
  expect(single(board), 'запрос за карточкой задачи на доске').toEqual([]);
  expect(single(table), 'запрос за карточкой задачи в таблице').toEqual([]);
  expect(board.join('\n')).not.toContain(`/tasks/${parent.key}`);
  expect(table.join('\n')).not.toContain(`/tasks/${parent.key}`);

  expect(board, 'запросов на отрисовку доски').toHaveLength(contractStatuses().length + 1);
  expect(table, 'запросов на отрисовку таблицы').toHaveLength(1);

  // Каждый запрос, читающий строки, просит родителей в наборе полей — тем же запросом.
  const reading = [...board, ...table]
    .map((path) => new URL(path, 'http://contour').searchParams)
    .filter((params) => params.get('limit') !== '1');
  expect(reading.length).toBeGreaterThan(0);
  for (const params of reading) expect(params.getAll('fields')).toContain('parent');
});

test('плашка родителя — своя остановка табом, и строку задачи она не обводит', async ({
  page,
  request,
}) => {
  const { child } = await family(request);
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await shellReady(page);

  const row = rowOf(page, child);
  await row.locator('a[data-link="task"]').focus();
  await page.keyboard.press('Tab');

  // За своей ссылкой строки — плашка родителя, и фокус на ней виден.
  const badge = caption(row);
  await expect(badge).toBeFocused();
  const drawn = await badge.evaluate((node) => ({
    own: getComputedStyle(node).outlineStyle,
    row: getComputedStyle(node.closest('tr') as Element).outlineStyle,
  }));
  expect(drawn.own).not.toBe('none');
  // Обведённая строка обещала бы Enter в эту задачу, а Enter раскроет родителя.
  expect(drawn.row).toBe('none');

  // Enter раскрывает панель — с клавиатуры так же, как нажатием.
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toContainText(`Родитель задачи ${child.key}`);
});
