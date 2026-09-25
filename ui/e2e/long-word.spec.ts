import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

/**
 * Длинное слово и встроенный код без единой точки переноса (UI-150): агенты пишут пути
 * к файлам, адреса и хеши постоянно, и до `overflow-wrap: anywhere` в `markdown.tsx`
 * такой текст растягивал карточку записи, а с ней страницу вбок на телефоне — замер
 * аудита UI-149 на `/questions` дал `scrollWidth` 547 против `clientWidth` 382. Слово
 * без пробела и дефиса внутри (путь на косой черте и подчёркивании — ни то, ни другое
 * перенос не разрешает, `parents-long.spec.ts`), поэтому единственная точка переноса —
 * та, что даёт `overflow-wrap: anywhere`.
 */
const LONG_WORD =
  'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4/very/long/path/segment/that/has/no/spaces/or/hyphens/anywhere/inside/it/and/keeps/going/past/the/column/width/on/a/phone/screen/without/any/natural/break/point/at/alll';

/** Встроенный код той же формы: адрес, какой встретился в аудите (TRK-63#7). */
const LONG_CODE =
  'https://raw.githubusercontent.com/example_org/example_repo/refs/heads/main/docs/assets/very_long_path_segment_without_any_wrap_opportunity_anywhere_inside_it_at_all.png';

const BODY = [
  `Длинное слово без пробелов: ${LONG_WORD}`,
  `Встроенный код с длинным адресом: \`${LONG_CODE}\``,
  'Рядом ключи задач: UI-137 и UI-137#11 — им рваться по дефису тоже нельзя (UI-151).',
].join('\n\n');

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

async function create(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      project: 'DEMO',
      title: 'Подопытная задача для длинного слова и кода без переноса (UI-150)',
      description: 'Заведена сквозным тестом UI-150: длинное слово и код на 390 px.',
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

/**
 * Вопрос, а не находка: тело вопроса показывается целиком сразу на всех трёх экранах —
 * на карточке (блок «Открытые вопросы»), в деле (лента вопросов и ответов не сворачивает
 * тело) и во входящей, — а находке пришлось бы каждый раз раскрывать строку описи.
 */
async function ask(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { ...auth(), 'X-Actor-Label': 'ui150_probe' },
    data: {
      type: 'question',
      title: 'Замер переноса длинного слова и кода на узком экране',
      body: BODY,
      payload: { addressees: ['owner'], blocking: false },
    },
  });
  expect(response.status()).toBe(201);
}

async function cancel(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-150' },
  });
  if (!response.ok()) {
    await test.info().attach(`уборка ${key} не удалась`, {
      body: await response.text(),
      contentType: 'text/plain',
    });
  }
}

/** Насколько документ шире окна. Больше нуля — страница разъехалась вширь. */
async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/**
 * Проект с длинным названием для UI-181: свой ключ на прогон, как у `project-actions`
 * и `project-place` — проект нельзя удалить, только архивировать, и повторный локальный
 * прогон заводит рядом свой, а не натыкается на прежний.
 */
const PROJECT_RUN = Date.now().toString(36).toUpperCase();
const PROJECT_KEY = `L${PROJECT_RUN}`.slice(0, 16);
const PROJECT_TITLE = `Подопытный проект сквозного теста с очень длинным названием для отбора, прогон ${PROJECT_RUN}`;

async function createLongProject(request: APIRequestContext): Promise<void> {
  const response = await request.post('/api/v1/projects', {
    headers: auth(),
    data: { key: PROJECT_KEY, title: PROJECT_TITLE },
  });
  expect([201, 409]).toContain(response.status());
}

test('длинное слово и код без пробелов не тянут страницу вбок на телефоне (UI-150)', async ({
  page,
  request,
}) => {
  test.setTimeout(90_000);

  const key = await create(request);

  try {
    await ask(request, key);

    await silenceJournal(page);
    await page.setViewportSize({ width: 390, height: 844 });

    for (const address of [`/tasks/${key}`, `/tasks/${key}/case`, '/questions']) {
      await page.goto(address);
      await expect(page.getByRole('main')).toBeVisible();
      // Ждём само содержимое записи, а не только оболочку: замер до его прихода
      // ничего не значит — расширить документ может как раз оно.
      await expect(page.getByText(LONG_WORD.slice(0, 40), { exact: false })).toBeVisible();
      await fontsReady(page);

      expect(await overflow(page), address).toBeLessThanOrEqual(0);

      // Слово и код читаются целиком, а не обрезаны многоточием: ограничение задачи
      // запрещает прятать текст агента.
      await expect(page.getByText(LONG_WORD, { exact: false })).toBeVisible();
      await expect(page.getByText(LONG_CODE, { exact: false })).toBeVisible();
    }
  } finally {
    await cancel(request, key);
  }
});

/**
 * Блок кода (`pre`) переносить нельзя было и раньше — у него своя горизонтальная
 * прокрутка (`Preformatted`, `overflow-x-auto`), и `overflow-wrap: anywhere` этого
 * не меняет: строка внутри `pre` не содержит естественной точки переноса вовсе.
 * Проверяется отдельно от трёх экранов выше: блок кода — не встроенный код, а свой узел.
 */
test('блок кода остаётся при своей прокрутке, а не переносится по буквам (UI-150)', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  const key = await create(request);
  const block = ['```', LONG_CODE, '```'].join('\n');

  try {
    const response = await request.post(`/api/v1/tasks/${key}/entries`, {
      headers: { ...auth(), 'X-Actor-Label': 'ui150_probe' },
      data: { type: 'finding', title: 'Блок кода без переноса', body: block },
    });
    expect(response.status()).toBe(201);

    await silenceJournal(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/tasks/${key}/case`);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByText(LONG_CODE, { exact: false })).toBeVisible();
    await fontsReady(page);

    expect(await overflow(page)).toBeLessThanOrEqual(0);

    const pre = page.locator('pre').filter({ hasText: LONG_CODE.slice(0, 30) });
    await expect(pre).toBeVisible();
    const scrolls = await pre.evaluate((node) => ({
      overflowX: getComputedStyle(node).overflowX,
      overflows: node.scrollWidth > node.clientWidth,
    }));
    expect(scrolls.overflowX).toBe('auto');
    expect(scrolls.overflows).toBe(true);
  } finally {
    await cancel(request, key);
  }
});

/**
 * Отбор проекта на `/questions` (UI-181): закрытый `<select>` без ограничения ширины
 * растягивался по самой длинной паре «ключ — название» среди `bootstrap.data.projects`,
 * даже когда она не выбрана, — проект достаточно завести, выбирать его не нужно.
 * Оба блока входящей проверяются отдельно: у входящей и у истории вопросов свой `<select>`
 * (`questions-page.tsx`).
 */
test('длинное название проекта в отборе не тянет /questions вбок на телефоне (UI-181)', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  await createLongProject(request);

  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });

  for (const address of ['/questions', '/questions?view=history']) {
    await page.goto(address);
    await expect(page.getByRole('main')).toBeVisible();
    // Ждём сам проект в списке: бутстрап приходит своим запросом, и замер до его
    // прихода ничего не значит — раздвинуть закрытый `<select>` может как раз он.
    await expect(page.locator(`option[value="${PROJECT_KEY}"]`)).toHaveCount(1);
    await fontsReady(page);

    expect(await overflow(page), address).toBeLessThanOrEqual(0);
  }
});
