import { expect, test, type Locator, type Page } from '@playwright/test';
import { silenceJournal } from './contour';

/*
 * UI-155: ссылка на запись дела — адрес, который открывается в браузере, одним нажатием
 * из описи карточки и из ленты дела; прежнее «Скопировать KEY#N» остаётся как было.
 *
 * Буфер читается из самой страницы (`navigator.clipboard.readText`), поэтому контексту
 * даны права на чтение и запись — как в `connect.spec.ts`.
 */
test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

const KEY = 'DEMO-6';
/** Запись с телом: вердикт по второй проверке. Номер берётся из описи, а не вписан. */
const TITLE = 'Обзорная проверка 2';

function entryRow(page: Page, title: string): Locator {
  return page.getByRole('row').filter({ has: page.getByRole('button', { name: title }) });
}

async function entryNo(page: Page): Promise<number> {
  await page.goto(`/tasks/${KEY}`);
  return Number((await entryRow(page, TITLE).getByRole('rowheader').innerText()).trim());
}

/**
 * Кнопка видна без наведения: указатель уведён в угол, и кнопка всё равно видна и не
 * прозрачна; на телефоне её мишень не меньше 24 px (UI-154).
 */
async function visibleWithoutHover(page: Page, button: Locator, width: number): Promise<void> {
  await page.mouse.move(0, 0);
  await expect(button).toBeVisible();
  expect(await button.evaluate((node) => getComputedStyle(node).opacity)).toBe('1');
  if (width < 600) {
    const box = await button.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(24);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(24);
  }
}

/** Скопированный адрес открывает карточку в новой странице на раскрытой записи `no`. */
async function opensExpanded(page: Page, no: number): Promise<void> {
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  const origin = new URL(page.url()).origin;
  expect(copied).toBe(`${origin}/tasks/${KEY}?entry=${no}`);

  const fresh = await page.context().newPage();
  await silenceJournal(fresh);
  await fresh.goto(copied);
  await expect(
    entryRow(fresh, TITLE).getByRole('button', { name: new RegExp(TITLE) }),
  ).toHaveAttribute('aria-expanded', 'true');
  expect(Number((await entryRow(fresh, TITLE).getByRole('rowheader').innerText()).trim())).toBe(no);
  // Тело раскрытой записи пришло: текст проверки берётся по номеру из задачи.
  await expect(fresh.getByRole('cell').filter({ hasText: 'Неприменимый оператор' })).toBeVisible();
  await fresh.close();
}

for (const width of [1280, 390]) {
  test.describe(`ширина ${width}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test('опись карточки: знак у записи кладёт в буфер адрес, который открывает её раскрытой', async ({
      page,
    }) => {
      await silenceJournal(page);
      const no = await entryNo(page);

      // Действие есть у свёрнутой записи: раскрывать её, чтобы поделиться, не нужно.
      const row = entryRow(page, TITLE);
      await expect(row.getByRole('button', { name: new RegExp(TITLE) })).toHaveAttribute(
        'aria-expanded',
        'false',
      );
      const link = row.getByRole('button', { name: `Скопировать ссылку на запись #${no}` });
      await visibleWithoutHover(page, link, width);

      await link.click();
      await expect(row.getByRole('status')).toHaveText('Ссылка на запись скопирована');
      // Нажатие не раскрыло запись: копирование и раскрытие — разные действия.
      await expect(row.getByRole('button', { name: new RegExp(TITLE) })).toHaveAttribute(
        'aria-expanded',
        'false',
      );
      await opensExpanded(page, no);
    });

    test('лента дела: знак у записи кладёт в буфер тот же адрес карточки', async ({ page }) => {
      await silenceJournal(page);
      const no = await entryNo(page);
      await page.goto(`/tasks/${KEY}/case`);

      const entry = page.getByRole('article', { name: `${KEY}#${no}`, exact: true });
      const link = entry.getByRole('button', { name: `Скопировать ссылку на запись #${no}` });
      await visibleWithoutHover(page, link, width);

      await link.click();
      await expect(entry.getByRole('status')).toHaveText('Ссылка на запись скопирована');
      await opensExpanded(page, no);
    });
  });
}

test('прежнее «Скопировать KEY#N» кладёт текстовую ссылку, как раньше', async ({ page }) => {
  await silenceJournal(page);
  const no = await entryNo(page);
  await page.goto(`/tasks/${KEY}/case`);

  const entry = page.getByRole('article', { name: `${KEY}#${no}`, exact: true });
  await entry.getByRole('button', { name: `Скопировать ${KEY}#${no}` }).click();
  // Рядом живёт и статус ссылки-адреса (пустой): берём тот, что сказал о копировании.
  await expect(entry.getByRole('status').filter({ hasText: /^скопировано$/ })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${KEY}#${no}`);
});

test.describe('буфер обмена недоступен', () => {
  // Так страница выглядит на сервере по голому http: `navigator.clipboard` нет вовсе.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, 'clipboard', { get: () => undefined });
    });
  });

  test('обе кнопки говорят об отказе словами, а не молчат', async ({ page }) => {
    await silenceJournal(page);
    const no = await entryNo(page);

    const row = entryRow(page, TITLE);
    await row.getByRole('button', { name: `Скопировать ссылку на запись #${no}` }).click();
    await expect(row.getByRole('status')).toHaveText('буфер обмена недоступен');
    await expect(row.getByRole('status')).toBeVisible();

    await page.goto(`/tasks/${KEY}/case`);
    const entry = page.getByRole('article', { name: `${KEY}#${no}`, exact: true });
    await entry.getByRole('button', { name: `Скопировать ссылку на запись #${no}` }).click();
    await entry.getByRole('button', { name: `Скопировать ${KEY}#${no}` }).click();
    const statuses = entry.getByRole('status');
    await expect(statuses).toHaveCount(2);
    for (const status of await statuses.all()) {
      await expect(status).toHaveText('буфер обмена недоступен');
      await expect(status).toBeVisible();
    }
  });
});
