import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Locator } from '@playwright/test';
import { compose, readE2eToken } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/**
 * Положение названных элементов на экране. Сравнивается до и после события, которое
 * пришло само: движение позволено только тому, что о себе объявляет, — и не ценой
 * сдвига того, что человек в этот момент читает.
 */
async function geometry(targets: Record<string, Locator>): Promise<Record<string, DOMRect>> {
  const measured: Record<string, DOMRect> = {};
  for (const [name, target] of Object.entries(targets)) {
    measured[name] = (await target.boundingBox()) as unknown as DOMRect;
  }
  return measured;
}

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
test('запись, подшитая через API, доходит до открытого списка полосой, а не перестановкой', async ({
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

  // Кадр дошёл, но список сам не перечитывается: он ждёт просьбы (UI-13). Что кадр
  // именно дошёл, видно по полосе.
  await expect(page.getByRole('status', { name: 'Обновления списка' })).toContainText(
    'Изменилось задач',
  );
  await settled(() => listings.length);
  expect(listings.length).toBe(before);

  // По просьбе — ровно один запрос на всё накопленное, а не серия.
  await page.getByRole('button', { name: 'Показать' }).click();
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
test('вопрос ко мне объявляется уведомлением и не сдвигает того, что человек читает', async ({
  page,
  request,
}) => {
  // Список отобран по `done`, и DEMO-3 в него не входит. Это важно для замера:
  // заданный вопрос честно меняет признаки своей задачи — у неё появляется плашка
  // «вопросов 1», строка становится выше, и на общем списке замер смешивал бы две
  // причины. Здесь единственное, что может сдвинуть вёрстку, — само уведомление.
  await page.goto('/tasks?queue=DEMO&status=done');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  // Замер до события: уведомление приходит само, и сдвинуть чужое оно не вправе.
  const watched = {
    header: page.getByRole('banner'),
    firstRow: page.locator('tbody tr').first(),
    logout: page.getByRole('button', { name: 'Выйти' }),
  };
  const before = await geometry(watched);

  const response = await request.post('/api/v1/tasks/DEMO-3/entries', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      type: 'question',
      title: 'Вопрос владельцу из сквозного теста',
      body: 'Проверяем, доходит ли вопрос до экрана живым потоком.',
      payload: { addressees: ['owner'], blocking: true },
    },
  });
  expect(response.status()).toBe(201);
  const question = (await response.json()) as { data: { no: number } };

  const notice = page.getByRole('complementary', { name: 'Вопросы ко мне' });
  await expect(notice.getByText('Вопрос владельцу из сквозного теста')).toBeVisible({
    timeout: 5_000,
  });
  await expect(notice.getByText('блокирующий')).toBeVisible();

  // Счётчик в шапке тоже ожил и стал ссылкой во входящую.
  const counter = page.getByRole('banner').getByRole('link', { name: /Открытых вопросов: [1-9]/ });
  await expect(counter).toHaveAttribute('href', '/questions');

  expect(await geometry(watched)).toEqual(before);

  // Переход по уведомлению ведёт к самому вопросу: карточка с раскрытой записью.
  await notice.getByRole('link', { name: `DEMO-3#${question.data.no}` }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/DEMO-3\\?entry=${question.data.no}$`));
  await expect(page.getByText('Вопрос владельцу из сквозного теста').first()).toBeVisible();
  // Точное совпадение: `getByLabel('Ответ')` находит и поле, и саму форму —
  // у неё `aria-label="Ответ на DEMO-3#N"` (тот же приём в `answer.spec.ts`).
  await expect(page.getByLabel(/^Ответ$/)).toBeVisible();

  // Уведомление гаснет переходом: человек уже там, куда оно звало. Область объявления
  // при этом остаётся — она обязана существовать до следующего вопроса.
  await expect(
    page.getByRole('complementary', { name: 'Вопросы ко мне' }).locator('article'),
  ).toHaveCount(0);

  // Убираем за собой: вопрос закрывается ответом, счётчик возвращается к прежнему.
  await addEntry(request, 'DEMO-3', {
    type: 'answer',
    body: 'Отвечено сквозным тестом, чтобы входящая осталась какой была.',
    payload: { question_no: question.data.no },
  });
});

test('два вопроса подряд видны оба: второй не затирает первый', async ({ page, request }) => {
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  const asked: { key: string; no: number }[] = [];
  for (const key of ['DEMO-3', 'DEMO-4']) {
    const response = await request.post(`/api/v1/tasks/${key}/entries`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        type: 'question',
        title: `Вопрос из сквозного теста по ${key}`,
        body: 'Второй вопрос не должен затирать первый.',
        payload: { addressees: ['owner'], blocking: false },
      },
    });
    expect(response.status()).toBe(201);
    asked.push({ key, no: ((await response.json()) as { data: { no: number } }).data.no });
  }

  const notice = page.getByRole('complementary', { name: 'Вопросы ко мне' });
  for (const question of asked) {
    await expect(notice.getByRole('link', { name: `${question.key}#${question.no}` })).toBeVisible({
      timeout: 5_000,
    });
  }

  const found = await new AxeBuilder({ page }).analyze();
  expect(found.violations).toEqual([]);

  for (const question of asked) {
    await addEntry(request, question.key, {
      type: 'answer',
      body: 'Отвечено сквозным тестом, чтобы входящая осталась какой была.',
      payload: { question_no: question.no },
    });
  }
});

test('на загрузке страницы индикатор ни разу не говорит «нет связи»', async ({ page }) => {
  // Наблюдатель ставится до загрузки: состояние `connecting` живёт доли секунды,
  // и поймать его проверкой после `goto` нельзя — к тому моменту поток уже открыт.
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __seen: string[] }).__seen = seen;
    new MutationObserver(() => {
      const text = document.querySelector('header')?.textContent ?? '';
      if (text.includes('нет связи')) seen.push('нет связи');
      if (text.includes('подключаемся')) seen.push('подключаемся');
    }).observe(document, { childList: true, subtree: true, characterData: true });
  });

  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();

  const seen = await page.evaluate(() => (window as unknown as { __seen: string[] }).__seen);
  expect(seen).not.toContain('нет связи');
  // Первое открытие называется своими словами, а не молчанием.
  expect(seen).toContain('подключаемся');
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
