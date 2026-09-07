import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { compose, fontsReady, readE2eToken } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

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

    await expect(bar(page)).toContainText('Изменилось задач: 1');

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

    // Приоритет и теги в дело не подшиваются записью агента — с TRK-7 они приходят
    // отдельным родом события (`field_changed`). Провалиться мимо полосы он не вправе.
    const patched = await request.patch(`/api/v1/tasks/${key}`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { priority: was },
    });
    expect(patched.status()).toBe(200);

    await expect(bar(page)).toContainText('Изменилось задач: 1');
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
    await expect(bar(page)).toContainText('Изменилось задач: 1');
    expect(await keys(page)).toEqual(before.keys);
    expect(await tops(page)).toEqual(before.tops);
  });

  test('новая запись на открытой карточке появляется сама, не сбивая прокрутку', async ({
    page,
    request,
  }) => {
    await page.goto('/tasks/DEMO-3');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-3');

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
