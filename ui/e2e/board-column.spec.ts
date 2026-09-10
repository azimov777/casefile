import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/**
 * Столько карточек читает столбец доски за раз (`entities/task`,
 * `TASK_COLUMN_PAGE_SIZE`). Число здесь выписано, потому что сценарий проверяет
 * именно его: страница, разошедшаяся с этой строкой, обязана уронить прогон.
 */
const COLUMN_PAGE = 10;

/** Столбец, на котором меряется дочитывание: новые задачи рождаются в `backlog`. */
const LONG = 'backlog';

/** Сколько ждать в покое, чтобы поймать цикл запросов, которого быть не должно. */
const REST = 10_000;

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

/** Сколько задач в отборе — по правде бэкенда: `meta.total` считает всю выдачу. */
async function countTasks(request: APIRequestContext, params: Record<string, string> = {}) {
  const query = new URLSearchParams({ queue: 'DEMO', fields: 'status', limit: '1', ...params });
  const response = await request.get(`/api/v1/tasks?${query.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { meta: { total: number | null } };
  expect(body.meta.total, 'список задач обязан считать общее число выдачи').not.toBeNull();
  return body.meta.total as number;
}

/** Заводит столько задач, чтобы столбец не поместился в две страницы. */
async function fillColumn(request: APIRequestContext): Promise<number> {
  const before = await countTasks(request, { status: LONG });
  const needed = COLUMN_PAGE * 2 + 3 - before;

  const created = Array.from({ length: Math.max(needed, 0) }, (_, index) =>
    request.post('/api/v1/tasks', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        queue: 'DEMO',
        title: `Задача для проверки дочитывания столбца № ${index + 1}`,
        description: 'Заведена сквозным тестом, чтобы столбец доски не влез в одну страницу.',
      },
    }),
  );
  for (const response of await Promise.all(created)) {
    expect(response.status()).toBe(201);
  }

  return countTasks(request, { status: LONG });
}

/** Запросы к списку задач, снятые с этой страницы. */
function watchRequests(page: Page): string[] {
  const calls: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks?')) calls.push(call.url());
  });
  return calls;
}

test('столбец дочитывается прокруткой, а не нажатием', async ({ page, request }) => {
  test.setTimeout(180_000);
  const total = await fillColumn(request);
  expect(total).toBeGreaterThan(COLUMN_PAGE * 2);

  // Живой поток на время замера молчит: он перечитывает показанное по кадрам журнала
  // и превратил бы счёт запросов в источник случайных чисел.
  await silenceJournal(page);
  const calls = watchRequests(page);

  await page.goto('/tasks?queue=DEMO&view=board');
  const cards = column(page, LONG).getByRole('article');
  await expect(cards.first()).toBeVisible();
  await fontsReady(page);

  /*
   * Сразу после отрисовки в разметке ровно страница, а не вся выдача: ради этого
   * задача и делалась. Число в заголовке при этом полное — его считает бэкенд.
   */
  await expect(cards).toHaveCount(COLUMN_PAGE);
  await expect(column(page, LONG).getByRole('button')).toContainText(String(total));

  // Кнопки «Ещё» под доской больше нет: способ дочитать столбец остался один.
  await expect(page.getByRole('button', { name: 'Ещё' })).toHaveCount(0);

  const pages = Math.ceil(total / COLUMN_PAGE);
  for (let page_ = 2; page_ <= pages; page_ += 1) {
    // Докручиваем столбец до конца — и ничего не нажимаем.
    await column(page, LONG).evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    await expect(cards).toHaveCount(Math.min(COLUMN_PAGE * page_, total));
  }

  // Дочитан весь столбец, и запросов на это ушло ровно столько, сколько в нём страниц.
  await expect(cards).toHaveCount(total);
  const asked = calls.filter((url) => new URL(url).searchParams.getAll('status').includes(LONG));
  expect(asked, `страниц ${pages}, запросов столбца`).toHaveLength(pages);

  /*
   * Последняя страница прочитана — сторож снят. Десять секунд покоя на дочитанном
   * столбце: если наблюдатель остался бы висеть на видимом стороже, здесь набежала бы
   * череда запросов, и цикл был бы виден числом, а не догадкой.
   */
  const settled = calls.length;
  await page.waitForTimeout(REST);
  expect(calls.length, 'дочитанный столбец продолжает спрашивать').toBe(settled);
});

test('раскрытие свёрнутого столбца читает одну страницу, а не сколько успеет', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const total = await fillColumn(request);
  await silenceJournal(page);
  const calls = watchRequests(page);

  // Тот же длинный столбец, но свёрнутый: раскрытие едет движением, и сторож конца
  // на это время оказывается внутри обрезанного места.
  await page.goto(`/tasks?queue=DEMO&view=board&collapsed=${LONG}`);
  const toggle = column(page, LONG).getByRole('button');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toContainText(String(total));
  await fontsReady(page);

  await toggle.click();
  const cards = column(page, LONG).getByRole('article');
  await expect(cards.first()).toBeVisible();

  /*
   * Ждём заведомо дольше движения и считаем ровно один раз, без повторов: проверка
   * с ожиданием прошла бы и на кадре, где страница ещё одна, а через мгновение их
   * три. Так и было: сторож нулевой высоты считался видимым внутри обрезанного
   * места, и раскрытие вычитывало страницу за страницей, пока едет раскрытие.
   */
  await page.waitForTimeout(1500);
  expect(await cards.count(), 'раскрытие вычитало больше страницы').toBe(COLUMN_PAGE);
  const asked = calls.filter((url) => new URL(url).searchParams.getAll('status').includes(LONG));
  expect(asked, 'запросов столбца на раскрытие').toHaveLength(2);
});

test('в покое доска не спрашивает ничего: ни пустой столбец, ни короткий', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await silenceJournal(page);
  const calls = watchRequests(page);

  /*
   * Отбор, под который не подходит ни одна задача: все шесть столбцов пусты, и
   * сторож в каждом из них виден с первого кадра. Наблюдатель, не спрашивающий
   * «а есть ли что дочитывать», крутился бы здесь вечно.
   */
  await page.goto('/tasks?queue=DEMO&view=board&assignee=никого-с-таким-именем-нет');
  await expect(column(page, 'open')).toBeVisible();
  await expect(column(page, 'open').getByRole('article')).toHaveCount(0);
  await expect.poll(() => calls.length).toBeGreaterThan(0);

  const onEmpty = calls.length;
  await page.waitForTimeout(REST);
  expect(calls.length, 'пустой столбец продолжает спрашивать').toBe(onEmpty);

  // Столбец короче экрана: карточки есть, но дочитывать нечего — сторожа над ним нет.
  const short = await countTasks(request, { status: 'waiting' });
  expect(short, 'в демо не осталось короткого столбца').toBeLessThan(COLUMN_PAGE);

  calls.length = 0;
  await page.goto('/tasks?queue=DEMO&view=board');
  await expect(column(page, 'waiting').getByRole('article').first()).toBeVisible();
  await expect.poll(() => calls.length).toBeGreaterThan(0);

  const onShort = calls.length;
  await page.waitForTimeout(REST);
  expect(calls.length, 'короткий столбец продолжает спрашивать').toBe(onShort);
});
