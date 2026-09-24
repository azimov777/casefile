import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

/**
 * Ключ задачи и ссылка на запись не рвутся переносом по дефису (UI-151, аудит UI-149):
 * «(UI-⏎137#11)» в сводке карточки UI-137 на 390 px, то же в тёмной теме на 1440 px
 * в сводке UI-124. Браузер вправе перенести строку после дефиса так же, как после
 * пробела (UAX #14), и короткий ключ разваливается пополам — его не находит ни поиск
 * глазами, ни копирование строки (`ui/docs/CONCEPT.md`, §6).
 *
 * Проверка не подбирает одну ширину-виновника: от неё зависит и шрифт, и то, сколько
 * текста стоит перед ключом, а оба меняются вместе с содержимым сводки. Вместо этого
 * запись несёт тридцать абзацев с одним и тем же ключом на разном отступе слов перед
 * ним — реальный перенос совпадает хотя бы с одним из них при любой разумной ширине
 * колонки и любом шрифте, и всё найденное обязано остаться целым. До UI-151 такой
 * набор на 390 px давал минимум один разрыв — ниже это тело задачи UI-150#4
 * (`git log`, воспроизведение в деле).
 */
function paddedKeyLines(key: string): string {
  const lines: string[] = [];
  for (let n = 0; n <= 30; n += 1) {
    const filler = 'слово '.repeat(n);
    lines.push(`${filler}${key} хвост.`);
  }
  return lines.join('\n\n');
}

const KEY_REF = 'UI-137#11';
const KEY_PLAIN = 'UI-137';

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

async function create(
  request: APIRequestContext,
  title = 'Подопытная задача для неразрывных ключей в сводке (UI-151)',
): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      queue: 'DEMO',
      title,
      description: 'Заведена сквозным тестом UI-151: ключ и ссылка на запись на 390 px.',
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

/** Связь `subject relates other` со стороны `subject` — тем же путём, что агент. */
async function link(request: APIRequestContext, subject: string, other: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${subject}/links`, {
    headers: auth(),
    data: { kind: 'relates', other },
  });
  expect(response.status(), `${subject} relates ${other}`).toBe(201);
}

/** Сводка — та же форма записи, что и в реальном аудите (карточка UI-137, UI-124). */
async function summarize(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { ...auth(), 'X-Actor-Label': 'ui151_probe' },
    data: {
      type: 'summary',
      payload: {
        done: 'Замер переноса ключа на разных отступах.',
        remaining: paddedKeyLines(KEY_REF),
        blockers: paddedKeyLines(KEY_PLAIN),
        next_step: 'Ничего: тело задачи для сквозного теста.',
      },
    },
  });
  expect(response.status()).toBe(201);
}

async function cancel(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-151' },
  });
  if (!response.ok()) {
    await test.info().attach(`уборка ${key} не удалась`, {
      body: await response.text(),
      contentType: 'text/plain',
    });
  }
}

/** Ключи-ссылки на узкой колонке: у каждого ровно один прямоугольник — перенос не рвёт его. */
async function keyLinkRectCounts(page: Page, pattern: RegExp): Promise<number[]> {
  return page.evaluate((source) => {
    const re = new RegExp(source);
    return Array.from(document.querySelectorAll('a'))
      .filter((a) => re.test(a.textContent ?? ''))
      .map((a) => a.getClientRects().length);
  }, pattern.source);
}

test('ключ и ссылка на запись в сводке не рвутся переносом по дефису на 390 px (UI-151)', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  const key = await create(request);

  try {
    await summarize(request, key);

    await silenceJournal(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/tasks/${key}`);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Последняя сводка' })).toBeVisible();
    await expect(page.getByText(KEY_REF).first()).toBeVisible();
    await fontsReady(page);

    const refCounts = await keyLinkRectCounts(page, /^UI-137#11$/);
    const plainCounts = await keyLinkRectCounts(page, /^UI-137$/);
    // Тридцать одна строка на каждое поле — все найдены ссылками, ни одна не пропала
    // из разбора и ни одна не разорвана переносом.
    expect(refCounts.length).toBeGreaterThanOrEqual(31);
    expect(plainCounts.length).toBeGreaterThanOrEqual(31);
    for (const count of refCounts) expect(count).toBe(1);
    for (const count of plainCounts) expect(count).toBe(1);
  } finally {
    await cancel(request, key);
  }
});

/**
 * Ключи вне markdown (задача UI-151, «опись, таблица, связи»): на практике они стоят
 * в собственной ячейке или строке и текста рядом с собой не делят, поэтому реальный
 * перенос посреди них на разумной ширине не воспроизводится, — но правило то же самое
 * применено и там (`entities/task/ui/task-card.tsx`, `task-row.tsx`,
 * `pages/task/ui/task-header.tsx`, `entities/entry/ui/entry-headline.tsx`,
 * `pages/task/ui/task-links.tsx`), и здесь это проверено вычисленным стилем, тем же
 * замером, что защищает markdown. Блок «Связи» UI-151 сознательно обошла — файл вела
 * параллельная задача UI-141/148 — и закрыла его отдельно задача UI-161, тем же приёмом.
 *
 * Замер идёт через один `page.evaluate` с обычным `querySelector`, а не через цепочку
 * `getByRole(...).getByRole(...)` с именем по регэкспу: у последней своя, немалая цена —
 * на каждый повтор ожидания Playwright пересчитывает доступное имя всех кандидатов,
 * а под чужой нагрузкой машины («Ожидание в Bash» в общем брифе задачи) это утроило
 * время одного этого сценария до тайм-аута `test.setTimeout`, хотя сама страница
 * дорисовывалась верно и быстро — снимок `error-context.md` падения это подтвердил:
 * искомая строка «Ответ на KEY#N» уже стояла в дереве, а тест всё ещё не сдвинулся.
 * `querySelector` в браузере — один синхронный обход, без ретраев со стороны Playwright.
 */
/** Ячейка ключа строки таблицы, найденной по тексту (список задач). */
async function rowKeyStyle(page: Page, key: string): Promise<string | null> {
  return page.evaluate((taskKey) => {
    const row = Array.from(document.querySelectorAll('tbody tr')).find((candidate) =>
      (candidate.textContent ?? '').includes(taskKey),
    );
    const cell = row?.querySelector('th') ?? null;
    return cell === null ? null : getComputedStyle(cell).whiteSpace;
  }, key);
}

/** Ключ в шапке карточки и ключ в заголовке описи «Ответ на KEY#N» (карточка задачи). */
async function taskPageKeyStyles(
  page: Page,
): Promise<{ headerKey: string | null; headlineKey: string | null }> {
  return page.evaluate(() => {
    const style = (node: Element | null) =>
      node === null ? null : getComputedStyle(node).whiteSpace;

    const headerKey = style(document.querySelector('h1 span.font-mono'));

    const headlineButton = Array.from(document.querySelectorAll('table[aria-label] button')).find(
      (candidate) => (candidate.textContent ?? '').includes('Ответ на'),
    );
    const headlineKey = style(headlineButton?.querySelector('a.font-mono, code.font-mono') ?? null);

    return { headerKey, headlineKey };
  });
}

/**
 * Ключ-ссылка на связанную задачу в блоке «Связи» (`aria-labelledby="links"`,
 * заголовок «Связи»): один прямоугольник и `white-space: nowrap` вычисленным стилем —
 * тот же замер, что и для описи, таблицы и шапки выше (UI-161: правило UI-151, которое
 * `task-links.tsx` сознательно обошло стороной, потому что файл в это же время вела
 * параллельная задача UI-141/148).
 */
async function linksKeyMeasure(
  page: Page,
  otherKey: string,
): Promise<{ rectCount: number; whiteSpace: string | null }> {
  return page.evaluate((targetKey) => {
    const region = document.querySelector('section[aria-labelledby="links"]');
    const found = Array.from(region?.querySelectorAll('a') ?? []).find(
      (a) => a.textContent === targetKey,
    );
    return {
      rectCount: found?.getClientRects().length ?? 0,
      whiteSpace: found === undefined ? null : getComputedStyle(found).whiteSpace,
    };
  }, otherKey);
}

test('ключ задачи вне markdown несёт `white-space: nowrap` — опись, таблица, карточка, связи (UI-151, UI-161)', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  const MARKER = 'Ключ вне markdown (UI-151, служебная задача сценария)';
  const key = await create(request, MARKER);
  const other = await create(request, 'Связанная задача для замера ключа в блоке «Связи» (UI-161)');

  try {
    await link(request, key, other);

    /*
     * Опись дела: заголовок «Ответ на KEY#N» несёт ссылку на запись вопроса — заводится
     * сама, а не берётся из демо: состав демо меняется, а заголовок нужен здесь заведомо,
     * не по счастливой случайности. Название вопроса намеренно НЕ содержит фразу «Ответ
     * на»: она — заголовок, который трекер сам соберёт для записи-ответа ниже, и если
     * вопрос назвать ею же, поиск кнопки описи по тексту находит не ту строку (ровно это
     * и произошло разок в реальном прогоне: `.find()` брал первую попавшуюся кнопку
     * с этой фразой — заголовок вопроса, — а не заголовок ответа, и следующий локатор
     * ждал вложенный `code.font-mono`, которого там нет, до тайм-аута теста).
     */
    const questionResponse = await request.post(`/api/v1/tasks/${key}/entries`, {
      headers: { ...auth(), 'X-Actor-Label': 'ui151_probe' },
      data: {
        type: 'question',
        title: 'Проверка заголовка описи для записи-ответа',
        body: 'Нужен ответ.',
        payload: { addressees: ['owner'], blocking: false },
      },
    });
    expect(questionResponse.status()).toBe(201);
    const questionNo = ((await questionResponse.json()) as { data: { no: number } }).data.no;

    const answerResponse = await request.post(`/api/v1/tasks/${key}/entries`, {
      headers: { ...auth(), 'X-Actor-Label': 'ui151_probe' },
      data: { type: 'answer', body: 'Ответ.', payload: { question_no: questionNo } },
    });
    expect(answerResponse.status()).toBe(201);

    await silenceJournal(page);
    await page.setViewportSize({ width: 390, height: 844 });

    /*
     * Таблица (карточка на узком экране — строка-карточка, UI-134): ключ в своей ячейке.
     * Строка отбирается по названию своей задачи (`text`, ищет в названии и описании,
     * `e2e/AGENTS.md`), а не берётся первой строкой очереди: очередь DEMO — общий контур
     * сквозных сценариев, к этому месту в прогоне в ней уже десятки задач от других
     * пишущих сценариев, и первая строка — чужая случайность, а не то, что проверяет
     * UI-151.
     */
    await page.goto(`/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}`);
    await expect(page.getByRole('table')).toBeVisible();
    expect(await rowKeyStyle(page, key)).toBe('nowrap');

    // Карточка задачи: ключ в шапке рядом с названием, и опись под ней.
    await page.goto(`/tasks/${key}`);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(key);

    const styles = await taskPageKeyStyles(page);
    // Строка описи с заголовком «Ответ на» на месте: сам факт присутствия, а не число
    // строк описи — это не предмет задачи UI-151.
    expect(styles.headlineKey, JSON.stringify(styles)).not.toBeNull();
    expect(styles).toEqual({ headerKey: 'nowrap', headlineKey: 'nowrap' });

    /*
     * Блок «Связи» (UI-161): та же карточка уже открыта, связь с `other` заведена
     * выше. Обе границы полосы телефонных ширин, которую интерфейс держит и в других
     * местах (320–390 px, `narrow.spec.ts`, `BAND`) — ключ связи не должен
     * разъезжаться переносом ни на одной из них.
     */
    await expect(page.getByRole('region', { name: 'Связи' }).getByText(other)).toBeVisible();
    for (const width of [390, 320] as const) {
      await page.setViewportSize({ width, height: 844 });
      await fontsReady(page);
      const measure = await linksKeyMeasure(page, other);
      expect(measure, `${width}px`).toEqual({ rectCount: 1, whiteSpace: 'nowrap' });
    }
  } finally {
    await cancel(request, other);
    await cancel(request, key);
  }
});
