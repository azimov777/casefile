import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { compose, fontsReady, readE2eToken, side, signedInByHand } from './contour';

const token = readE2eToken();

function rows(page: Page) {
  return page.locator('tbody tr');
}

/** Ключи строк сверху вниз: по ним видно, переставился список или нет. */
async function keys(page: Page): Promise<string[]> {
  return page.getByRole('rowheader').allInnerTexts();
}

/** Верх каждой видимой строки: сдвиг на любой пиксель — это движение под рукой. */
async function tops(page: Page): Promise<number[]> {
  // Первый замер снимается уже подставленным шрифтом, иначе разница «до и после»
  // окажется разницей между системной гарнитурой и Fira, а не движением строк.
  await fontsReady(page);
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('tbody tr')).map((node) =>
      Math.round(node.getBoundingClientRect().top),
    ),
  );
}

async function addEntry(
  request: APIRequestContext,
  key: string,
  body: Record<string, unknown>,
): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
  expect(response.status()).toBe(201);
}

/** Полоса обновлений. По имени, а не по роли: роль `status` носит и индикатор связи. */
const bar = (page: Page) => page.getByRole('status', { name: 'Обновления списка' });

/** Размер страницы таблицы (`entities/task`, `TASK_PAGE_SIZE`): им её запрос и узнаётся. */
const TABLE_PAGE = '50';

function isTableRequest(address: string): boolean {
  const url = new URL(address);
  return url.pathname === '/api/v1/tasks' && url.searchParams.get('limit') === TABLE_PAGE;
}

/** Запросы выдачи со страницы: все или только таблицы. */
function watchListings(page: Page, only: (address: string) => boolean = () => true): string[] {
  const calls: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks?') && only(call.url())) calls.push(call.url());
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

/**
 * Заводит на странице наблюдателя: появлялась ли полоса хоть на одну отрисовку.
 *
 * Отсутствие полосы в конце шага мало что значит: полоса, мелькнувшая на приходе и
 * тут же ушедшая, — то же враньё про экран, только короткое. Смотрятся и вставленные,
 * и снятые узлы: мелькнувшая внутри целиком вставленной страницы к моменту наблюдения
 * из неё уже вынута, а снятым узел бывает, только если побывал в документе.
 */
async function watchBar(page: Page): Promise<void> {
  await page.evaluate(() => {
    const seen = { appeared: false };
    Object.assign(window, { updatesBarSeen: seen });
    new MutationObserver((records) => {
      for (const record of records) {
        const nodes = [...Array.from(record.addedNodes), ...Array.from(record.removedNodes)];
        for (const node of nodes) {
          if (!(node instanceof Element)) continue;
          const found = [node, ...Array.from(node.querySelectorAll('[aria-label]'))];
          if (found.some((element) => element.getAttribute('aria-label') === 'Обновления списка')) {
            seen.appeared = true;
          }
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  });
}

async function barAppeared(page: Page): Promise<boolean> {
  return page.evaluate(
    () => (window as unknown as { updatesBarSeen: { appeared: boolean } }).updatesBarSeen.appeared,
  );
}

/**
 * Считает кадры, дошедшие до страницы, не подменяя поток: ответ настоящего SSE
 * раздваивается (`tee`), одна ветка уходит клиенту как была, по другой считаются кадры.
 *
 * Нужен там, где надо знать, что кадр уже на странице, а видимого следа он не
 * оставляет: пока таблица читается, полоса молчит. Подмена потока целиком (как
 * в `notice.spec.ts`) здесь не годится — проверяется гонка настоящей записи
 * с настоящим ответом.
 */
async function countFrames(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const network = window.fetch.bind(window);
    const counter = { frames: 0 };
    Object.assign(window, { journalFrames: counter });

    window.fetch = async (input, init) => {
      const response = await network(input, init);
      const address =
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (!address.includes('/api/v1/journal/stream') || response.body === null) return response;

      const [client, probe] = response.body.tee();
      void (async () => {
        const reader = probe.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) return;
            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
            const events = buffer.split('\n\n');
            buffer = events.pop() ?? '';
            counter.frames += events.filter((event) =>
              event.split('\n').some((line) => line.startsWith('data:')),
            ).length;
          }
        } catch {
          // Поток оборван клиентом (уход со страницы, переподключение): считать нечего.
        }
      })();

      return new Response(client, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    };
  });
}

async function framesSeen(page: Page): Promise<number> {
  return page.evaluate(
    () => (window as unknown as { journalFrames: { frames: number } }).journalFrames.frames,
  );
}

/**
 * Задачи очереди `DEMO` в порядке таблицы по умолчанию — «свежие в деле сверху», —
 * по правде бэкенда. Последняя на первой странице — та, чей подъём наверх виден
 * сразу: запись выносит её с конца страницы в начало.
 */
async function tableOrder(request: APIRequestContext): Promise<string[]> {
  const response = await request.get(
    `/api/v1/tasks?queue=DEMO&fields=status&limit=${TABLE_PAGE}&sort=-last_entry_at`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(response.status()).toBe(200);
  return ((await response.json()) as { data: { key: string }[] }).data.map((row) => row.key);
}

/**
 * Живой поток на списке: он знает, что выдача устарела, но не перестраивает её сам.
 *
 * Сценарии пишущие — записи подшиваются в дела демо-задач, — и потому живут в проекте
 * «запись» (`playwright.config.ts`).
 */
test.describe('список под живым потоком', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('запись в чужой задаче не переставляет строки, а предлагает показать новое', async ({
    page,
    request,
  }) => {
    await page.goto('/tasks?queue=DEMO');
    await expect(rows(page).first()).toBeVisible();

    const before = { keys: await keys(page), tops: await tops(page) };

    // Задача из конца списка: при порядке «сначала живые в деле» запись выносит её
    // наверх — то есть ровно переставляет то, что человек читает.
    const last = before.keys.at(-1) as string;
    await addEntry(request, last, {
      type: 'note',
      title: 'Запись, ради которой список мог бы перестроиться',
    });

    await expect(bar(page)).toContainText('Изменилась 1 задача');

    // Ничего не сдвинулось и не переставилось: полоса стоит вне потока вёрстки.
    expect(await keys(page)).toEqual(before.keys);
    expect(await tops(page)).toEqual(before.tops);

    // Вторая половина: человек попросил — список пришёл в новый порядок.
    await page.getByRole('button', { name: 'Показать' }).click();

    await expect.poll(async () => (await keys(page))[0]).toBe(last);
    await expect(bar(page)).toBeHidden();
  });

  test('правка приоритета мимо дела доходит до той же полосы', async ({ page, request }) => {
    // Задача в незакрытом статусе: у `done` и `cancelled` не меняется ничего
    // (`409 task_closed`), а какая из демо-задач сейчас открыта — знает бэкенд.
    const listed = await request.get(
      '/api/v1/tasks?queue=DEMO&status=open&fields=priority&limit=1&sort=key',
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(listed.status()).toBe(200);
    const target = ((await listed.json()) as { data: { key: string; priority: string }[] }).data[0];
    expect(target).toBeDefined();
    const key = (target as { key: string }).key;
    const was = (target as { priority: string }).priority === 'critical' ? 'high' : 'critical';

    await page.goto('/tasks?queue=DEMO&status=open&sort=key');
    await expect(rows(page).first()).toBeVisible();

    const row = page
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: key, exact: true }) });

    // Приоритет в дело не подшивается записью агента — с TRK-7 он приходит отдельным
    // родом события (`field_changed`). Провалиться мимо полосы оно не вправе.
    const patched = await request.patch(`/api/v1/tasks/${key}`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { priority: was },
    });
    expect(patched.status()).toBe(200);

    await expect(bar(page)).toContainText('Изменилась 1 задача');
    await page.getByRole('button', { name: 'Показать' }).click();

    await expect(row).toContainText(was);
    await expect(bar(page)).toBeHidden();
  });

  test('возврат из фона не выливает накопленное на экран', async ({ page, request }) => {
    await page.goto('/tasks?queue=DEMO');
    await expect(rows(page).first()).toBeVisible();
    const before = { keys: await keys(page), tops: await tops(page) };

    // Вкладка ушла в фон: браузер Playwright её не прячет, поэтому скрытость
    // объявляется странице так же, как это делает браузер.
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await addEntry(request, before.keys.at(-1) as string, {
      type: 'note',
      title: 'Запись, пришедшая в фоновую вкладку',
    });

    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Человек вернулся в ту же точку, где был: строки на месте, накопленное — в полосе.
    await expect(bar(page)).toContainText('Изменилась 1 задача');
    expect(await keys(page)).toEqual(before.keys);
    expect(await tops(page)).toEqual(before.tops);
  });

  test('новая запись на открытой карточке появляется сама, не сбивая прокрутку', async ({
    page,
    request,
  }) => {
    await page.goto('/tasks/DEMO-3');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-3');
    // Прокрутка снимается уже подставленным шрифтом: Fira приходит с внешнего хоста
    // и меняет высоту документа, а вместе с ней и то, докуда страница прокрутилась.
    await fontsReady(page);

    await page.evaluate(() => window.scrollTo(0, 200));
    const scrolled = await page.evaluate(() => window.scrollY);

    await addEntry(request, 'DEMO-3', {
      type: 'note',
      title: 'Запись, которую человек ждёт на открытой карточке',
    });

    // Тут человек смотрит именно на эту задачу и ждёт свежего: полосы нет, запись
    // приходит сама — но прокрутка от неё не съезжает.
    await expect(
      page
        .getByRole('row')
        .filter({ hasText: 'Запись, которую человек ждёт на открытой карточке' }),
    ).toBeVisible();
    await expect(bar(page)).toBeHidden();
    expect(await page.evaluate(() => window.scrollY)).toBe(scrolled);
  });

  /*
   * Таблица на прибытии (UI-95): полоса считает изменения с последнего чтения таблицы,
   * а не с последнего нажатия. Таблица перечитывается и мимо полосы — на приходе
   * с доски и из карточки, — и полоса над только что прочитанными строками предлагала
   * бы показать то, что уже показано.
   */
  test('доска, запись, переход в таблицу: полосы нет, а запрос таблицы один', async ({
    page,
    request,
  }) => {
    const listings = watchListings(page);
    const tableCalls = watchListings(page, isTableRequest);
    const target = (await tableOrder(request)).at(-1) as string;

    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(
      page.getByRole('region', { name: 'open' }).getByRole('article').first(),
    ).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
    await settled(() => listings.length);
    const before = listings.length;

    await addEntry(request, target, {
      type: 'note',
      title: 'Запись, сделанная при открытой доске',
    });

    // Доска догнала запись сама — значит, кадр дошёл до страницы. Таблица при этом
    // не спрошена ни разу: её запрос на доске выключен.
    await expect.poll(() => listings.length, { timeout: 10_000 }).toBeGreaterThan(before);
    await settled(() => listings.length);
    expect(tableCalls).toEqual([]);

    await watchBar(page);
    await page.getByRole('link', { name: 'Таблица' }).click();

    // Одно чтение на прибытие — и в нём уже есть запись: задача поднялась наверх.
    await expect.poll(async () => (await keys(page))[0]).toBe(target);
    await settled(() => tableCalls.length);
    expect(tableCalls).toHaveLength(1);

    // Полоса не показалась ни на одну отрисовку: предлагать ей нечего.
    expect(await barAppeared(page)).toBe(false);
    await expect(bar(page)).toBeHidden();

    // А запись после прихода полоса предлагает, как прежде, — без единого запроса.
    await addEntry(request, target, {
      type: 'note',
      title: 'Запись, сделанная уже при открытой таблице',
    });
    await expect(bar(page)).toContainText('Изменилась 1 задача');
    await settled(() => tableCalls.length);
    expect(tableCalls).toHaveLength(1);
  });

  test('возврат из карточки в таблицу после записи: полосы нет, а запрос таблицы один', async ({
    page,
    request,
  }) => {
    const tableCalls = watchListings(page, isTableRequest);

    await page.goto('/tasks?queue=DEMO');
    await expect(rows(page).first()).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

    // Задача с конца страницы: запись вынесет её наверх, и по этому видно, что чтение
    // на возврате её уже принесло.
    const target = (await keys(page)).at(-1) as string;
    await rows(page).last().getByRole('link').click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(target);

    const title = 'Запись, сделанная, пока человек читал карточку';
    await addEntry(request, target, { type: 'note', title });
    // Карточка обновилась сама — кадр дошёл до страницы.
    await expect(page.getByRole('row').filter({ hasText: title })).toBeVisible();
    await settled(() => tableCalls.length);
    const before = tableCalls.length;

    await watchBar(page);
    await page.getByRole('link', { name: '← К списку с отбором' }).click();

    await expect.poll(async () => (await keys(page))[0]).toBe(target);
    await settled(() => tableCalls.length);
    expect(tableCalls).toHaveLength(before + 1);
    expect(await barAppeared(page)).toBe(false);
    await expect(bar(page)).toBeHidden();
  });

  test('запись, пришедшая, пока запрос таблицы в пути, остаётся в полосе', async ({
    page,
    request,
  }) => {
    await countFrames(page);
    const tableCalls = watchListings(page, isTableRequest);
    const target = (await tableOrder(request)).at(-1) as string;

    await page.goto('/tasks?queue=DEMO&view=board');
    await expect(
      page.getByRole('region', { name: 'open' }).getByRole('article').first(),
    ).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

    // Сервер отвечает таблице сразу, а до страницы ответ доезжает, когда скажет
    // сценарий: так выглядит запрос, который прочитал выдачу раньше, чем агент подшил
    // запись, но вернулся позже, чем её кадр.
    let release!: () => void;
    const gate = new Promise<void>((done) => {
      release = done;
    });
    let answered!: () => void;
    const snapshot = new Promise<void>((done) => {
      answered = done;
    });
    await page.route(
      (url) => isTableRequest(url.href),
      async (route) => {
        const response = await route.fetch();
        answered();
        await gate;
        await route.fulfill({ response });
      },
    );

    await page.getByRole('link', { name: 'Таблица' }).click();
    await snapshot;

    const frames = await framesSeen(page);
    await addEntry(request, target, {
      type: 'note',
      title: 'Запись, подшитая, пока ответ таблицы в пути',
    });
    await expect.poll(() => framesSeen(page), { timeout: 10_000 }).toBeGreaterThan(frames);

    // Пока таблица читается, полоса молчит: строки вот-вот придут.
    await expect(bar(page)).toBeHidden();

    release();
    await expect(rows(page).first()).toBeVisible();

    // Ответ снят до записи: задача ещё внизу, и полоса говорит именно о ней.
    expect((await keys(page))[0]).not.toBe(target);
    await expect(bar(page)).toContainText('Изменилась 1 задача');
    expect(tableCalls).toHaveLength(1);

    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await page.getByRole('button', { name: 'Показать' }).click();
    await expect.poll(async () => (await keys(page))[0]).toBe(target);
    await expect(bar(page)).toBeHidden();
    expect(tableCalls).toHaveLength(2);
  });

  test('после обрыва связи список ждёт просьбы, а не переставляется сам', async ({
    page,
    request,
  }) => {
    // Гашение и подъём бэкенда — минуты, а не секунды.
    test.setTimeout(240_000);

    await page.goto('/tasks?queue=DEMO');
    await expect(rows(page).first()).toBeVisible();
    const before = { keys: await keys(page), tops: await tops(page) };

    const topbar = page.getByRole('banner');
    // Рвём связь так, как она рвётся в жизни: бэкенд ушёл (см. `live.spec.ts`).
    compose(['stop', 'api']);
    await expect(topbar.getByText('нет связи')).toBeVisible({ timeout: 60_000 });

    compose(['start', 'api']);
    await expect
      .poll(
        async () => {
          try {
            const response = await request.post(
              `/api/v1/tasks/${before.keys.at(-1) as string}/entries`,
              {
                headers: { Authorization: `Bearer ${token}` },
                data: { type: 'note', title: 'Запись, сделанная во время обрыва' },
                timeout: 5_000,
              },
            );
            return response.status();
          } catch {
            return 0;
          }
        },
        { timeout: 90_000 },
      )
      .toBe(201);

    await expect(topbar.getByText('на связи')).toBeVisible({ timeout: 90_000 });

    // Обрыв случается тогда, когда человек ничего не делал: переставлять список под
    // ним особенно нечестно. Полоса при этом обязана появиться.
    await expect(bar(page)).toBeVisible();
    expect(await keys(page)).toEqual(before.keys);
    expect(await tops(page)).toEqual(before.tops);
  });
});

/**
 * Порог показа боковой панели (`--breakpoint-fold` в `shared/styles/theme.css`,
 * 44rem = 704 px). Полоса, приклеенная к краю окна, до UI-98 закрывала подвал панели
 * ровно там, где панель показана, — а на ширине сразу выше порога самой панели уже
 * досталось место, и его меньше всего для всех остальных.
 */
const FOLD = 704;

/** Числовой прямоугольник, как его отдаёт `boundingBox()`. */
interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Есть ли у прямоугольников общая точка по обеим осям. */
function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

async function rectOf(locator: Locator, label: string): Promise<Rect> {
  const box = await locator.boundingBox();
  if (box === null) throw new Error(`нет прямоугольника: ${label}`);
  return box;
}

/**
 * Полоса обновлений стоит `fixed` в углу экрана. До UI-98 она держалась левого края
 * окна и на ширине, где показана боковая панель, ложилась на её подвал — участника
 * и, у установки со входом руками, кнопку «Выйти». Проверяется на 1440×900 (обычный
 * широкий экран) и на ширине сразу выше порога показа панели, где места меньше всего.
 *
 * Установка со входом руками (`signedInByHand`): у локальной установки кнопки
 * «Выйти» нет вовсе (`fromInstall`), а вторая часть проверки — как раз про неё.
 */
test.describe('полоса обновлений не закрывает подвал панели (UI-98)', () => {
  for (const width of [FOLD + 1, 1440]) {
    test(`на ${width} px подвал панели виден и нажимается целиком`, async ({ page, request }) => {
      await signedInByHand(page);
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/tasks?queue=DEMO');
      await expect(rows(page).first()).toBeVisible();

      const name = side(page).getByText('owner');
      const signOut = side(page).getByRole('button', { name: 'Выйти' });
      await expect(name).toBeVisible();
      await expect(signOut).toBeVisible();

      const target = (await keys(page)).at(-1) as string;
      await addEntry(request, target, {
        type: 'note',
        title: `Запись для геометрии полосы на ${width} px`,
      });
      await expect(bar(page)).toContainText('Изменилась 1 задача');

      // Метрика снимается уже подставленным шрифтом: он меняет ширины и точки
      // переноса и у полосы, и у подвала панели.
      await fontsReady(page);

      const barBox = await rectOf(bar(page), 'полоса обновлений');
      const nameBox = await rectOf(name, 'имя участника');
      const signOutBox = await rectOf(signOut, 'кнопка «Выйти»');

      expect(
        overlaps(barBox, nameBox),
        `${width} px: полоса ${JSON.stringify(barBox)} и имя ${JSON.stringify(nameBox)}`,
      ).toBe(false);
      expect(
        overlaps(barBox, signOutBox),
        `${width} px: полоса ${JSON.stringify(barBox)} и «Выйти» ${JSON.stringify(signOutBox)}`,
      ).toBe(false);

      // Проверка 2: кнопка достижима табом, пока полоса видна, — числом шагов до
      // совпадения, а не фиксированным счётом (порядок пунктов панели может измениться).
      for (
        let step = 0;
        step < 20 && !(await signOut.evaluate((node) => node === document.activeElement));
        step += 1
      ) {
        await page.keyboard.press('Tab');
      }
      await expect(signOut).toBeFocused();
      await expect(bar(page)).toBeVisible();

      // И нажимается мышью без `force`: без этого флага клик Playwright отказал бы
      // сам, наткнувшись на полосу, если бы та и вправду перекрывала кнопку.
      await signOut.click();
      await expect(page).toHaveURL(/\/login/);
    });
  }
});
