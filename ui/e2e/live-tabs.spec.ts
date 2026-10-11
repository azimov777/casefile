import { expect, test, type APIRequestContext, type Page, type Request } from '@playwright/test';
import { askLegacyOwner, readE2eToken } from './contour';

const token = readE2eToken();

/** Задача, на карточке которой идут сценарии: кандидат демо, дело которого можно дополнять. */
const KEY = 'DEMO-3';

/** Метка прогона: записи остаются в деле, и строку описи ищут по названию. */
const RUN = Date.now().toString(36);

/** Подшивает заметку в дело задачи и отдаёт её номер в деле и место в журнале. */
async function addNote(
  request: APIRequestContext,
  title: string,
  body = '',
): Promise<{ no: number; seq: number; title: string }> {
  const response = await request.post(`/api/v1/tasks/${KEY}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { type: 'note', title, body },
  });
  expect(response.status()).toBe(201);
  const filed = ((await response.json()) as { data: { no: number; seq: number } }).data;
  return { no: filed.no, seq: filed.seq, title };
}

/** Сколько потоков журнала открыто разом во всех наблюдаемых страницах и сколько было самое большее. */
interface Tally {
  pending: number;
  peak: number;
}

/** Запросы потока журнала одной страницы: все открытые по порядку и ещё не завершённые. */
interface Streams {
  opened: Request[];
  pending: Set<Request>;
}

/**
 * Следит за запросами потока журнала со страницы.
 *
 * Незавершённый запрос — открытое соединение: ответ SSE не кончается, пока поток жив,
 * а закрытие клиентом браузер сообщает отказом запроса (`requestfailed`).
 */
function watchStreams(page: Page, tally: Tally = { pending: 0, peak: 0 }): Streams {
  const streams: Streams = { opened: [], pending: new Set() };
  const over = (call: Request): void => {
    if (!streams.pending.delete(call)) return;
    tally.pending -= 1;
  };
  page.on('request', (call) => {
    if (!call.url().includes('/api/v1/journal/stream')) return;
    streams.opened.push(call);
    streams.pending.add(call);
    tally.pending += 1;
    tally.peak = Math.max(tally.peak, tally.pending);
  });
  page.on('requestfinished', over);
  page.on('requestfailed', over);
  return streams;
}

/**
 * Ожидание, которое сценарий не обрывает: на коде, где скрытая вкладка держит поток,
 * сценарий на восемь вкладок доходит до конца и называет всё, что не так, разом.
 */
const softly = expect.configure({ soft: true });

function state(streams: Streams): { opened: number; pending: number } {
  return { opened: streams.opened.length, pending: streams.pending.size };
}

/**
 * Страница рождается скрытой — как вкладка, открытая в фоне.
 *
 * Playwright страниц не прячет: все страницы контекста считают себя видимыми. Скрытость
 * объявляется странице так же, как её объявляет браузер, и до загрузки приложения:
 * иначе оно успело бы увидеть вкладку видимой.
 */
async function bornHidden(page: Page): Promise<void> {
  await page.addInitScript(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  });
}

/** Вкладка ушла в фон или вернулась: значение и событие, как у браузера. */
async function setHidden(page: Page, hidden: boolean): Promise<void> {
  await page.evaluate((value) => {
    Object.defineProperty(document, 'hidden', { configurable: true, value });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);
}

/**
 * Запоминает, что говорил индикатор связи за всю жизнь страницы. Ставится до загрузки:
 * «нет связи», мелькнувшее на один кадр, проверкой после события уже не поймать.
 */
async function watchStatus(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const said: string[] = [];
    Object.assign(window, { liveStatusSaid: said });
    new MutationObserver(() => {
      if ((document.body?.textContent ?? '').includes('нет связи')) said.push('нет связи');
    }).observe(document, { childList: true, subtree: true, characterData: true });
  });
}

async function statusSaid(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { liveStatusSaid: string[] }).liveStatusSaid);
}

function entryRow(page: Page, title: string) {
  return page.getByRole('row').filter({ hasText: title });
}

/** Ждёт, пока счётчик запросов перестанет расти: перечитывание улеглось. */
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
 * Даёт сценарию оборвать настоящий поток посреди выдачи — так, как рвётся сеть.
 *
 * Ответ потока идёт клиенту через свою трубу: оборвав её, сценарий получает обрыв без
 * гашения бэкенда, а следующий запрос потока уходит в сеть как есть — с теми
 * заголовками, которые собрал клиент. Остальные ответы перехват отдаёт нетронутыми.
 */
async function breakableJournal(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const network = window.fetch.bind(window);
    let breaker: AbortController | null = null;
    Object.assign(window, { breakJournal: () => breaker?.abort() });

    window.fetch = async (input, init) => {
      const response = await network(input, init);
      const address =
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (!address.includes('/api/v1/journal/stream') || response.body === null) return response;

      breaker = new AbortController();
      const pipe = new TransformStream<Uint8Array, Uint8Array>();
      // Отказ трубы — это и есть обрыв (наш или клиента, закрывшего поток): глотаем.
      void response.body.pipeTo(pipe.writable, { signal: breaker.signal }).catch(() => undefined);
      return new Response(pipe.readable, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    };
  });
}

/**
 * Поток журнала держит только видимая вкладка (TRK-697).
 *
 * Браузер по HTTP/1.1 даёт шесть соединений на адрес, а поток занимает одно на всё
 * время жизни: шесть вкладок с потоками оставляли остальные без сети вовсе. Скрытая
 * вкладка поток закрывает, как только знает свою позицию, и после возврата продолжает
 * с неё по `Last-Event-ID`.
 *
 * Сценарии пишут в дело демо-задачи, а первый открывает восемь страниц разом, поэтому
 * живут в проекте «запись»: по одному и после читающих (`playwright.config.ts`).
 */
test('восемь вкладок карточки: семь скрытых потока не держат, восьмая читает запись сразу', async ({
  context,
  request,
}) => {
  // Каждое ожидание ниже со своим пределом, и на красном прогоне они складываются.
  test.setTimeout(90_000);

  const body = `Тело записи, которое читают восемь вкладок (${RUN}).`;
  const note = await addNote(request, `Запись для восьми вкладок ${RUN}`, body);
  const address = `/tasks/${KEY}?entry=${note.no}`;
  const tally: Tally = { pending: 0, peak: 0 };

  for (let tab = 1; tab <= 7; tab += 1) {
    const hidden = await context.newPage();
    await bornHidden(hidden);
    const streams = watchStreams(hidden, tally);
    // Конец загрузки не ждём: без свободного соединения страница не получает и документа,
    // а сказать об этом должно ожидание ниже, а не отказ перехода.
    await hidden.goto(address, { waitUntil: 'commit', timeout: 3_000 }).catch(() => undefined);
    // Скрытая вкладка открыла поток, узнала позицию и закрыла его — и только тогда
    // открывается следующая: так «не больше одного потока разом» мерится честно.
    await softly
      .poll(() => state(streams), {
        timeout: 3_000,
        message: `скрытая вкладка ${tab}: поток открыт один раз и закрыт`,
      })
      .toEqual({ opened: 1, pending: 0 });
  }

  const eighth = await context.newPage();
  const streams = watchStreams(eighth, tally);
  const deadline = Date.now() + 5_000;
  const arrived = await eighth.goto(address, { waitUntil: 'commit', timeout: 5_000 }).then(
    () => true,
    () => false,
  );
  softly(arrived, 'документ восьмой вкладки пришёл за 5 секунд').toBe(true);
  await softly(
    eighth.getByRole('cell').filter({ hasText: body }),
    'тело записи на восьмой вкладке показано за 5 секунд',
  ).toBeVisible({ timeout: Math.max(deadline - Date.now(), 1) });
  await softly(eighth.getByText('Читаем запись…')).toHaveCount(0, { timeout: 1_000 });

  // Видимая вкладка поток держит, и он один на все восемь страниц — в любой момент.
  await softly
    .poll(() => state(streams), { timeout: 3_000, message: 'восьмая вкладка держит один поток' })
    .toEqual({ opened: 1, pending: 1 });
  expect(tally.peak, 'потоков журнала одновременно по всем восьми страницам').toBeLessThanOrEqual(
    1,
  );
});

test('вкладка ушла в фон — поток закрыт; вернулась — продолжает с позиции и показывает подшитое', async ({
  page,
  request,
}) => {
  // Последняя запись журнала до открытия страницы: её номером поток назовёт свою позицию.
  const mark = await addNote(request, `Отметка журнала перед открытием ${RUN}-a`);

  await watchStatus(page);
  const streams = watchStreams(page);
  await page.goto(`/tasks/${KEY}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(KEY);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  expect(state(streams)).toEqual({ opened: 1, pending: 1 });

  await setHidden(page, true);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'поток скрытой вкладки закрыт' })
    .toEqual({ opened: 1, pending: 0 });

  const note = await addNote(request, `Запись, подшитая пока вкладка была скрыта ${RUN}-a`);
  // Скрытая вкладка за записью не ходит: нового запроса потока нет.
  expect(state(streams)).toEqual({ opened: 1, pending: 0 });

  await setHidden(page, false);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'вернувшаяся вкладка открыла поток' })
    .toEqual({ opened: 2, pending: 1 });
  // Позиция — из первого блока потока: ни одного кадра записи до страницы не дошло.
  expect(await streams.opened[1]?.headerValue('last-event-id')).toBe(String(mark.seq));
  await expect(entryRow(page, note.title)).toBeVisible({ timeout: 5_000 });

  // Уход в фон — не обрыв: «нет связи» не сказано ни разу.
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  expect(await statusSaid(page)).toEqual([]);
});

test('вкладка, открытая в фоне, поток не держит, а после показа догоняет подшитое', async ({
  page,
  request,
}) => {
  const mark = await addNote(request, `Отметка журнала перед открытием ${RUN}-b`);

  await bornHidden(page);
  await watchStatus(page);
  const streams = watchStreams(page);
  await page.goto(`/tasks/${KEY}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(KEY);
  // Позиции у новой вкладки нет: она открывает поток, узнаёт её из первого блока и
  // закрывает — до первой записи.
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'поток скрытой вкладки закрыт' })
    .toEqual({ opened: 1, pending: 0 });

  const note = await addNote(request, `Запись, подшитая до первого показа вкладки ${RUN}-b`);
  expect(state(streams)).toEqual({ opened: 1, pending: 0 });

  await setHidden(page, false);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'показанная вкладка открыла поток' })
    .toEqual({ opened: 2, pending: 1 });
  expect(await streams.opened[1]?.headerValue('last-event-id')).toBe(String(mark.seq));
  await expect(entryRow(page, note.title)).toBeVisible({ timeout: 5_000 });

  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  expect(await statusSaid(page)).toEqual([]);
});

test('пачка записей, подшитых пока вкладка была скрыта, после возврата стоит одного чтения карточки', async ({
  page,
  request,
}) => {
  // Чтения пакета карточки: адрес без хвоста, лента и тела записей сюда не попадают.
  const packages: string[] = [];
  page.on('request', (call) => {
    if (new URL(call.url()).pathname === `/api/v1/tasks/${KEY}`) packages.push(call.url());
  });
  const streams = watchStreams(page);
  await page.goto(`/tasks/${KEY}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(KEY);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  await setHidden(page, true);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'поток скрытой вкладки закрыт' })
    .toEqual({ opened: 1, pending: 0 });

  // Заход агента по задаче, пока на неё никто не смотрит: два десятка записей подряд.
  let last = '';
  for (let no = 1; no <= 20; no += 1) {
    last = (await addNote(request, `Запись пачки ${RUN} №${no}`)).title;
  }
  const before = packages.length;

  await setHidden(page, false);
  await expect(entryRow(page, last)).toBeVisible({ timeout: 5_000 });

  // Поток отдал пропущенное пачкой, и карточка перечитана один раз на всю пачку, а не
  // по разу на запись: после долгого фона это была бы сотня чтений подряд.
  await settled(() => packages.length);
  expect(packages.length - before).toBe(1);
});

test('вопрос ко мне, заданный пока вкладка была скрыта, после возврата объявлен уведомлением', async ({
  page,
  request,
}) => {
  const streams = watchStreams(page);
  await page.goto('/tasks?project=DEMO');
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  await setHidden(page, true);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'поток скрытой вкладки закрыт' })
    .toEqual({ opened: 1, pending: 0 });

  const title = `Вопрос, заданный скрытой вкладке ${RUN}`;
  const asked = await askLegacyOwner(request, { key: KEY, title });
  try {
    const notice = page.getByRole('complementary', { name: 'Вопросы ко мне' });
    await expect(notice.locator('article')).toHaveCount(0);

    await setHidden(page, false);
    await expect(notice.getByRole('link', { name: `${KEY}#${asked.no}` })).toBeVisible({
      timeout: 5_000,
    });
    await expect(notice.getByText(title)).toBeVisible();
  } finally {
    await asked.cleanup();
  }
});

test('обрыв после возврата из фона: переподключение называет одну позицию и доносит записи', async ({
  page,
  request,
}) => {
  await breakableJournal(page);
  const streams = watchStreams(page);
  await page.goto(`/tasks/${KEY}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(KEY);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  await setHidden(page, true);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'поток скрытой вкладки закрыт' })
    .toEqual({ opened: 1, pending: 0 });
  await setHidden(page, false);
  await expect
    .poll(() => state(streams), { timeout: 2_000, message: 'вернувшаяся вкладка открыла поток' })
    .toEqual({ opened: 2, pending: 1 });

  // Кадр после возврата: его номер клиент потока запоминает сам, для своих повторов.
  const before = await addNote(request, `Запись перед обрывом ${RUN}`);
  await expect(entryRow(page, before.title)).toBeVisible({ timeout: 5_000 });

  await page.evaluate(() => (window as unknown as { breakJournal: () => void }).breakJournal());
  await expect
    .poll(() => streams.opened.length, { timeout: 15_000, message: 'поток переподключился' })
    .toBe(3);

  /*
   * Позиция, с которой хук открыл поток после возврата, и номер, который клиент потока
   * запомнил сам, — один заголовок, а не два: два значения браузер склеил бы через
   * запятую, бэкенд такую позицию не разбирает, и поток не открылся бы уже никогда.
   */
  const retry = streams.opened[2] as Request;
  expect(await retry.headerValue('last-event-id')).toBe(String(before.seq));
  expect((await retry.response())?.status()).toBe(200);

  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible({ timeout: 15_000 });
  const after = await addNote(request, `Запись после обрыва ${RUN}`);
  await expect(entryRow(page, after.title)).toBeVisible({ timeout: 5_000 });
});
