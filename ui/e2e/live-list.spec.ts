import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
  compose,
  curve,
  fontsReady,
  ms,
  readE2eToken,
  shellReady,
  side,
  signedInByHand,
} from './contour';

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
    // Своя ссылка строки — на названии (`data-link="task"`, `task-row.tsx`). У задачи
    // с родителем (UI-119) за ней стоит вторая, в родителя: без уточнения `getByRole`
    // видит обе и падает `strict mode violation`, если последней строкой оказывается
    // как раз такая задача (UI-136).
    await rows(page).last().locator('a[data-link="task"]').click();
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

/** Стопка уведомлений о вопросах ко мне: живёт в оболочке, у правого края. */
const stack = (page: Page) => page.getByRole('complementary', { name: 'Вопросы ко мне' });

/**
 * Предел ширины плавающего слоя на этой ширине окна — `--ui-float-max`
 * в `shared/styles/theme.css`: 26rem, но не шире окна без полей в 3rem.
 */
function floatMax(width: number): number {
  return Math.min(416, width - 48);
}

/**
 * Заголовок заведомо длиннее строки: карточка уведомления — текст с переносом, и такой
 * вопрос растягивает её до предела ширины. Замер обязан идти на предельной карточке —
 * короткий заголовок дал бы узкую, и пересечение спряталось бы за ним.
 */
const LONG_QUESTION =
  'Какой адрес брать для ленты событий: основной или резервный, если основной недоступен ' +
  'дольше минуты, а резервный отвечает с задержкой в несколько секунд?';

/**
 * Вопрос владельцу, заданный по-настоящему, через API, и уборка за ним ответом — иначе
 * он остался бы во входящей, и соседний пишущий сценарий видел бы не то, что ожидал.
 * Образец — `askOwner` в `answer.spec.ts`.
 */
async function askOwner(
  request: APIRequestContext,
  key: string,
  title: string,
): Promise<{ cleanup: () => Promise<void> }> {
  const asked = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      type: 'question',
      title,
      body: 'Тело вопроса, на состав которого замер не опирается.',
      payload: { addressees: ['owner'], blocking: false },
    },
  });
  expect(asked.status()).toBe(201);
  const no = ((await asked.json()) as { data: { no: number } }).data.no;

  return {
    cleanup: async () => {
      const closed = await request.post(`/api/v1/tasks/${key}/entries`, {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          type: 'answer',
          body: 'Закрыт сквозным тестом, чтобы входящая осталась какой была.',
          payload: { question_no: no },
        },
      });
      expect(closed.status()).toBe(201);
    },
  };
}

/** Прямоугольник целыми пикселями — для отчёта прогона, а не для сравнения. */
function rounded({ x, y, width, height }: Rect): Record<string, number> {
  return {
    left: Math.round(x),
    right: Math.round(x + width),
    top: Math.round(y),
    bottom: Math.round(y + height),
  };
}

/** Числа в отчёт прогона: вердикт по замеру называет их, а не «прошло». */
function report(type: string, numbers: unknown): void {
  const description = JSON.stringify(numbers);
  test.info().annotations.push({ type, description });
  console.log(`[${type}] ${description}`);
}

/**
 * Одно событие даёт оба плавающих слоя разом: вопрос владельцу — это и карточка
 * в стопке, и запись в деле задачи, то есть «Изменилась 1 задача» в полосе. Рядом
 * они помещаются не везде: на `fold` панель, полоса и карточка предельной ширины
 * вместе с полями шире окна (`UI-98#13`). Сценарий проверяет, что на любой ширине, где
 * показана панель, полоса не уходит ни под её подвал, ни под карточку, и «Показать»
 * нажимается, пока уведомление видно. Ширины — сразу выше порога, обычный узкий
 * ноутбук, место, где полоса и карточка ещё не помещаются рядом, и широкий экран.
 */
test.describe('полоса обновлений не спорит за место со стопкой уведомлений (UI-98#13)', () => {
  for (const width of [FOLD + 1, 768, 900, 1440]) {
    test(`на ${width} px полоса не уходит ни под подвал панели, ни под уведомление`, async ({
      page,
      request,
    }) => {
      await signedInByHand(page);
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/tasks?queue=DEMO');
      await expect(rows(page).first()).toBeVisible();
      await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
      // Кадр с вопросом, обогнавший участника, уведомления не даст: «спросили ли меня»
      // сверяется с именем из `bootstrap`.
      await shellReady(page);

      const name = side(page).getByText('owner');
      const signOut = side(page).getByRole('button', { name: 'Выйти' });
      await expect(signOut).toBeVisible();

      const question = await askOwner(request, 'DEMO-3', LONG_QUESTION);
      try {
        const card = stack(page).locator('article').filter({ hasText: LONG_QUESTION });
        await expect(card).toBeVisible();
        await expect(bar(page)).toContainText('Изменилась 1 задача');

        // Замер в покое: шрифт подставлен, приход карточки доехал (`docs/notes/ui.md`,
        // «Замер геометрии снимается после `document.fonts.ready`»).
        await fontsReady(page);
        await stack(page).evaluate((node) =>
          Promise.all(node.getAnimations({ subtree: true }).map((motion) => motion.finished)),
        );

        const boxes = {
          bar: await rectOf(bar(page), 'полоса обновлений'),
          card: await rectOf(card, 'карточка вопроса'),
          name: await rectOf(name, 'имя участника'),
          signOut: await rectOf(signOut, 'кнопка «Выйти»'),
        };
        report(`UI-98#13 ${width}px`, {
          bar: rounded(boxes.bar),
          card: rounded(boxes.card),
          name: rounded(boxes.name),
          signOut: rounded(boxes.signOut),
        });
        const numbers = `${width} px: ${JSON.stringify(boxes)}`;

        // Карточка на пределе ширины: иначе замер проверял бы не худший случай.
        expect(boxes.card.width, numbers).toBeGreaterThanOrEqual(floatMax(width) - 1);

        expect(overlaps(boxes.bar, boxes.card), `полоса и карточка, ${numbers}`).toBe(false);
        expect(overlaps(boxes.bar, boxes.name), `полоса и имя, ${numbers}`).toBe(false);
        expect(overlaps(boxes.bar, boxes.signOut), `полоса и «Выйти», ${numbers}`).toBe(false);
        expect(overlaps(boxes.card, boxes.name), `карточка и имя, ${numbers}`).toBe(false);
        expect(overlaps(boxes.card, boxes.signOut), `карточка и «Выйти», ${numbers}`).toBe(false);

        // «Показать» нажимается мышью без `force`, пока уведомление на экране: клик
        // Playwright сам отказал бы, окажись под курсором карточка, а не кнопка.
        await bar(page).getByRole('button', { name: 'Показать' }).click();
        await expect(bar(page)).toBeHidden();
        await expect(card).toBeVisible();
      } finally {
        await question.cleanup();
      }
    });
  }
});

/**
 * Место полосы в низу области содержания: открывается, когда полоса приходит, и
 * закрывается, когда уходит (`updates-bar.tsx`, `data-bar="place"`).
 */
const barPlace = (page: Page) => page.locator('[data-bar="place"]');

/**
 * Ждёт покоя всего, что на странице движется: карточки в стопке, её места и места
 * полосы. Места полосы в стопке нет — она соседка стопки по низу области содержания, —
 * поэтому ожидание по поддереву стопки его бы не дождалось.
 *
 * Перебитое движение — тоже покой: `finished` у него отклоняется `AbortError`, и без
 * `catch` ожидание падало бы на том, что движение сменили (UI-102).
 */
async function motionsSettled(page: Page): Promise<void> {
  await page.evaluate(() =>
    Promise.all(document.getAnimations().map((motion) => motion.finished.catch(() => undefined))),
  );
}

/** Токены словаря движения, какими их отдаёт живой документ. */
async function motionTokens(page: Page) {
  return page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return {
      fast: root.getPropertyValue('--motion-fast'),
      slow: root.getPropertyValue('--motion-slow'),
      enter: root.getPropertyValue('--ease-fast'),
      exit: root.getPropertyValue('--ease-exit'),
    };
  });
}

/** Кадр низа области содержания: где карточка вопроса и что с полосой. */
interface DockFrame {
  /** Миллисекунды от начала наблюдения. */
  at: number;
  left: number;
  top: number;
  width: number;
  height: number;
  /** Высота места полосы; `null` — места в разметке нет. */
  place: number | null;
  /** Прямоугольник самой полосы (лево, верх, право, низ); `null` — полосы в разметке нет. */
  bar: number[] | null;
  /** Полоса скрыта (`visibility: hidden`); `null` — полосы в разметке нет. */
  hidden: boolean | null;
  /** Полоса инертна; `null` — полосы в разметке нет. */
  inert: boolean | null;
  /** Под серединой «Показать» — полоса; `null` — точку не снимали. */
  hit: boolean | null;
}

/** Движение места полосы в первом кадре, где место есть. */
interface PlaceMotion {
  running: boolean;
  property: string;
  duration: string;
  easing: string;
}

interface DockMotion {
  before: DockFrame;
  frames: DockFrame[];
  place: PlaceMotion | null;
  done: boolean;
  timedOut: boolean;
}

/**
 * Снимает положение карточки вопроса и места полосы по кадрам — изнутри браузера:
 * снаружи 120 мс выхода кончаются раньше первого замера (`docs/notes/ui.md`, «Кадр
 * движения не поймать снаружи»).
 *
 * Приход (`leave: false`): наблюдение ставится до записи, от которой полоса придёт,
 * и кончается, когда место полосы доехало и три кадра простояло. Уход (`leave: true`):
 * «Показать» нажимает сам браузер сразу после первого замера, наблюдение кончается,
 * когда место снято и три кадра его нет. Итог лежит в `window.dockMotion`.
 */
async function watchDock(page: Page, question: string, leave: boolean): Promise<void> {
  await page.evaluate(
    ({ question: title, leave: leaving }) => {
      const card = Array.from(
        document.querySelectorAll<HTMLElement>('[aria-label="Вопросы ко мне"] article'),
      ).find((node) => node.textContent?.includes(title) === true);
      if (card === undefined) throw new Error('карточки вопроса на странице нет');

      const barOf = () => document.querySelector<HTMLElement>('[data-bar="place"] [role="status"]');
      const button = leaving ? (barOf()?.querySelector('button') ?? null) : null;
      if (leaving && button === null) throw new Error('кнопки «Показать» на странице нет');
      const target = button?.getBoundingClientRect();
      const aim =
        target === undefined
          ? null
          : { x: target.left + target.width / 2, y: target.top + target.height / 2 };

      const started = performance.now();
      const sample = () => {
        const box = card.getBoundingClientRect();
        const place = document.querySelector<HTMLElement>('[data-bar="place"]');
        const bar = barOf();
        const under = aim === null ? null : document.elementFromPoint(aim.x, aim.y);
        const barBox = bar?.getBoundingClientRect();
        return {
          at: Math.round(performance.now() - started),
          left: box.left,
          top: box.top,
          width: box.width,
          height: box.height,
          place: place === null ? null : place.getBoundingClientRect().height,
          bar: barBox === undefined ? null : [barBox.left, barBox.top, barBox.right, barBox.bottom],
          hidden: bar === null ? null : getComputedStyle(bar).visibility === 'hidden',
          inert: bar === null ? null : bar.inert,
          hit: aim === null ? null : under?.closest('[data-bar="place"]') != null,
        };
      };

      const record: DockMotion = {
        before: sample(),
        frames: [],
        place: null,
        done: false,
        timedOut: false,
      };
      Object.assign(window, { dockMotion: record });

      let calm = 0;
      const tick = () => {
        const place = document.querySelector<HTMLElement>('[data-bar="place"]');
        if (place !== null && record.place === null) {
          // Что движение идёт прямо сейчас, видно по живой анимации на узле, а
          // длительность и кривую отдаёт вычисленный стиль: у перехода они на правиле.
          const style = getComputedStyle(place);
          record.place = {
            running: place.getAnimations().length > 0,
            property: style.transitionProperty,
            duration: style.transitionDuration,
            easing: style.transitionTimingFunction,
          };
        }
        record.frames.push(sample());

        const resting = leaving
          ? place === null
          : place !== null && place.getAnimations().length === 0;
        calm = resting ? calm + 1 : 0;
        if (calm >= 3 || performance.now() - started > 15_000) {
          record.timedOut = calm < 3;
          record.done = true;
          return;
        }
        requestAnimationFrame(tick);
      };

      button?.click();
      requestAnimationFrame(tick);
    },
    { question, leave },
  );
}

async function dockMotion(page: Page): Promise<DockMotion> {
  await page.waitForFunction(
    () => (window as unknown as { dockMotion?: DockMotion }).dockMotion?.done === true,
    undefined,
    { timeout: 20_000 },
  );
  return page.evaluate(() => (window as unknown as { dockMotion: DockMotion }).dockMotion);
}

/** Шаги карточки по вертикали от кадра к кадру, начиная с положения до события. */
function steps(start: number, tops: number[]): number[] {
  return tops.map((top, index) => top - (index === 0 ? start : (tops[index - 1] as number)));
}

/** Прямоугольник карточки из кадра — для сравнения «ни на пиксель». */
function cardRect({ left, top, width, height }: DockFrame): number[] {
  return [left, top, width, height];
}

/**
 * Стояла ли полоса на месте весь приход: на каждом кадре, где она есть, — тот же
 * прямоугольник, что на последнем, в покое. Числа одного источника (`getBoundingClientRect`
 * в браузере), поэтому сравниваются точно. Отклонение печатается в отчёт прогона.
 */
function stillBar(motion: DockMotion): boolean {
  const seen = motion.frames.flatMap((frame) => (frame.bar === null ? [] : [frame.bar]));
  const rest = JSON.stringify(seen.at(-1));
  const moved = seen.filter((box) => JSON.stringify(box) !== rest);
  if (moved.length > 0) report('UI-101 полоса сдвинулась', { rest: seen.at(-1), moved });
  return seen.length > 0 && moved.length === 0;
}

/**
 * Исходное положение сценариев ниже: карточка вопроса предельной ширины на экране,
 * полосы нет, чтение таблицы и движение улеглись.
 *
 * Вопрос владельцу — это и карточка, и запись в деле задачи, то есть и полоса: их
 * приход одним кадром потока движения стопки не требует (UI-98#16). Здесь нужен
 * другой случай — полоса, пришедшая к уже висящей карточке, — поэтому первую полосу
 * снимает «Показать».
 */
async function questionWithoutBar(page: Page): Promise<Locator> {
  const card = stack(page).locator('article').filter({ hasText: LONG_QUESTION });
  await expect(card).toBeVisible();
  await expect(bar(page)).toContainText('Изменилась 1 задача');

  const read = page.waitForResponse((response) => isTableRequest(response.url()));
  await bar(page).getByRole('button', { name: 'Показать' }).click();
  await read;
  await expect(bar(page)).toBeHidden();
  await expect(barPlace(page)).toHaveCount(0);

  await fontsReady(page);
  await motionsSettled(page);
  return card;
}

/** Запись в деле задачи из таблицы: от неё полоса приходит сама, пока карточка висит. */
async function barArrives(request: APIRequestContext): Promise<void> {
  await addEntry(request, 'DEMO-3', {
    type: 'note',
    title: 'Запись, от которой полоса приходит к уже висящему вопросу',
  });
}

/**
 * Там, где полоса и карточка вопроса не помещаются рядом, стопка стоит строкой выше
 * полосы (UI-98#13) и поднимается на эту строку, когда полоса приходит к уже висящей
 * карточке, а опускается, когда «Показать» полосу убирает. До UI-101 это было
 * в один кадр. Место полосы теперь едет строками сетки на токенах словаря движения:
 * приход пришёл сам — `--motion-slow` и `--ease-fast`, уход отвечает человеку —
 * `--motion-fast` и `--ease-exit`. На широком экране, где они стоят рядом, то же
 * движение места не сдвигает карточку ни на пиксель.
 */
test.describe('стопка над полосой обновлений встаёт движением места, а не рывком (UI-101)', () => {
  test('на 768 px приход полосы поднимает стопку, а уход опускает — движением на токенах', async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width: 768, height: 900 });
    await page.goto('/tasks?queue=DEMO');
    await expect(rows(page).first()).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
    // Кадр с вопросом, обогнавший участника, уведомления не даст (`shellReady`).
    await shellReady(page);
    const motion = await motionTokens(page);

    const question = await askOwner(request, 'DEMO-3', LONG_QUESTION);
    try {
      const card = await questionWithoutBar(page);

      // Приход: полоса пришла сама, и стопка встаёт над ней.
      await watchDock(page, LONG_QUESTION, false);
      await barArrives(request);
      const lift = await dockMotion(page);
      expect(lift.timedOut, 'место полосы не пришло или не доехало').toBe(false);

      expect(lift.place?.running).toBe(true);
      expect(lift.place?.property).toBe('grid-template-rows');
      expect(ms(lift.place?.duration ?? '')).toBe(ms(motion.slow));
      expect(curve(lift.place?.easing ?? '')).toBe(curve(motion.enter));

      const idle = lift.frames.filter((frame) => frame.place === null);
      const lifting = lift.frames.filter((frame) => frame.place !== null).map((frame) => frame.top);
      const liftStart = lift.before.top;
      const liftEnd = lifting.at(-1) as number;
      const liftSteps = steps(liftStart, lifting);
      report('UI-101 приход 768px', {
        from: liftStart,
        to: liftEnd,
        frames: lifting.length,
        at: lift.frames.filter((frame) => frame.place !== null).map((frame) => frame.at),
        tops: lifting.map((top) => Math.round(top * 10) / 10),
        place: lift.place,
      });

      // Пока полосы не было, карточка стояла: сдвинуло её именно место полосы.
      expect(idle.map((frame) => frame.top)).toEqual(idle.map(() => liftStart));
      // Поднялась, а не осталась под полосой.
      expect(liftEnd).toBeLessThan(liftStart);
      // На первом снятом кадре карточка ещё в пути: место не встало разом.
      expect(lifting[0]).toBeGreaterThan(liftEnd);
      // Промежуточные положения были, и самый большой шаг за кадр меньше всего пути.
      expect(lifting.some((top) => top < liftStart && top > liftEnd)).toBe(true);
      expect(Math.max(...liftSteps.map((step) => -step))).toBeLessThan(liftStart - liftEnd);
      // И ехала она в одну сторону — вверх, без отскока.
      expect(Math.max(...liftSteps)).toBeLessThanOrEqual(0);

      // Доехала над полосой, а не на неё.
      await motionsSettled(page);
      const lifted = {
        bar: await rectOf(bar(page), 'полоса обновлений'),
        card: await rectOf(card, 'карточка вопроса'),
      };
      report('UI-101 над полосой 768px', {
        bar: rounded(lifted.bar),
        card: rounded(lifted.card),
      });
      expect(lifted.card.y + lifted.card.height).toBeLessThanOrEqual(lifted.bar.y);
      // Едет стопка, а не полоса: с первого кадра полоса стоит там, где встанет в покое.
      expect(stillBar(lift)).toBe(true);

      // Уход: «Показать» нажато, полосы нет, стопка опускается на её место.
      await watchDock(page, LONG_QUESTION, true);
      const drop = await dockMotion(page);
      expect(drop.timedOut, 'место полосы не снялось').toBe(false);

      expect(drop.place?.running).toBe(true);
      expect(drop.place?.property).toBe('grid-template-rows');
      expect(ms(drop.place?.duration ?? '')).toBe(ms(motion.fast));
      expect(curve(drop.place?.easing ?? '')).toBe(curve(motion.exit));
      // Уход вдвое короче прихода: он отвечает человеку (`UI-59#11`).
      expect(ms(lift.place?.duration ?? '')).toBe(ms(drop.place?.duration ?? '') * 2);

      const dropping = drop.frames.map((frame) => frame.top);
      const dropStart = drop.before.top;
      const dropEnd = dropping.at(-1) as number;
      const dropSteps = steps(dropStart, dropping);
      const held = drop.frames.filter((frame) => frame.place !== null);
      report('UI-101 уход 768px', {
        from: dropStart,
        to: dropEnd,
        frames: dropping.length,
        held: held.length,
        at: drop.frames.map((frame) => frame.at),
        tops: dropping.map((top) => Math.round(top * 10) / 10),
        place: drop.place,
      });

      // Опустилась ровно туда, где стояла до полосы.
      expect(dropStart).toBe(liftEnd);
      expect(dropEnd).toBe(liftStart);
      expect(dropping[0]).toBeLessThan(dropEnd);
      expect(dropping.some((top) => top > dropStart && top < dropEnd)).toBe(true);
      expect(Math.max(...dropSteps)).toBeLessThan(dropEnd - dropStart);
      expect(Math.min(...dropSteps)).toBeGreaterThanOrEqual(0);

      /*
       * Правило ухода полосы не сдвинуто (UI-95): узел доживает выход, но полосы уже
       * нет. До нажатия «Показать» стояло под курсором; с первого кадра выхода и до
       * снятия места полоса скрыта, инертна, и точка, где была кнопка, ведёт мимо неё.
       */
      expect(drop.before.hit).toBe(true);
      expect(held.length).toBeGreaterThan(0);
      expect(held.map((frame) => [frame.hidden, frame.inert, frame.hit])).toEqual(
        held.map(() => [true, true, false]),
      );

      /*
       * Выход доехал до конца раньше, чем узел сняли (UI-111): в последнем кадре, где
       * место ещё в разметке, оно уже схлопнулось само, а не обнуляется снятием узла.
       * Иначе остаток хода стопка проходила бы одним кадром — тем рывком, от которого
       * место и едет.
       */
      report('UI-111 уход полосы 768px', {
        at: held.map((frame) => frame.at),
        place: held.map((frame) => Math.round((frame.place ?? 0) * 10) / 10),
      });
      expect(held.at(-1)?.place, 'место полосы снято, не доехав до нуля').toBeLessThanOrEqual(1);

      await expect(bar(page)).toBeHidden();
      await expect(barPlace(page)).toHaveCount(0);
    } finally {
      await question.cleanup();
    }
  });

  test('на 1440 px приход и уход полосы не сдвигают карточку ни на пиксель', async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/tasks?queue=DEMO');
    await expect(rows(page).first()).toBeVisible();
    await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
    await shellReady(page);

    const question = await askOwner(request, 'DEMO-3', LONG_QUESTION);
    try {
      const card = await questionWithoutBar(page);
      const rest = await rectOf(card, 'карточка вопроса до полосы');

      await watchDock(page, LONG_QUESTION, false);
      await barArrives(request);
      const arrival = await dockMotion(page);
      expect(arrival.timedOut, 'место полосы не пришло или не доехало').toBe(false);
      await expect(bar(page)).toContainText('Изменилась 1 задача');
      await motionsSettled(page);
      const withBar = await rectOf(card, 'карточка вопроса при полосе');
      const barBox = await rectOf(bar(page), 'полоса обновлений');

      await watchDock(page, LONG_QUESTION, true);
      const departure = await dockMotion(page);
      expect(departure.timedOut, 'место полосы не снялось').toBe(false);
      await expect(barPlace(page)).toHaveCount(0);
      await motionsSettled(page);
      const after = await rectOf(card, 'карточка вопроса после полосы');

      const placeHeights = arrival.frames.flatMap((frame) =>
        frame.place === null ? [] : [Math.round(frame.place)],
      );
      report('UI-101 1440px', {
        rest: rounded(rest),
        withBar: rounded(withBar),
        after: rounded(after),
        bar: rounded(barBox),
        place: placeHeights,
      });

      // Широкий экран: полоса и карточка стоят рядом, в одной строке низа.
      expect(barBox.x + barBox.width).toBeLessThan(withBar.x);
      expect(overlaps(barBox, withBar)).toBe(false);

      // Место полосы при этом ехало — проверка ниже не пустая.
      expect(arrival.place?.running).toBe(true);
      expect(Math.min(...placeHeights)).toBeLessThan(Math.max(...placeHeights));
      expect(departure.place?.running).toBe(true);

      // До и после — `boundingBox()`, и на каждом кадре обоих движений — то же самое.
      expect(withBar).toEqual(rest);
      expect(after).toEqual(rest);
      for (const motion of [arrival, departure]) {
        expect(motion.frames.map(cardRect)).toEqual(
          motion.frames.map(() => cardRect(motion.before)),
        );
      }
      // И сама полоса не едет: пришла сразу туда, где стоит в покое, — рядом двигать
      // нечего, и движение места не вправе стать движением полосы.
      expect(stillBar(arrival)).toBe(true);

      // Уход и здесь доезжает до конца раньше, чем узел снимают (UI-111).
      const held = departure.frames.filter((frame) => frame.place !== null);
      report('UI-111 уход полосы 1440px', {
        at: held.map((frame) => frame.at),
        place: held.map((frame) => Math.round((frame.place ?? 0) * 10) / 10),
      });
      expect(held.at(-1)?.place, 'место полосы снято, не доехав до нуля').toBeLessThanOrEqual(1);
    } finally {
      await question.cleanup();
    }
  });
});
