import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

/**
 * Причина перехода со ссылкой `KEY#N` рвалась на три строки (UI-159, найдено на демо-
 * контуре витрины mcp.so): текст и «(» на первой строке, ссылка на второй, «)» на
 * третьей. Тело `status_changed` заворачивало `TaskText` (текст со ссылками,
 * `shared/ui/task-text.tsx`) в `<p className={BLOCK}>` — тот же `flex flex-col`, каким
 * `entry-body.tsx` разводит отступом несколько блоков подряд у записи агента. `TaskText`
 * отдаёт фрагмент без обёртки: текст до ссылки, саму ссылку и текст после неё прямыми
 * узлами родителя, — и во флекс-колонке каждый из них становится своим элементом
 * переноса, а не частью одной строки. Причина — обычный абзац, и её узлы обязаны стоять
 * в одной строке, пока текст в неё помещается: `entry-body.tsx` больше не заворачивает
 * её в `BLOCK` (см. коммит задачи).
 *
 * Проверка снимает вертикаль трёх узлов вокруг ссылки — текста перед ней, самой ссылки
 * и текста после — в обоих местах, где причина показана целиком: в ленте дела
 * (`pages/case/ui/case-page.tsx`) и в раскрытой строке описи карточки
 * (`pages/task/ui/task-index.tsx`), — оба идут через один и тот же `EntryBody`, и правка
 * одна на двоих.
 */

const MARKER = 'подтвердить срок вывода старых версий агента';

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

async function create(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      project: 'DEMO',
      title: 'Подопытная задача для причины перехода со ссылкой (UI-159)',
      description: 'Заведена сквозным тестом UI-159: причина `waiting` со ссылкой на запись.',
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

/** Причина рвалась ровно там, где перед ссылкой стоит текст, а после — закрывающая скобка. */
function reasonOf(key: string): string {
  return `Заблокировано владельцем: ${MARKER} (${key}#1)`;
}

async function blockOnOwner(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'waiting', reason: reasonOf(key) },
  });
  expect(response.status()).toBe(200);
}

async function cancel(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-159' },
  });
  if (!response.ok()) {
    await test.info().attach(`уборка ${key} не удалась`, {
      body: await response.text(),
      contentType: 'text/plain',
    });
  }
}

/**
 * Разница верхних краёв меньше кегля — те же строчные боксы; разница в размер строки —
 * разрыв UI-159. Число выбрано с запасом от суб-пиксельных отличий базовой линии между
 * текстовым узлом и ссылкой (доли пикселя — на деле) и с большим запасом до настоящей
 * высоты строки (кегль тела с межстрочным интервалом — от 20 px).
 */
const SAME_LINE_TOLERANCE = 6;

/**
 * Вертикаль трёх узлов вокруг ссылки: текст перед ней, сама ссылка, текст после.
 * `TaskText` кладёт их прямыми соседями в разметке (фрагмент без обёртки), поэтому
 * `previousSibling`/`nextSibling` ссылки — это ровно они, без обхода дерева.
 */
async function reasonLineTops(
  page: Page,
  marker: string,
  refText: string,
): Promise<{ before: number; link: number; after: number } | null> {
  return page.evaluate(
    ({ marker, refText }) => {
      const paragraph = Array.from(document.querySelectorAll('p')).find((element) =>
        (element.textContent ?? '').includes(marker),
      );
      const link = paragraph
        ? Array.from(paragraph.querySelectorAll('a')).find((a) => a.textContent === refText)
        : undefined;
      if (paragraph === undefined || link === undefined) return null;

      const before = link.previousSibling;
      const after = link.nextSibling;
      if (before?.nodeType !== Node.TEXT_NODE || after?.nodeType !== Node.TEXT_NODE) return null;

      const beforeRange = document.createRange();
      beforeRange.selectNodeContents(before);
      const beforeRects = beforeRange.getClientRects();

      const afterRange = document.createRange();
      afterRange.selectNodeContents(after);
      const afterRects = afterRange.getClientRects();

      if (beforeRects.length === 0 || afterRects.length === 0) return null;

      return {
        // Последняя строка текста перед ссылкой: если текста больше одной строки,
        // рядом со ссылкой стоит именно последняя.
        before: beforeRects[beforeRects.length - 1].top,
        link: link.getBoundingClientRect().top,
        // Первая строка текста после ссылки — по той же причине.
        after: afterRects[0].top,
      };
    },
    { marker, refText },
  );
}

test('причина перехода со ссылкой стоит в одну строку в ленте дела и в описи (UI-159)', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  const key = await create(request);
  const refText = `${key}#1`;

  try {
    await blockOnOwner(request, key);

    await silenceJournal(page);
    await page.setViewportSize({ width: 1280, height: 900 });

    // Лента дела: `pages/case/ui/case-page.tsx` → `EntryCard` → `EntryBody`.
    await page.goto(`/tasks/${key}/case`);
    await expect(page.getByText(MARKER)).toBeVisible();
    await expect(page.getByRole('link', { name: refText }).first()).toBeVisible();
    await fontsReady(page);

    const feedTops = await reasonLineTops(page, MARKER, refText);
    expect(feedTops, 'лента дела: узлы вокруг ссылки не найдены рядом').not.toBeNull();
    expect(
      Math.abs(feedTops!.before - feedTops!.link),
      `лента дела: текст перед ссылкой ${JSON.stringify(feedTops)}`,
    ).toBeLessThanOrEqual(SAME_LINE_TOLERANCE);
    expect(
      Math.abs(feedTops!.link - feedTops!.after),
      `лента дела: текст после ссылки ${JSON.stringify(feedTops)}`,
    ).toBeLessThanOrEqual(SAME_LINE_TOLERANCE);

    // Опись карточки: `pages/task/ui/task-index.tsx` → `EntryDetails` → `EntryBody`, та же
    // причина, но раскрытая по клику, а не готовой лентой.
    await page.goto(`/tasks/${key}`);
    await page.getByRole('button', { name: /причиной/ }).click();
    await expect(page.getByText(MARKER)).toBeVisible();
    await fontsReady(page);

    const indexTops = await reasonLineTops(page, MARKER, refText);
    expect(indexTops, 'опись: узлы вокруг ссылки не найдены рядом').not.toBeNull();
    expect(
      Math.abs(indexTops!.before - indexTops!.link),
      `опись: текст перед ссылкой ${JSON.stringify(indexTops)}`,
    ).toBeLessThanOrEqual(SAME_LINE_TOLERANCE);
    expect(
      Math.abs(indexTops!.link - indexTops!.after),
      `опись: текст после ссылки ${JSON.stringify(indexTops)}`,
    ).toBeLessThanOrEqual(SAME_LINE_TOLERANCE);

    // Ссылка ведёт на саму запись (запись №1, «Задача заведена»), а не только выглядит
    // ссылкой.
    expect(await page.getByRole('link', { name: refText }).first().getAttribute('href')).toBe(
      `/tasks/${key}?entry=1`,
    );
  } finally {
    await cancel(request, key);
  }
});
