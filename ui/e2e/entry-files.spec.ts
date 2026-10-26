import { expect, test, type Page } from '@playwright/test';
import { askLegacyOwner, readE2eToken } from './contour';

const token = readE2eToken();

/** PNG 1×1: настоящее изображение, чтобы «Открыть» показало картинку, а не битый значок. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);
const PDF = Buffer.from('%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n', 'utf8');

async function fitsWidth(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
}

/**
 * Вложения к записям человека (TRK-740): ответ с PNG и замечание с PDF. Запись показывает
 * карточку файла, а байты читает только по клику «Открыть» или «Скачать» — чтение байтов
 * для сервера открытие файла (TRK-741). Пишущий сценарий (проект «запись»).
 */
test('ответ с PNG и замечание с PDF: файлы видны в записях, удалённый — «файл удалён»', async ({
  page,
  request,
}) => {
  const stamp = `e2e${Date.now().toString(36)}`;
  const png = `${stamp}-scheme.png`;
  const pdf = `${stamp}-report.pdf`;
  const problems: string[] = [];
  const contentReads: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console: ${message.text()}`);
  });
  page.on('pageerror', (error) => problems.push(`page: ${error.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400) problems.push(`${response.status()} ${response.url()}`);
  });
  page.on('request', (call) => {
    if (call.url().includes('/content')) contentReads.push(call.url());
  });

  const { no: questionNo } = await askLegacyOwner(request, {
    key: 'DEMO-6',
    title: 'Вопрос сквозного теста вложений',
    body: 'Приложите схему.',
  });

  // Ответ с PNG.
  await page.goto(`/tasks/DEMO-6?entry=${questionNo}`);
  await page.getByLabel(/^Ответ$/).fill('Схема во вложении.');
  await page.getByLabel('Выбрать файлы для записи').setInputFiles({
    name: png,
    mimeType: 'image/png',
    buffer: PNG,
  });
  await expect(page.locator('[data-attachment="ready"]')).toContainText(png);
  await page.getByRole('button', { name: 'Ответить' }).click();
  const receipt = page.getByRole('region', { name: `Ответ на DEMO-6#${questionNo} подшит` });
  await expect(receipt).toBeVisible();
  const href = await receipt.getByRole('link', { name: /^DEMO-6#\d+$/ }).getAttribute('href');

  await page.goto(href ?? '');
  const pngItem = page.locator('[data-entry-file]').filter({ hasText: png }).first();
  await expect(pngItem).toBeVisible();
  const pngId = (await pngItem.getAttribute('data-entry-file')) ?? '';
  await expect(pngItem.locator('[data-role="type"]')).toHaveText('image/png');
  await expect(pngItem.getByRole('button', { name: 'Скачать' })).toBeVisible();
  // Лента байтов не читала: картинки нет, пока человек не нажал «Открыть».
  expect(contentReads).toHaveLength(0);
  await expect(pngItem.getByRole('img')).toHaveCount(0);
  await pngItem.getByRole('button', { name: 'Открыть' }).click();
  const image = pngItem.getByRole('img');
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
  expect(contentReads).toHaveLength(1);

  // 390 px: запись с картинкой без горизонтальной прокрутки.
  await page.setViewportSize({ width: 390, height: 800 });
  expect(await fitsWidth(page)).toBe(true);
  await page.setViewportSize({ width: 1280, height: 800 });

  // Замечание с PDF.
  await page.goto('/tasks/DEMO-6');
  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  await page.getByLabel(/^Замечание$/).fill('Отчёт во вложении.');
  await page.getByLabel('Выбрать файлы для записи').setInputFiles({
    name: pdf,
    mimeType: 'application/pdf',
    buffer: PDF,
  });
  await expect(page.locator('[data-attachment="ready"]')).toContainText(pdf);
  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  const remarkReceipt = page.getByRole('region', { name: 'Замечание к DEMO-6 подшито' });
  await expect(remarkReceipt).toBeVisible();
  const remarkHref = await remarkReceipt
    .getByRole('link', { name: /^DEMO-6#\d+$/ })
    .getAttribute('href');

  await page.goto(remarkHref ?? '');
  const pdfItem = page.locator('[data-entry-file]').filter({ hasText: pdf }).first();
  await expect(pdfItem).toBeVisible();
  await expect(pdfItem.getByRole('button', { name: 'Скачать' })).toBeVisible();
  await expect(pdfItem.getByRole('button', { name: 'Открыть' })).toHaveCount(0);
  const pdfId = (await pdfItem.getAttribute('data-entry-file')) ?? '';

  // Удаление файла: запись показывает «файл удалён», кто и когда.
  for (const id of [pdfId, pngId]) {
    const removed = await request.delete(`/api/v1/files/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(removed.status()).toBe(200);
  }
  await page.goto(remarkHref ?? '');
  const gone = page
    .locator('[data-entry-file] [data-role="deleted"]')
    .filter({ hasText: pdf })
    .first();
  await expect(gone).toContainText('Файл удалён');
  await expect(gone).toContainText('Удалил');
  await expect(page.getByRole('button', { name: 'Скачать', exact: true })).toHaveCount(0);

  expect(problems).toEqual([]);
});
