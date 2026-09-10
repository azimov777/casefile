import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { compose, fontsReady, readE2eToken } from './contour';

const token = readE2eToken();

/** Столько карточек читает столбец доски за раз (`entities/task`, `TASK_COLUMN_PAGE_SIZE`). */
const COLUMN_PAGE = 10;

/** Окно склейки кадров (`features/live-journal`, `COALESCE_WINDOW_MS`). */
const WINDOW = 1_000;

/** Сколько ждать в покое, чтобы поймать перечитывание, которого быть не должно. */
const REST = 10_000;

/**
 * Числа, которых стоит одно обновление доски помимо страниц раскрытых столбцов:
 * по одному на число каждого свёрнутого столбца (`done`, `cancelled`) и один на число
 * выдачи у заголовка экрана.
 */
const COUNTS = 3;

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

/** Полоса обновлений. По имени, а не по роли: роль `status` носит и индикатор связи. */
const bar = (page: Page) => page.getByRole('status', { name: 'Обновления списка' });

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Задачи отбора ключами, по правде бэкенда и в порядке доски: свежие в деле сверху. */
async function tasksIn(
  request: APIRequestContext,
  params: Record<string, string>,
): Promise<string[]> {
  const query = new URLSearchParams({
    queue: 'DEMO',
    fields: 'status',
    limit: '200',
    sort: '-last_entry_at',
    ...params,
  });
  const response = await request.get(`/api/v1/tasks?${query.toString()}`, { headers: auth() });
  expect(response.status()).toBe(200);
  return ((await response.json()) as { data: { key: string }[] }).data.map((row) => row.key);
}

/**
 * Заводит столько задач, чтобы столбец `backlog` не влез в одну страницу.
 *
 * Столбец нужен длинный: обновление доски перечитывает **все** прочитанные страницы
 * бесконечного запроса, и на коротком столбце цена этого не видна вовсе. Заводит их
 * сценарий сам и считает недостающее — соседний мог завести их раньше.
 */
async function fillBacklog(request: APIRequestContext): Promise<string[]> {
  const before = await tasksIn(request, { status: 'backlog' });
  const created = Array.from({ length: Math.max(COLUMN_PAGE + 3 - before.length, 0) }, (_, index) =>
    request.post('/api/v1/tasks', {
      headers: auth(),
      data: {
        queue: 'DEMO',
        title: `Задача для проверки живой доски № ${index + 1}`,
        description: 'Заведена сквозным тестом, чтобы столбец доски не влез в одну страницу.',
      },
    }),
  );
  for (const response of await Promise.all(created)) expect(response.status()).toBe(201);

  return tasksIn(request, { status: 'backlog' });
}

/**
 * Заводит задачу, которую сценарий двигает между столбцами.
 *
 * Разделы и проверка заполнены не для красоты: `backlog → open` требует четырёх
 * непустых разделов и непустого `checks`, иначе бэкенд отвечает
 * `409 task_sections_incomplete` (`../docs/ERRORS.md`). Задачи-наполнители
 * такому требованию не отвечают, и двигать надо именно эту.
 */
async function seedMover(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      queue: 'DEMO',
      title: 'Задача, которую сквозной тест двигает между столбцами',
      description: 'Заведена сквозным тестом: на ней проверяется, что доска обновляется сама.',
      goal: 'Проверить, что карточка переезжает в свой столбец без нажатия.',
      context: 'Сценарий `e2e/live-board.spec.ts` двигает эту задачу и возвращает обратно.',
      constraints: 'Ничего, кроме статуса, у задачи не меняется.',
      output: 'Карточка, переехавшая из `backlog` в `open` сама.',
      checks: ['Карточка видна в столбце `open` без единого нажатия'],
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

async function transition(
  request: APIRequestContext,
  key: string,
  data: Record<string, unknown>,
): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, { headers: auth(), data });
  expect(response.status(), await response.text()).toBe(200);
}

/** Запросы к списку задач, снятые с этой страницы. */
function watchRequests(page: Page): string[] {
  const calls: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks?')) calls.push(call.url());
  });
  return calls;
}

/** Ждёт, пока счётчик запросов перестанет расти: обновление улеглось. */
async function settled(count: () => number): Promise<void> {
  let previous = -1;
  await expect
    .poll(
      () => {
        const now = count();
        const stable = now === previous;
        previous = now;
        return stable;
      },
      { intervals: [400, 400, 400, 400, 400], timeout: 10_000 },
    )
    .toBe(true);
}

/** Дочитывает столбец до конца прокруткой и отвечает, сколько страниц в нём прочитано. */
async function readWholeColumn(page: Page, status: string, total: number): Promise<number> {
  const cards = column(page, status).getByRole('article');
  const pages = Math.ceil(total / COLUMN_PAGE);

  for (let read = 2; read <= pages; read += 1) {
    await column(page, status).evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    await expect(cards).toHaveCount(Math.min(COLUMN_PAGE * read, total));
  }
  await expect(cards).toHaveCount(total);
  return pages;
}

/**
 * Доска под живым потоком.
 *
 * Единственный экран списка, который перечитывает себя сам: переезд карточки между
 * столбцами — это то, ради чего на доску смотрят (UI-72). Сценарии пишущие — двигают
 * задачу и подшивают записи в дела демо-задач, — и потому живут в проекте «запись».
 */
test.describe('доска под живым потоком', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('задача, двинутая на бэкенде, переезжает в свой столбец сама', async ({ page, request }) => {
    test.setTimeout(120_000);
    await fillBacklog(request);
    /*
     * Своя задача — но не обязательно первая в столбце: `last_entry_at` считает только
     * записи агента и человека, а у новой задачи в деле одни служебные. Место в столбце
     * сценарию и не нужно: столбец дочитывается до конца, и карточка в разметке есть
     * при любом порядке.
     */
    const moving = await seedMover(request);
    const backlog = await tasksIn(request, { status: 'backlog' });
    expect(backlog).toContain(moving);

    const calls = watchRequests(page);
    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(column(page, 'backlog').getByRole('article').first()).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
    await fontsReady(page);

    // Столбец дочитывается до конца: обновление перечитывает всё прочитанное, и цена
    // должна быть замерена там, где страниц больше одной.
    const pages = await readWholeColumn(page, 'backlog', backlog.length);
    expect(pages).toBeGreaterThan(1);

    // Возвращаемся к середине столбца: отсюда и меряется, сбило ли обновление чтение.
    await column(page, 'backlog').evaluate((node) => {
      node.scrollTop = 120;
    });
    await settled(() => calls.length);

    const before = {
      calls: calls.length,
      column: await column(page, 'backlog').evaluate((node) => node.scrollTop),
      page: await page.evaluate(() => window.scrollY),
    };

    try {
      const started = Date.now();
      await transition(request, moving, { to: 'open' });

      // Ни одного нажатия: карточка переехала сама.
      await expect(
        column(page, 'open').getByRole('article').filter({ hasText: moving }),
      ).toBeVisible({ timeout: 15_000 });
      const elapsed = Date.now() - started;
      await expect(
        column(page, 'backlog').getByRole('article').filter({ hasText: moving }),
      ).toHaveCount(0);
      test.info().annotations.push({ type: 'переезд', description: `${String(elapsed)} мс` });
      expect(elapsed, 'переезд занял больше окна склейки с большим запасом').toBeLessThan(10_000);

      // Полосы на доске нет ни при каком потоке кадров: предлагать показать то, что
      // уже показано, значит врать про состояние экрана.
      await expect(bar(page)).toBeHidden();

      /*
       * Одно обновление — один заход по всему, что доска читает: страницы раскрытых
       * столбцов (у `backlog` их несколько, и перечитываются все — курсор второй
       * страницы отсчитан от конца первой) плюс числа свёрнутых и число выдачи.
       */
      await settled(() => calls.length);
      const spent = calls.length - before.calls;
      /*
       * Границы, а не одно число: уехавшая карточка укорачивает столбец, и последняя
       * его страница может стать лишней — тогда перечитывание кончается на странице
       * раньше. Обе границы — это **один** заход по доске; десять кадров ушедшей
       * пачки дали бы десятки.
       */
      const after = Math.ceil((backlog.length - 1) / COLUMN_PAGE);
      test.info().annotations.push({ type: 'запросов на кадр', description: String(spent) });
      expect(spent, `запросов на кадр потока (страниц ${String(pages)})`).toBeGreaterThanOrEqual(
        after + 3 + COUNTS,
      );
      expect(spent, `запросов на кадр потока (страниц ${String(pages)})`).toBeLessThanOrEqual(
        pages + 3 + COUNTS,
      );

      // И то, что человек читал, осталось на месте: обновление — это перечитывание
      // выдачи, а не пересборка экрана.
      expect(await column(page, 'backlog').evaluate((node) => node.scrollTop)).toBe(before.column);
      expect(await page.evaluate(() => window.scrollY)).toBe(before.page);
    } finally {
      // Уборка в `finally`: иначе падение проверки оставило бы демо в чужом виде.
      await transition(request, moving, {
        to: 'backlog',
        reason: 'Возврат после сквозной проверки живой доски',
      });
    }
  });

  test('пачка записей стоит доске одного перечитывания, а не десяти', async ({ page, request }) => {
    test.setTimeout(120_000);
    const [target] = await tasksIn(request, { status: 'open', limit: '1' });
    expect(target, 'в демо не нашлось открытой задачи').toBeDefined();

    const calls = watchRequests(page);
    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
    await settled(() => calls.length);

    const before = calls.length;
    const backlogPages = Math.ceil(
      (await column(page, 'backlog').getByRole('article').count()) / COLUMN_PAGE,
    );

    // Десять записей разом — обычный заход агента по задаче. Идут параллельно, чтобы
    // уложиться в одно окно склейки: проверяется склейка, а не скорость `POST`.
    const written = await Promise.all(
      Array.from({ length: 10 }, (_, index) =>
        request.post(`/api/v1/tasks/${target as string}/entries`, {
          headers: auth(),
          data: {
            type: 'attempt',
            title: `Запись пачкой из сквозного теста № ${String(index + 1)}`,
            body: 'Десять записей за секунду обязаны стоить одного перечитывания доски.',
          },
        }),
      ),
    );
    for (const response of written) expect(response.status()).toBe(201);

    await expect.poll(() => calls.length, { timeout: 15_000 }).toBeGreaterThan(before);
    await settled(() => calls.length);

    // Один заход по всему, что читает доска, — а не десять.
    expect(calls.length - before, 'запросов на пачку из десяти кадров').toBe(
      backlogPages + 3 + COUNTS,
    );

    // И покой ничего не читает: окно закрывается один раз, а не заводится само.
    const done = calls.length;
    await page.waitForTimeout(REST);
    expect(calls.length, 'доска продолжает спрашивать в покое').toBe(done);
    await expect(bar(page)).toBeHidden();
  });

  test('после обрыва связи доска догоняет пропущенное сама, без полосы', async ({
    page,
    request,
  }) => {
    // Гашение и подъём бэкенда — минуты, а не секунды.
    test.setTimeout(240_000);
    const moving = await seedMover(request);

    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
    const topbar = page.getByRole('banner');
    await expect(topbar.getByText('на связи')).toBeVisible();
    await expect(column(page, 'open').getByRole('article').filter({ hasText: moving })).toHaveCount(
      0,
    );

    // Рвём связь так, как она рвётся в жизни: бэкенд ушёл (`docs/notes/live.md`).
    compose(['stop', 'api']);
    await expect(topbar.getByText('нет связи')).toBeVisible({ timeout: 60_000 });
    compose(['start', 'api']);

    try {
      // Задачу двигают, пока поток ещё не переподключился: экран о ней не знает.
      await expect
        .poll(
          async () => {
            try {
              const response = await request.post(`/api/v1/tasks/${moving}/transition`, {
                headers: auth(),
                data: { to: 'open' },
                timeout: 5_000,
              });
              return response.status();
            } catch {
              return 0;
            }
          },
          { timeout: 90_000 },
        )
        .toBe(200);

      await expect(topbar.getByText('на связи')).toBeVisible({ timeout: 90_000 });

      // Догнала сама: без нажатия и без полосы, которой на доске нет вовсе.
      await expect(
        column(page, 'open').getByRole('article').filter({ hasText: moving }),
      ).toBeVisible({ timeout: 15_000 });
      await expect(bar(page)).toBeHidden();
    } finally {
      await transition(request, moving, {
        to: 'backlog',
        reason: 'Возврат после сквозной проверки обрыва на доске',
      });
    }
  });

  test('на таблице ключи доски не будят её запросов, а полоса копит как прежде', async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    const [target] = await tasksIn(request, { status: 'open', limit: '1' });

    const calls = watchRequests(page);
    // Сначала доска: её запросы попадают в кэш, и дальше проверяется именно то, что
    // помеченный устаревшим, но не показанный запрос в сеть не идёт.
    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(column(page, 'open').getByRole('article').first()).toBeVisible();
    await settled(() => calls.length);

    await page.getByRole('link', { name: 'Таблица' }).click();
    await expect(page.locator('tbody tr').first()).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
    await settled(() => calls.length);
    const before = calls.length;

    const response = await request.post(`/api/v1/tasks/${target as string}/entries`, {
      headers: auth(),
      data: {
        type: 'note',
        title: 'Запись, ради которой таблица могла бы перестроиться',
        body: 'Таблица обязана остаться при своей полосе, что бы ни делала доска.',
      },
    });
    expect(response.status()).toBe(201);

    // Полоса на месте — и ни одного запроса: ключи доски помечены устаревшими, но её
    // столбцов на экране нет, а табличный запрос ждёт нажатия.
    await expect(bar(page)).toContainText('Изменилась 1 задача');
    await page.waitForTimeout(WINDOW * 3);
    expect(calls.length, 'экран сходил в сеть сам, без просьбы человека').toBe(before);

    await page.getByRole('button', { name: 'Показать' }).click();
    await expect.poll(() => calls.length).toBe(before + 1);
    await expect(bar(page)).toBeHidden();
  });
});
