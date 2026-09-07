import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/*
 * Сценарий пишущий и идёт последним среди пишущих: он заводит в очереди DEMO два
 * десятка задач, и соседи, которые ищут демо-задачи по ключу (`DEMO-3` находит и
 * `DEMO-30`), после него падали бы строгим режимом локатора. Порядок задаётся именем
 * файла — Playwright берёт файлы по алфавиту, и `task-list-screen` стоит после
 * `answer`, `layout`, `live` и `paging` (`playwright.config.ts`, проект «запись»).
 */

/**
 * Метка своего набора данных. Замеры первого экрана нельзя ставить на демо-задачи:
 * их семь, они короткие, и число строк на экране менялось бы вместе с демо.
 */
const TAG = 'ui12-first-screen';

/** Столько задач заводится: экран обязан вместить больше, чем помещалось раньше. */
const TASKS = 21;

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

async function makeTask(
  request: APIRequestContext,
  title: string,
  overrides: Record<string, unknown> = {},
): Promise<string> {
  const created = await request.post('/api/v1/tasks', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      queue: 'DEMO',
      title,
      description: 'Заведена сквозным тестом ради замеров первого экрана списка.',
      tags: [TAG],
      ...overrides,
    },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { data: { key: string } }).data.key;
}

/** Ключи задач набора, уже заведённых в установке. */
async function taggedKeys(request: APIRequestContext): Promise<string[]> {
  const response = await request.get(
    `/api/v1/tasks?queue=DEMO&tags=${TAG}&fields=title&limit=200&sort=key`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { data: { key: string }[] };
  return body.data.map((item) => item.key);
}

/**
 * Набор из двадцати одной задачи, среди которых три с названием в две строки, а
 * последняя — та, в которую сценарий про активность подошьёт запись.
 *
 * Заводятся только недостающие, и это не бережливость: упавший сценарий заставляет
 * Playwright выбросить воркер и начать новый, а вместе с воркером обнуляется память
 * модуля. Набор, заведённый безусловно, после первого же падения удваивался бы — и
 * следующие сценарии падали бы на числе строк, уводя разбор от настоящей причины.
 */
let ready: Promise<string[]> | null = null;

function seed(request: APIRequestContext): Promise<string[]> {
  ready ??= (async () => {
    const long =
      'Задача с намеренно длинным названием, которое не помещается в одну строку ' +
      'колонки и переносится, как переносятся настоящие названия заданий';

    const keys = await taggedKeys(request);
    for (let index = keys.length; index < TASKS; index += 1) {
      const twoLines = index < 3;
      const alive = index === TASKS - 1;
      keys.push(
        await makeTask(
          request,
          alive
            ? 'Задача набора, в которую подшивают запись'
            : twoLines
              ? `${long} — ${index + 1}`
              : `Задача набора № ${index + 1}`,
          { priority: !alive && index % 4 === 0 ? 'high' : 'normal' },
        ),
      );
    }
    return keys;
  })();

  return ready;
}

function rows(page: Page): Locator {
  return page.locator('tbody tr');
}

/** Верх элемента в окне. Элемент приводится в вид заранее: см. `docs/notes/ui.md`. */
async function topOf(target: Locator): Promise<number> {
  return (await target.boundingBox())?.y ?? Number.NaN;
}

/** Сколько строк целиком помещается в окно. */
async function visibleRows(page: Page): Promise<number> {
  // Замер снимается тем шрифтом, которым экран будет жить: Fira приходит с внешнего
  // хоста и после подстановки меняет высоту строки, а с ней и число видимых строк.
  await fontsReady(page);
  return page.evaluate(() => {
    const height = window.innerHeight;
    return Array.from(document.querySelectorAll('tbody tr')).filter((node) => {
      const box = node.getBoundingClientRect();
      return box.top >= 0 && box.bottom <= height;
    }).length;
  });
}

test.describe('первый экран списка', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('занят задачами, а не формой отбора', async ({ page, request }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(`/tasks?queue=DEMO&tags=${TAG}`);
    await expect(rows(page)).toHaveCount(TASKS);

    // Форма свёрнута, но отбор не спрятан: свёрнутая строка называет его словами.
    await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText(`тег ${TAG}`);
    await expect(page.getByLabel('Исполнитель')).toBeHidden();

    // Было: 415 px до первой строки и семь строк на экране.
    expect(await topOf(rows(page).first())).toBeLessThan(200);
    expect(await visibleRows(page)).toBeGreaterThanOrEqual(12);
  });

  test('шапка таблицы подписывает колонки на любой глубине прокрутки', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(`/tasks?queue=DEMO&tags=${TAG}`);
    await expect(rows(page)).toHaveCount(TASKS);

    await rows(page).last().scrollIntoViewIfNeeded();

    // Последняя строка внизу — а заголовки колонок всё ещё на экране, все до одного.
    await expect(rows(page).last()).toBeInViewport();
    await expect(page.getByRole('columnheader', { name: 'Активность' })).toBeInViewport();
    await expect(page.getByRole('columnheader', { name: 'Ключ' })).toBeInViewport();
  });

  test('отказ разбора запроса не сдвигает таблицу', async ({ page, request }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(`/tasks?queue=DEMO&tags=${TAG}`);
    await expect(rows(page)).toHaveCount(TASKS);

    await page.getByRole('button', { name: 'Изменить отбор' }).click();
    await fontsReady(page);
    const before = await topOf(rows(page).first());

    const field = page.getByLabel('Запрос на языке бэкенда');
    await field.fill('status: opne');
    // Черновик говорит о себе сам, до всякого применения.
    await expect(page.getByText('не применено, Enter применит')).toBeVisible();
    await field.press('Enter');

    const problem = page.getByRole('alert');
    await expect(problem).toContainText('Ошибка в символе 9');
    await expect(problem).toContainText('Показаны строки предыдущего отбора');

    // Объяснение наложено на страницу, а не встроено в поток: строки на месте.
    expect(Math.abs((await topOf(rows(page).first())) - before)).toBeLessThanOrEqual(8);
    await expect(rows(page)).toHaveCount(TASKS);
  });

  test('активность в деле видна в строке, и по ней есть порядок', async ({ page, request }) => {
    test.setTimeout(120_000);
    await silenceJournal(page);

    // Задача набора, в которую только что подшили запись: при порядке по активности
    // она обязана стоять первой.
    const key = (await seed(request)).at(-1) as string;
    const entry = await request.post(`/api/v1/tasks/${key}/entries`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { type: 'note', title: 'Запись ради признака активности' },
    });
    expect(entry.status()).toBe(201);

    await page.goto(`/tasks?queue=DEMO&tags=${TAG}&sort=-last_entry_at`);

    const first = rows(page).first();
    await expect(first.getByRole('rowheader')).toHaveText(key);
    // В строке ровно одно время, и это активность в деле: у остальных задач набора
    // записей нет вовсе, и они говорят об этом словами.
    await expect(first.locator('time')).toHaveCount(1);
    await expect(rows(page).nth(1).getByText('в деле пусто')).toBeVisible();

    // Порядок берётся из адреса и меняется полем, которое видно и при свёрнутом отборе.
    await expect(page.getByLabel('Сортировка')).toHaveValue('-last_entry_at');
    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/v1/tasks?') && response.url().includes('sort=key'),
      ),
      page.getByLabel('Сортировка').selectOption('key'),
    ]);
    await expect(first.getByRole('rowheader')).not.toHaveText(key);
  });

  test('ссылка с отбором открывается в чистом контексте тем же списком', async ({
    page,
    request,
    browser,
  }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(`/tasks?queue=DEMO&tags=${TAG}&priority=high&sort=key`);
    await expect(rows(page)).toHaveCount(5);
    const keys = await page.getByRole('rowheader').allInnerTexts();

    // Чистый контекст: ни хранилища этой вкладки, ни её памяти о свёрнутом отборе.
    const fresh = await browser.newContext();
    await fresh.addInitScript((value) => {
      window.localStorage.setItem('tracker.token', value);
    }, token);

    try {
      const copy = await fresh.newPage();
      await silenceJournal(copy);
      await copy.goto(page.url());

      await expect(copy.locator('tbody tr')).toHaveCount(5);
      expect(await copy.getByRole('rowheader').allInnerTexts()).toEqual(keys);
      await expect(copy.getByRole('list', { name: 'Условия отбора' })).toContainText(
        'приоритет high',
      );
    } finally {
      await fresh.close();
    }
  });
});

test.describe('список на узком экране', () => {
  test.use({ viewport: { width: 900, height: 800 } });

  test('строка отбора и таблица укладываются без горизонтальной прокрутки', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(`/tasks?queue=DEMO&tags=${TAG}`);
    await expect(rows(page)).toHaveCount(TASKS);

    // Таблица сжимаема: обёртка обрезает переполнение (`overflow-x: clip`) и потому
    // прокручиваемым предком не становится — иначе липкая шапка перестала бы липнуть.
    const scroll = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(scroll.width).toBe(scroll.client);

    // Условия отбора не спрятаны и на узком экране: перенеслись, но названы все.
    await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText(`тег ${TAG}`);

    await rows(page).last().scrollIntoViewIfNeeded();
    await expect(page.getByRole('columnheader', { name: 'Ключ' })).toBeInViewport();
  });
});
