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
 * Опознаватель своего набора данных. Замеры первого экрана нельзя ставить на демо-задачи:
 * их семь, они короткие, и число строк на экране менялось бы вместе с демо.
 *
 * Раньше набор помечался машинной меткой `tags`; поле снято вместе со всей механикой
 * (UI-41), и опознавателем стала фраза из **описания**, а находит её отбор `text` — он
 * ищет в названии и в описании сразу. Описание, а не название, намеренно: в списке оно
 * не показано, поэтому опознаватель не участвует ни в одном замере ширин и переносов,
 * а этот файл только их и делает.
 *
 * Фраза, а не вставленное в скобках слово: односложную метку тут держало то, что
 * структурный отбор `text` отвергал значение из двух слов (`422 invalid_search_query`),
 * и это ограничение снято (TRK-21). Фраза обязана оставаться уникальной в очереди DEMO:
 * совпав с чужой задачей, сценарий нашёл бы её и своей не завёл.
 *
 * На экране она видна: свёрнутый отбор называет условие чипом «текст «…»». Замеров это
 * не касается — чип стоит в строке отбора, а меряются строки таблицы.
 */
const MARKER = 'ради замеров первого экрана списка';

/** Адрес списка, отобранного до своего набора: им начинается каждый сценарий файла. */
const LIST = `/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}`;

/** Столько задач заводится: экран обязан вместить больше, чем помещалось раньше. */
const TASKS = 21;

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
      description: `Заведена сквозным тестом ${MARKER}.`,
      ...overrides,
    },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { data: { key: string } }).data.key;
}

/** Ключи задач набора, уже заведённых в установке. */
async function seededKeys(request: APIRequestContext): Promise<string[]> {
  const response = await request.get(
    `/api/v1/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}&fields=title&limit=200&sort=key`,
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

    const keys = await seededKeys(request);
    for (let index = keys.length; index < TASKS; index += 1) {
      const twoLines = index < 3;
      const alive = index === TASKS - 1;
      const manyTags = index % 4 === 0;
      keys.push(
        await makeTask(
          request,
          alive
            ? 'Задача набора, в которую подшивают запись'
            : twoLines
              ? `${long} — ${index + 1}`
              : `Задача набора № ${index + 1}`,
          {
            priority: !alive && manyTags ? 'high' : 'normal',
          },
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

  test('все строки одной высоты, включая строки с длинными названиями', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(LIST);
    await expect(rows(page)).toHaveCount(TASKS);
    await fontsReady(page);

    const heights = await page.evaluate(() =>
      Array.from(document.querySelectorAll('tbody tr')).map(
        (node) => node.getBoundingClientRect().height,
      ),
    );

    // Было (замер до правки, UI-31#11): 40.3 px у всех строк, и это при том, что
    // колонка тегов расширялась под самый длинный набор, отнимая ширину у названия.
    // Колонки тегов больше нет (UI-41), а требование к ритму строк осталось прежним.
    const spread = Math.max(...heights) - Math.min(...heights);
    expect(spread).toBeLessThanOrEqual(2);

    // Строк на первом экране не меньше, чем было: 17.
    expect(await visibleRows(page)).toBeGreaterThanOrEqual(17);
  });

  test('длинное название обрезается, но отдаётся целиком подсказкой', async ({ page, request }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(`${LIST}&sort=key`);
    await expect(rows(page)).toHaveCount(TASKS);
    await fontsReady(page);

    // У первых трёх задач набора название заведомо длиннее колонки.
    const long = rows(page).first().locator('[title]').first();
    const measured = await long.evaluate((node) => ({
      scroll: node.scrollWidth,
      client: node.clientWidth,
      title: node.getAttribute('title') ?? '',
    }));

    expect(measured.scroll).toBeGreaterThan(measured.client);
    expect(measured.title.length).toBeGreaterThan(60);
  });

  test('занят задачами, а не формой отбора', async ({ page, request }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(LIST);
    await expect(rows(page)).toHaveCount(TASKS);

    // Панель закрыта, но отбор не спрятан: строка состояния называет его словами.
    await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText(
      `текст «${MARKER}»`,
    );
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

    await page.goto(LIST);
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

    await page.goto(LIST);
    await expect(rows(page)).toHaveCount(TASKS);

    // Режим запроса сменяет строку поиска полем запроса той же высоты.
    await page.getByRole('button', { name: 'Запрос', exact: true }).click();
    await fontsReady(page);
    const before = await topOf(rows(page).first());

    const field = page.getByLabel('Запрос на языке бэкенда');
    await field.fill('status: opne');
    // Черновик говорит о себе сам, до всякого применения.
    await expect(page.getByText('↵ применить')).toBeVisible();
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

    await page.goto(`${LIST}&sort=-last_entry_at`);

    const first = rows(page).first();
    await expect(first.getByRole('rowheader')).toHaveText(key);
    // В строке ровно одно время, и это активность в деле: у остальных задач набора
    // записей нет вовсе, и они говорят об этом словами.
    await expect(first.locator('time')).toHaveCount(1);
    await expect(rows(page).nth(1).getByText('в деле пусто')).toBeVisible();

    // Порядок берётся из адреса и меняется списком, который виден и при свёрнутом
    // отборе. Список — компонент Radix: открывается кнопкой, значение выбирается пунктом.
    const sort = page.getByRole('combobox', { name: 'Сортировка' });
    await expect(sort).toContainText('сначала живые в деле');
    await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/api/v1/tasks?') && response.url().includes('sort=key'),
      ),
      (async () => {
        await sort.click();
        await page.getByRole('option', { name: 'по ключу', exact: true }).click();
      })(),
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

    await page.goto(`${LIST}&priority=high&sort=key`);
    await expect(rows(page)).toHaveCount(5);
    const keys = await page.getByRole('rowheader').allInnerTexts();

    // Чистый контекст: ни памяти этой вкладки о свёрнутом отборе, ни её хранилища.
    // Ключ ему не подсевают — его отдаёт установка, как и всякой другой вкладке.
    const fresh = await browser.newContext();

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

  test('страница не едет вбок, а название держит свою ширину', async ({ page, request }) => {
    test.setTimeout(120_000);
    await seed(request);
    await silenceJournal(page);

    await page.goto(LIST);
    await expect(rows(page)).toHaveCount(TASKS);
    await fontsReady(page);

    // Страница вширь не едет: прокрутка таблицы остаётся внутри её рамки.
    const scroll = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(scroll.width).toBe(scroll.client);

    // Условия отбора не спрятаны и на узком экране: перенеслись, но названы все.
    await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText(
      `текст «${MARKER}»`,
    );

    /*
     * 900 px — середина той полосы, где панель забирает место, а таблица его не
     * получает: здесь у названия было 66 px, то есть три буквы и многоточие. Теперь
     * таблица не сжимается ниже своего минимума, а прокручивается, и названию
     * достаётся та же строка текста, что и на телефоне (UI-66).
     *
     * Липкой шапки на этой ширине нет и быть не может: прокрутка вбок делает рамку
     * прокручиваемым предком, и шапка липнет к ней (`docs/notes/ui.md`, «Липкую шапку
     * таблицы ломает `overflow` у её обёртки»). Что шапка жива там, где таблица
     * помещается целиком, стережёт сценарий выше — на 1440 px.
     */
    const title = await page.getByRole('columnheader', { name: 'Название' }).boundingBox();
    expect(Math.round(title?.width ?? 0)).toBeGreaterThanOrEqual(184);
  });
});
