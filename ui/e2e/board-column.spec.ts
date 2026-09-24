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
  const query = new URLSearchParams({ project: 'DEMO', fields: 'status', limit: '1', ...params });
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
        project: 'DEMO',
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

  await page.goto('/tasks?project=DEMO&view=board');
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
  await page.goto(`/tasks?project=DEMO&view=board&collapsed=${LONG}`);
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

/**
 * Слово, которое браузер не переносит нигде, — путь к файлу этого же репозитория.
 *
 * Дефис перенос разрешает, косая черта, точка и подчёркивание — нет (замерено:
 * `scrollable-region-focusable` даёт пол ширины 66,8 px, а `tests/test_agent_token.py`
 * — 161,3 px). Поэтому слово выбрано без дефисов и выписано целиком, а не собрано из
 * кусков: сценарий проверяет ровно эту длину, и укоротившееся слово молча перестало бы
 * проверять что-либо. Название с путём — не выдумка теста: ими полны дела этого трекера,
 * и именно такое слово задаёт `min-content` карточки, а через него — ширину, которую
 * требует содержимое столбца (UI-115).
 */
const UNBREAKABLE = 'src/shared/i18n/dictionaries/ru/tasks.ts';

/** Исполнитель, по которому отбирается ровно одна заведённая здесь задача. */
const PROBE = 'ui115_probe';

/** Запас прокрутки вбок у столбцов и у ряда: точный, дробный — такой же, как у браузера. */
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
        over: node.scrollWidth - node.clientWidth,
        room: room(node),
        clientWidth: node.clientWidth,
      })),
      row: { over: lane.scrollWidth - lane.clientWidth, room: room(lane) },
    };
  });
}

test('длинное непереносимое слово в названии не разводит столбец вбок', async ({
  page,
  request,
}) => {
  /*
   * Задача с путём в названии и своим исполнителем: по нему отбирается ровно она,
   * и столбец `backlog` в этом отборе состоит из одной карточки — той, чьё название
   * и проверяется. Без отбора она уехала бы на третью страницу столбца: порядок
   * списка — по ключу по возрастанию, а заведённых соседями задач в демо к этому
   * времени десятки.
   */
  const created = await request.post('/api/v1/tasks', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      project: 'DEMO',
      title: `Подпись рамки таблицы живёт в ${UNBREAKABLE}`,
      description: 'Заведена сквозным тестом: в названии путь, который нигде не переносится.',
      assignee: PROBE,
    },
  });
  expect(created.status()).toBe(201);

  await silenceJournal(page);

  /*
   * Ниже точки остановки, на ней и шире. Ширина окна ширины столбца не меняет — она
   * задана `--ui-board-column`, — но меняет ветку: с `fold` у столбца `overflow-y: auto`,
   * а рядом с ним и вторая ось вычисляется в `auto`, то есть переполнение вправо
   * становится полосой прокрутки. Ниже `fold` полосы не будет и при переполнении —
   * там содержимое просто вылезет на соседа, что не лучше.
   */
  for (const width of [640, 704, 1024]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/tasks?project=DEMO&view=board&assignee=${PROBE}&collapsed=`);
    await expect(column(page, LONG).getByRole('article')).toHaveCount(1);
    await expect(column(page, LONG).getByRole('article').first()).toContainText(UNBREAKABLE);
    await fontsReady(page);

    const measured = await lanes(page);
    const report = `на ${width}px ${JSON.stringify(measured)}`;
    for (const seen of measured.columns) {
      expect(seen.over, report).toBeLessThanOrEqual(0);
      expect(seen.room, report).toBe(0);
    }
    // Прокрутка ряда вбок при этом цела: шесть столбцов не влезают ни в одну ширину.
    expect(measured.row.room, report).toBeGreaterThan(0);
  }
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
  await page.goto('/tasks?project=DEMO&view=board&assignee=никого-с-таким-именем-нет');
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
  await page.goto('/tasks?project=DEMO&view=board');
  await expect(column(page, 'waiting').getByRole('article').first()).toBeVisible();
  await expect.poll(() => calls.length).toBeGreaterThan(0);

  const onShort = calls.length;
  await page.waitForTimeout(REST);
  expect(calls.length, 'короткий столбец продолжает спрашивать').toBe(onShort);
});
