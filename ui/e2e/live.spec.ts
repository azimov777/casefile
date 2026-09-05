import { expect, test, type APIRequestContext } from '@playwright/test';
import { compose, readE2eToken } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Ждёт, пока счётчик перестанет расти: запросы улеглись. */
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
      { intervals: [300, 300, 300, 300, 300], timeout: 5_000 },
    )
    .toBe(true);
}

/**
 * Подшить запись в дело задачи так, как это делает агент.
 *
 * С повторами: сценарий обрыва зовёт это сразу после подъёма бэкенда, а тот отвечает
 * не в первую секунду.
 */
async function addEntry(
  request: APIRequestContext,
  key: string,
  body: Record<string, unknown>,
): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          const response = await request.post(`/api/v1/tasks/${key}/entries`, {
            headers: { Authorization: `Bearer ${token}` },
            data: body,
            timeout: 5_000,
          });
          return response.status();
        } catch {
          return 0;
        }
      },
      { timeout: 60_000 },
    )
    .toBe(201);
}

/**
 * Живой поток проверяется только здесь: в jsdom он не работает вовсе
 * (`@microsoft/fetch-event-source` создаёт свой `AbortSignal`, который не принимает
 * `fetch` из Node), поэтому страничные тесты подменяют границу «как открыть поток»,
 * а настоящий SSE — забота браузера.
 *
 * Сценарий пишет в демо-установку, поэтому живёт в проекте «ответ», который идёт
 * после читающих (`playwright.config.ts`).
 */
test('запись, подшитая через API, доходит до открытого экрана без перезагрузки', async ({
  page,
  request,
}) => {
  const listings: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks?')) listings.push(call.url());
  });

  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('rowheader', { name: 'DEMO-3' })).toBeVisible();

  // Поток открыт: шапка говорит об этом словами.
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  // Открытие потока само перечитывает показанное (в паузу могло случиться что угодно),
  // поэтому «до» считается, когда запросы улеглись, — иначе тест считал бы чужой запрос.
  await settled(() => listings.length);
  const before = listings.length;

  await addEntry(request, 'DEMO-3', {
    type: 'note',
    title: 'Заметка, сделанная при открытом списке',
    body: 'Запись, сделанная во время открытого экрана.',
  });

  // Список перечитался сам — и ровно один раз на кадр, а не серией.
  await expect.poll(() => listings.length, { timeout: 5_000 }).toBeGreaterThan(before);
  await settled(() => listings.length);
  expect(listings.length).toBe(before + 1);

  // Одно соединение на вкладку: переход между экранами его не пересоздаёт.
  const streams: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/journal/stream')) streams.push(call.url());
  });
  await page.getByRole('link', { name: 'Доска' }).click();
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();
  expect(streams).toEqual([]);
});

test('запись, подшитая при открытой карточке, попадает в опись дела', async ({ page, request }) => {
  await page.goto('/tasks/DEMO-3');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-3');

  const rows = page.getByRole('row');
  const before = await rows.count();

  await addEntry(request, 'DEMO-3', {
    type: 'finding',
    title: 'Находка, пришедшая живым потоком',
    body: 'Опись должна пополниться сама.',
  });

  await expect(
    page.getByRole('row').filter({ hasText: 'Находка, пришедшая живым потоком' }),
  ).toBeVisible({
    timeout: 5_000,
  });
  expect(await rows.count()).toBeGreaterThan(before);
});

/**
 * Сценарий возвращает установку в прежнее состояние: заданный вопрос закрывается
 * ответом через API. Иначе он оставлял бы во входящей вопрос, и соседний пишущий
 * сценарий видел бы не то, что ожидал.
 */
test('вопрос ко мне объявляется в шапке и растит счётчик без перезагрузки', async ({
  page,
  request,
}) => {
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  const response = await request.post('/api/v1/tasks/DEMO-3/entries', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      type: 'question',
      title: 'Вопрос владельцу из сквозного теста',
      body: 'Проверяем, доходит ли вопрос до шапки живым потоком.',
      payload: { addressees: ['owner'], blocking: false },
    },
  });
  expect(response.status()).toBe(201);

  const notice = page.getByRole('link', { name: /Вам вопрос: DEMO-3#\d+/ });
  await expect(notice).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole('banner').getByText(/Открытых вопросов: [1-9]/)).toBeVisible();

  // Убираем за собой: вопрос закрывается ответом, счётчик возвращается к прежнему.
  const question = (await response.json()) as { data: { no: number } };
  await addEntry(request, 'DEMO-3', {
    type: 'answer',
    body: 'Отвечено сквозным тестом, чтобы входящая осталась какой была.',
    payload: { question_no: question.data.no },
  });
});

test('обрыв виден в шапке, а после восстановления пропущенное не теряется', async ({
  page,
  request,
}) => {
  // Гашение и подъём бэкенда — минуты, а не секунды: сценарий идёт последним и один.
  test.setTimeout(180_000);

  await page.goto('/tasks/DEMO-3');
  const header = page.getByRole('banner');
  await expect(header.getByText('на связи')).toBeVisible();

  // Рвём связь так, как она рвётся в жизни: бэкенд ушёл. Перехват маршрута этого не
  // умеет (он действует на новые запросы), а `setOffline` не закрывает уже открытый
  // поток — сервер продолжает держать соединение.
  compose(['stop', 'api']);
  await expect(header.getByText('нет связи')).toBeVisible({ timeout: 60_000 });

  compose(['start', 'api']);

  // Запись, сделанная в паузу: поток о ней не узнает — он ещё не переподключился.
  // Появиться на экране она обязана всё равно.
  await addEntry(request, 'DEMO-3', {
    type: 'note',
    title: 'Запись, сделанная во время обрыва',
    body: 'После восстановления она обязана быть на экране.',
  });

  await expect(header.getByText('на связи')).toBeVisible({ timeout: 90_000 });
  await expect(
    page.getByRole('row').filter({ hasText: 'Запись, сделанная во время обрыва' }),
  ).toBeVisible({ timeout: 30_000 });
});
