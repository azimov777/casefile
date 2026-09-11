import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  contractStatuses,
  readE2eToken,
  shownKeys,
  silenceJournal,
  tasksByStatus,
} from './contour';

/**
 * Архив: закрытые задачи, в делах которых больше трёх дней не писали, список и доска
 * по умолчанию не показывают (UI-97). Правило считается при чтении от часов браузера,
 * поэтому проверяется сдвигом этих часов (`page.clock`): записи демо все «сейчас»,
 * а время записи бэкенд задать не даёт.
 *
 * Сценарий только читает и идёт в обеих темах: `axe` на переключателе архива обязан
 * пройти и там, и там.
 */

const DAY = 24 * 60 * 60 * 1000;

/** Столько вперёд сдвигаются часы браузера: порог три дня, и все закрытые демо за ним. */
const SHIFT = 4 * DAY;

/** Сколько стоять в покое, чтобы поймать перезапрос, которого быть не должно. */
const REST = 5_000;

const CLOSED = ['done', 'cancelled'];

function rows(page: Page) {
  return page.locator('tbody tr');
}

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

function archive(page: Page) {
  return page.getByRole('checkbox', { name: 'показывать архив' });
}

/** Запросы к списку задач, снятые с этой страницы. */
function watchRequests(page: Page): string[] {
  const calls: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks?')) calls.push(call.url());
  });
  return calls;
}

/** Числа в отчёт прогона: вердикт по проверке называет их, а не «прошло». */
function report(type: string, numbers: unknown): void {
  const description = JSON.stringify(numbers);
  test.info().annotations.push({ type, description });
  console.log(`[${type}] ${description}`);
}

/** Карточек в каждом столбце доски — по статусам контракта. */
async function cardsByStatus(page: Page): Promise<Record<string, number>> {
  const counted: Record<string, number> = {};
  for (const status of contractStatuses()) {
    counted[status] = await column(page, status).getByRole('article').count();
  }
  return counted;
}

/** Сколько задач каждого статуса в составе — по правде бэкенда. */
function sizes(byStatus: Map<string, string[]>): Record<string, number> {
  return Object.fromEntries(
    contractStatuses().map((status) => [status, byStatus.get(status)?.length ?? 0]),
  );
}

/** Ждёт на доске ровно эти числа карточек по столбцам. */
async function expectBoard(page: Page, expected: Record<string, number>): Promise<void> {
  for (const [status, count] of Object.entries(expected)) {
    await expect(column(page, status).getByRole('article'), status).toHaveCount(count);
  }
}

async function everything(request: APIRequestContext) {
  const all = await tasksByStatus(request, {}, { archive: true });
  const closed = CLOSED.flatMap((status) => all.get(status) ?? []);
  const open = [...all.entries()]
    .filter(([status]) => !CLOSED.includes(status))
    .flatMap(([, keys]) => keys);
  return { all, closed, open };
}

test('со сдвигом часов на четыре дня закрытые задачи демо уходят из таблицы и с доски, а показ архива их возвращает', async ({
  page,
  request,
}) => {
  const { all, closed, open } = await everything(request);
  expect(closed.length, 'в демо нет закрытых задач — проверять нечего').toBeGreaterThan(0);
  const later = new Date(Date.now() + SHIFT);

  // Правда бэкенда при том же пороге, что посчитает браузер: вне архива — только
  // незакрытые. Это сверка самого правила, а не интерфейса.
  const shownLater = await tasksByStatus(request, {}, { now: later });
  expect([...shownLater.values()].flat().sort()).toEqual([...open].sort());

  await silenceJournal(page);
  await page.clock.install({ time: later });

  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(open.length);
  for (const key of open) await expect(page.getByRole('rowheader', { name: key })).toBeVisible();
  for (const key of closed) await expect(page.getByRole('rowheader', { name: key })).toHaveCount(0);
  await expect(archive(page)).not.toBeChecked();
  const tableHidden = await rows(page).count();

  // Доска: все столбцы развёрнуты, чтобы считать карточки, а не только числа.
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  const withoutArchive = { ...sizes(all), done: 0, cancelled: 0 };
  await expectBoard(page, withoutArchive);
  const boardHidden = await cardsByStatus(page);

  // Одно действие — и архив на месте: на доске и в таблице все задачи демо.
  await archive(page).click();
  await expect(page).toHaveURL(/archive=shown/);
  await expect(archive(page)).toBeChecked();
  await expectBoard(page, sizes(all));
  const boardShown = await cardsByStatus(page);

  await page.getByRole('link', { name: 'Таблица' }).click();
  await expect(page).toHaveURL(/archive=shown/);
  await expect(rows(page)).toHaveCount(open.length + closed.length);
  for (const key of closed) await expect(page.getByRole('rowheader', { name: key })).toBeVisible();

  report('часы +4 дня', {
    таблица: { безАрхива: tableHidden, сАрхивом: await rows(page).count() },
    доска: { безАрхива: boardHidden, сАрхивом: boardShown },
    закрытые: closed,
  });
});

test('без сдвига часов видны все задачи демо, в которых была работа; скрыта только закрытая без единой записи', async ({
  page,
  request,
}) => {
  const { all, closed, open } = await everything(request);
  const shown = await shownKeys(request);

  // Кого правило прячет прямо сейчас — это закрытые без единой записи агента или
  // человека: пустое `last_entry_at` тишину не прерывает (UI-97#6). В демо такая одна,
  // отменённая переходом `DEMO-7`.
  const silent = await tasksByStatus(
    request,
    { query: 'status: done, cancelled and last_entry_at: empty()' },
    { archive: true },
  );
  const neverWorked = [...silent.values()].flat();
  expect(all.size).toBeGreaterThan(0);
  expect([...open, ...closed].filter((key) => !shown.includes(key)).sort()).toEqual(
    [...neverWorked].sort(),
  );

  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(shown.length);
  for (const key of shown) await expect(page.getByRole('rowheader', { name: key })).toBeVisible();
  for (const key of neverWorked) {
    await expect(page.getByRole('rowheader', { name: key })).toHaveCount(0);
  }

  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  const byStatus = await tasksByStatus(request);
  await expectBoard(page, sizes(byStatus));
  const board = await cardsByStatus(page);

  report('часы как есть', {
    таблица: { строк: shown.length, всегоВДемо: open.length + closed.length },
    скрыты: neverWorked,
    доска: board,
  });
});

test('показ архива держится адресом: переживает перезагрузку и открывается ссылкой в новой вкладке', async ({
  page,
  context,
  request,
}) => {
  const { closed, open } = await everything(request);
  await page.clock.install({ time: new Date(Date.now() + SHIFT) });

  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(open.length);
  await archive(page).click();
  await expect(page).toHaveURL(/\/tasks\?queue=DEMO&archive=shown$/);
  await expect(rows(page)).toHaveCount(open.length + closed.length);

  await page.reload();
  await expect(archive(page)).toBeChecked();
  await expect(rows(page)).toHaveCount(open.length + closed.length);

  // Вторая вкладка того же контекста: часы у контекста одни, ссылка та же.
  const copy = await context.newPage();
  await copy.goto(page.url());
  await expect(archive(copy)).toBeChecked();
  await expect(rows(copy)).toHaveCount(open.length + closed.length);

  // Снять — тоже одно действие, и адрес возвращается к умолчанию.
  await archive(copy).click();
  await expect(copy).toHaveURL(/\/tasks\?queue=DEMO$/);
  await expect(rows(copy)).toHaveCount(open.length);
  await copy.close();
});

test('экран без событий потока не шлёт лишних запросов: порога в ключе запроса нет', async ({
  page,
}) => {
  await silenceJournal(page);
  const calls = watchRequests(page);

  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page).first()).toBeVisible();
  const tableAfterLoad = calls.length;
  // Перерисовки без чтения: раскрыть и свернуть отбор, навести на строку.
  await page.getByRole('button', { name: 'Изменить отбор' }).click();
  await page.getByRole('button', { name: 'Свернуть отбор' }).click();
  await rows(page).first().hover();
  await page.waitForTimeout(REST);
  const tableAfterRest = calls.length;

  const board = calls.length;
  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
  // Столбец на статус и одно число выдачи — то, что доска и должна прочитать (UI-70).
  await expect.poll(() => calls.length - board).toBe(contractStatuses().length + 1);
  const boardAfterLoad = calls.length - board;
  await page.waitForTimeout(REST);
  const boardAfterRest = calls.length - board;

  report('запросы', {
    таблица: { послеЗагрузки: tableAfterLoad, черезПокой: tableAfterRest },
    доска: { послеЗагрузки: boardAfterLoad, черезПокой: boardAfterRest },
    покой: REST,
  });
  expect(tableAfterLoad).toBe(1);
  expect(tableAfterRest).toBe(tableAfterLoad);
  expect(boardAfterRest).toBe(boardAfterLoad);
});

test('порог пересекается при следующем чтении, а не по часам: сам экран не перечитывает', async ({
  page,
  request,
}) => {
  const { closed } = await everything(request);
  const shown = await shownKeys(request);
  // Закрытые, в которых была работа: они видны сейчас и уйдут, когда пройдут три дня.
  const leaving = closed.filter((key) => shown.includes(key));
  expect(leaving.length, 'в демо нет закрытой задачи с работой в деле').toBeGreaterThan(0);

  await silenceJournal(page);
  const calls = watchRequests(page);

  await page.clock.install();
  await page.goto('/tasks?queue=DEMO');
  await expect(rows(page)).toHaveCount(shown.length);
  const before = calls.length;

  // Четыре дня прошли, пока вкладка стояла открытой: таймеров, перечитывающих список
  // ради порога, нет, и закрытые остаются на экране до следующего чтения.
  await page.clock.fastForward(SHIFT);
  await page.waitForTimeout(1_000);
  expect(calls.length).toBe(before);
  for (const key of leaving) await expect(page.getByRole('rowheader', { name: key })).toBeVisible();

  // Следующее чтение — и они ушли: порог считается в момент чтения.
  await page.reload();
  await expect(rows(page)).toHaveCount(shown.length - leaving.length);
  for (const key of leaving) {
    await expect(page.getByRole('rowheader', { name: key })).toHaveCount(0);
  }
});

test('запрос человека складывается с правилом архива, а опечатка в нём названа в его строке', async ({
  page,
}) => {
  const token = readE2eToken();
  const allDone = await (async () => {
    const response = await page.request.get(
      '/api/v1/tasks?queue=DEMO&status=done&fields=status&limit=100',
      { headers: { Authorization: `Bearer ${token}` } },
    );
    return ((await response.json()) as { data: { key: string }[] }).data.map((row) => row.key);
  })();
  expect(allDone.length).toBeGreaterThan(0);

  await silenceJournal(page);
  await page.clock.install({ time: new Date(Date.now() + SHIFT) });

  // `status: done` без показа архива — только неархивные `done`: со сдвигом их нет.
  const query = 'queue: DEMO and status: done';
  await page.goto(`/tasks?query=${encodeURIComponent(query)}`);
  await expect(page.getByText('Задач по этим условиям нет')).toBeVisible();
  await expect(page.getByText('Архив не показан.')).toBeVisible();

  // С показом — все `done` демо.
  await page.getByRole('button', { name: 'Показать архив' }).click();
  await expect(page).toHaveURL(/archive=shown/);
  await expect(rows(page)).toHaveCount(allDone.length);
  for (const key of allDone) await expect(page.getByRole('rowheader', { name: key })).toBeVisible();

  // Опечатка без показа архива: запрос ушёл склеенным, а символ и указатель — в строке
  // человека. `donee` стоит в ней на 25-м символе.
  const typo = 'queue: DEMO and status: donee';
  await page.goto(`/tasks?query=${encodeURIComponent(typo)}`);
  const problem = page.getByRole('alert');
  await expect(problem).toContainText(`Ошибка в символе ${typo.indexOf('donee') + 1}`);
  await expect(problem.locator('pre')).toHaveText(`${typo}\n${' '.repeat(typo.indexOf('donee'))}^`);
  await expect(problem).not.toContainText('last_entry_at');

  // Несошедшаяся скобка: такую строку не склеивают, и бэкенд объясняет её сам.
  const unbalanced = 'status: done)';
  await page.goto(`/tasks?query=${encodeURIComponent(unbalanced)}`);
  await expect(page.getByRole('alert')).toContainText('Ошибка в символе 13');
  await expect(page.getByRole('alert').locator('pre')).toHaveText(
    `${unbalanced}\n${' '.repeat(12)}^`,
  );
});

test('доступность таблицы и доски с переключателем архива', async ({ page }) => {
  await silenceJournal(page);

  for (const path of ['/tasks?queue=DEMO', '/tasks?queue=DEMO&view=board']) {
    await page.goto(path);
    await expect(archive(page)).toBeVisible();
    await expect(page.locator('tbody tr, article').first()).toBeVisible();

    const found = await new AxeBuilder({ page }).analyze();
    const serious = found.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map(
        (violation) => `${violation.id}: ${violation.nodes.map((node) => node.target).join(' ')}`,
      );
    report(`axe ${path}`, {
      нарушения: found.violations.map((violation) => `${violation.id} (${violation.impact})`),
      серьёзных: serious,
    });
    expect(serious, path).toEqual([]);
  }
});

/**
 * Отдельная проверка от предыдущей намеренно: там отбор по серьёзности остаётся —
 * это старый замер, и ослаблять его нельзя, — а здесь порог снят целиком. `heading-order`
 * (moderate) на доске в отбор `serious`/`critical` не попадал и оставался незамеченным до
 * UI-99, хотя `axe` его исправно ловил на каждом прогоне архива (UI-97).
 */
test('доска и таблица не дают ни одного нарушения `axe`, включая некритичные', async ({ page }) => {
  await silenceJournal(page);

  for (const path of ['/tasks?queue=DEMO', '/tasks?queue=DEMO&view=board']) {
    await page.goto(path);
    await expect(page.locator('tbody tr, article').first()).toBeVisible();

    const found = await new AxeBuilder({ page }).analyze();
    const violations = found.violations.map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.nodes.map((node) => node.target).join(' ')}`,
    );
    report(`axe (все уровни) ${path}`, { нарушения: violations });
    expect(violations, path).toEqual([]);
  }
});
