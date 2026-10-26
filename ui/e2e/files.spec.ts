import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { compose, side } from './contour';

/**
 * «Файлы» (TRK-739, слово владельца TRK~8#4): все файлы установки одним списком — загрузка,
 * поиск по имени, сортировка, отбор по типу, замена, скачивание, удаление выбранных и
 * всех отобранных с подтверждением числом. Настоящие nginx и API, без подмен.
 *
 * Сценарий пишущий — кладёт и стирает файлы общей установки — и идёт проектом «запись».
 * Все файлы носят метку прогона в имени, а чистит за собой сам сценарий: соседние
 * сценарии не должны видеть чужие файлы.
 */

/** PNG 1×1: настоящее изображение, чтобы окно «Открыть» показало картинку, а не битый значок. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);
const PDF = Buffer.from('%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n', 'utf8');
/** 2 МиБ: больше 1 МиБ, которыми nginx по умолчанию отвечает `413`. */
const BIG = Buffer.alloc(2 * 1024 * 1024, 'a');

function card(page: Page, name: string) {
  return page.getByRole('article', { name: `Файл ${name}`, exact: true });
}

async function upload(
  page: Page,
  file: { name: string; mimeType: string; buffer: Buffer },
): Promise<void> {
  await page.getByRole('button', { name: 'Загрузить файл' }).click();
  const dialog = page.getByRole('dialog', { name: 'Загрузить файл' });
  await dialog.getByLabel('Файл', { exact: true }).setInputFiles(file);
  await dialog.getByRole('button', { name: 'Загрузить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(card(page, file.name)).toBeVisible();
}

async function choose(page: Page, field: string, option: string): Promise<void> {
  await page.getByRole('combobox', { name: field }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

async function fitsWidth(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
}

test('загрузить, найти, отсортировать, отобрать, заменить, скачать, удалить', async ({ page }) => {
  const stamp = `e2e${Date.now().toString(36)}`;
  const png = `${stamp}-scheme.png`;
  const png2 = `${stamp}-second.png`;
  const pdf = `${stamp}-report.pdf`;
  const big = `${stamp}-big.txt`;

  // Консоль и сеть без ошибок: страница не должна ни писать в консоль об ошибках, ни
  // получать отказы, которых сценарий не ждёт (все отказы здесь — ошибка).
  const problems: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console: ${message.text()}`);
  });
  page.on('pageerror', (error) => problems.push(`page: ${error.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400) problems.push(`${response.status()} ${response.url()}`);
  });

  await page.goto('/tasks');
  await side(page).getByRole('link', { name: 'Файлы' }).click();
  await expect(page).toHaveURL(/\/files$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Файлы' })).toBeVisible();

  try {
    // Загрузка: PNG, PDF, второй PNG и файл больше мегабайта (nginx не режет его на 413).
    await upload(page, { name: png, mimeType: 'image/png', buffer: PNG });
    await upload(page, { name: pdf, mimeType: 'application/pdf', buffer: PDF });
    await upload(page, { name: png2, mimeType: 'image/png', buffer: PNG });
    await upload(page, { name: big, mimeType: 'text/plain', buffer: BIG });

    const loaded = card(page, big);
    await expect(loaded.locator('[data-role="size"]')).toHaveText(/2 МБ/);
    await expect(loaded.locator('[data-role="opened"]')).toHaveText('Не открывали');

    // Поиск по имени: ровно один файл; поле и адрес согласны.
    const search = page.getByRole('searchbox', { name: 'Поиск по имени' });
    await search.fill(`${stamp}-scheme`);
    await expect(page).toHaveURL(new RegExp(`q=${stamp}-scheme`));
    await expect(page.getByRole('article')).toHaveCount(1);
    await expect(card(page, png)).toBeVisible();

    // Метка прогона: все четыре; порядок по умолчанию — свежие первыми.
    await search.fill(stamp);
    await expect(page.getByRole('article')).toHaveCount(4);
    await expect(page.getByRole('article').first()).toHaveAccessibleName(`Файл ${big}`);

    // Сортировка по размеру: крупный первым, обратное направление — мелкий.
    await choose(page, 'Сортировать по', 'Размеру');
    await expect(page).toHaveURL(/sort=size/);
    await expect(page.getByRole('article').first()).toHaveAccessibleName(`Файл ${big}`);
    await page.getByRole('button', { name: /^Порядок: По убыванию$/ }).click();
    await expect(page).toHaveURL(/order=asc/);
    await expect(page.getByRole('article').last()).toHaveAccessibleName(`Файл ${big}`);

    // Отбор по типу: изображения — два PNG.
    await choose(page, 'Тип', 'Изображения');
    await expect(page).toHaveURL(/type=image/);
    await expect(page.getByRole('article')).toHaveCount(2);

    // Открыть изображение: окно показывает настоящую картинку (байты через fetch в blob:).
    await card(page, png).getByRole('button', { name: 'Открыть' }).click();
    const preview = page.getByRole('dialog', { name: png });
    const image = preview.getByRole('img', { name: `Изображение ${png}` });
    await expect(image).toBeVisible();
    expect(await image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(1);
    await preview.getByRole('button', { name: 'Закрыть' }).click();
    await expect(card(page, png).locator('[data-role="opened"]')).not.toHaveText('Не открывали');

    // Удалить выбранный: окно называет число, файл исчезает, второй PNG на месте.
    await card(page, png).getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Удалить выбранные' }).click();
    const picked = page.getByRole('alertdialog');
    await expect(picked.getByText('Удалить 1 файл?')).toBeVisible();
    await picked.getByRole('button', { name: 'Удалить', exact: true }).click();
    await expect(card(page, png)).toHaveCount(0);
    await expect(card(page, png2)).toBeVisible();

    // Загрузить ещё один PNG, чтобы под отбор попало два: число в окне не единица.
    const png3 = `${stamp}-third.png`;
    await upload(page, { name: png3, mimeType: 'image/png', buffer: PNG });
    await expect(page.getByRole('article')).toHaveCount(2);

    // Удалить все отобранные: окно считает файлы под фильтр, подтверждение — отметка с числом.
    await page.getByRole('button', { name: 'Удалить все отобранные' }).click();
    const all = page.getByRole('alertdialog');
    await expect(all.getByText('Удалить все 2 файла, отобранные фильтром?')).toBeVisible();
    const confirm = all.getByRole('button', { name: 'Удалить', exact: true });
    await expect(confirm).toBeDisabled();
    await all.getByRole('checkbox', { name: 'Удаляю ровно 2' }).check();
    await confirm.click();
    await expect(page.getByText('Под поиск и фильтры не подошёл ни один файл.')).toBeVisible();

    // Остались PDF и большой текст. Заменить PDF: размер меняется, ссылка и имя те же.
    await page.getByRole('button', { name: 'Сбросить' }).click();
    await search.fill(stamp);
    await expect(page.getByRole('article')).toHaveCount(2);
    const before = await card(page, pdf).locator('[data-role="size"]').textContent();
    await card(page, pdf).getByRole('button', { name: 'Заменить' }).click();
    const replacing = page.getByRole('dialog', { name: `Заменить ${pdf}` });
    await replacing.getByLabel('Новый файл').setInputFiles({
      name: 'other.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.concat([PDF, Buffer.alloc(4096, 'x')]),
    });
    await replacing.getByRole('button', { name: 'Заменить', exact: true }).click();
    await expect(replacing).toHaveCount(0);
    await expect(card(page, pdf).locator('[data-role="size"]')).not.toHaveText(before ?? '');
    await expect(card(page, pdf).locator('[data-role="replaced"]')).toBeVisible();

    // Скачать: браузер получает файл с исходным именем.
    const download = page.waitForEvent('download');
    await card(page, pdf).getByRole('button', { name: 'Скачать' }).click();
    expect((await download).suggestedFilename()).toBe(pdf);

    // Удалить один из карточки: окно спрашивает, файл исчезает.
    await card(page, pdf).getByRole('button', { name: 'Удалить' }).click();
    await page
      .getByRole('alertdialog', { name: `Удалить ${pdf}?` })
      .getByRole('button', { name: 'Удалить', exact: true })
      .click();
    await expect(card(page, pdf)).toHaveCount(0);

    // Экран без нарушений доступности и без бокового перелива на телефоне.
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await fitsWidth(page)).toBe(true);
    await expect(card(page, big).getByRole('button', { name: 'Скачать' })).toBeVisible();
    await page.getByRole('button', { name: 'Загрузить файл' }).click();
    const phone = page.getByRole('dialog', { name: 'Загрузить файл' });
    await expect(phone.getByRole('button', { name: 'Загрузить', exact: true })).toBeVisible();
    expect(await fitsWidth(page)).toBe(true);
    await phone.getByRole('button', { name: 'Закрыть' }).click();
    expect(problems).toEqual([]);
  } finally {
    // Уборка: всё, что носит метку прогона, — одним удалением по отбору.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/files?q=${stamp}`);
    const left = await page.getByRole('article').count();
    if (left > 0) {
      await page.getByRole('button', { name: 'Удалить все отобранные' }).click();
      const dialog = page.getByRole('alertdialog');
      await dialog.getByRole('checkbox').check();
      await dialog.getByRole('button', { name: 'Удалить', exact: true }).click();
      await expect(page.getByRole('article')).toHaveCount(0);
    }
  }
});

/**
 * «Давно не открывали» (TRK-754, слово владельца TRK~8#12, вариант «Б»): метка у изображений,
 * отбор в адресе, число отобранных, удаление с подтверждением числа. Срок — настройка
 * `file_unopened_days` (минимум 1 день, умолчание 90), а добавленный сейчас файл за сутки не
 * состарить, поэтому сценарий сдвигает `created_at` загруженных файлов прямо в базе контура
 * (`docker compose exec db psql`): отсчёт признака идёт от добавления, пока файл не открывали.
 */
function age(names: string[], days: number): void {
  const list = names.map((name) => `'${name}'`).join(', ');
  compose([
    'exec',
    '-T',
    'db',
    'psql',
    '-U',
    'tracker',
    '-d',
    'tracker',
    '-c',
    `UPDATE files SET created_at = now() - interval '${days} days' WHERE name IN (${list})`,
  ]);
}

test('давно не открывали: метка, отбор, число, удаление с подтверждением и расхождение числа', async ({
  page,
}) => {
  const stamp = `e2u${Date.now().toString(36)}`;
  const oldA = `${stamp}-old-a.png`;
  const oldB = `${stamp}-old-b.png`;
  const fresh = `${stamp}-fresh.png`;
  const doc = `${stamp}-old-doc.pdf`;

  const problems: string[] = [];
  const bytesReads: string[] = [];
  const deletions: string[] = [];
  page.on('console', (message) => {
    // Браузер сам пишет в консоль ожидаемое 409 расхождения числа; сам отказ сверяет ответ ниже.
    if (message.type() === 'error' && !/status of 409/.test(message.text())) {
      problems.push(`console: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`page: ${error.message}`));
  page.on('request', (request) => {
    if (/\/api\/v1\/files\/[^/]+\/content/.test(request.url())) bytesReads.push(request.url());
  });
  await page.route('**/api/v1/files/delete', async (route) => {
    deletions.push(route.request().postData() ?? '');
    await route.continue();
  });
  page.on('response', (response) => {
    // Единственный ожидаемый отказ — расхождение числа при удалении (409).
    if (response.status() >= 400 && response.status() !== 409) {
      problems.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto('/files');
  try {
    await upload(page, { name: oldA, mimeType: 'image/png', buffer: PNG });
    await upload(page, { name: oldB, mimeType: 'image/png', buffer: PNG });
    await upload(page, { name: fresh, mimeType: 'image/png', buffer: PNG });
    await upload(page, { name: doc, mimeType: 'application/pdf', buffer: PDF });
    // Состарить двух изображений и документ; документ метки не получает никогда.
    age([oldA, oldB, doc], 200);

    await page.goto(`/files?q=${stamp}`);
    await expect(page.getByRole('article')).toHaveCount(4);
    const mark = (name: string) => card(page, name).locator('[data-role="unopened"]');
    await expect(mark(oldA)).toHaveText('Давно не открывали');
    await expect(mark(oldB)).toHaveText('Давно не открывали');
    await expect(mark(fresh)).toHaveCount(0);
    await expect(mark(doc)).toHaveCount(0);

    // Отбор: переключатель пишет адрес; в списке два изображения, число названо, срок виден.
    await page.getByRole('checkbox', { name: 'Давно не открывали' }).click();
    await expect(page.getByRole('checkbox', { name: 'Давно не открывали' })).toBeChecked();
    await expect(page).toHaveURL(/unopened=1/);
    await expect(page.getByRole('article')).toHaveCount(2);
    await expect(page.locator('[data-role="unopened-count"]')).toHaveText(
      'Давно не открывали: 2 изображения',
    );
    await expect(page.locator('[data-role="unopened-term"]')).toContainText('90 дней');
    const settingsLink = page.getByRole('link', { name: /меняется в «Настройках»/ });
    await expect(settingsLink).toHaveAttribute('href', '/settings');

    // Список — не открытие: ни одно изображение не читалось байтами (иначе признак бы слетел).
    expect(bytesReads).toEqual([]);

    // Расхождение числа: пока окно открыто, третье изображение состарилось. Ничего не удалено.
    await page.getByRole('button', { name: 'Удалить все давно не открытые' }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByText('Удалить все 2 файла, отобранные фильтром?')).toBeVisible();
    await dialog.getByRole('checkbox', { name: 'Удаляю ровно 2' }).check();
    age([fresh], 200);
    await dialog.getByRole('button', { name: 'Удалить', exact: true }).click();
    await expect(
      dialog.getByText(/число подходящих файлов стало 3: ничего не удалено/),
    ).toBeVisible();
    expect(JSON.parse(deletions[0] ?? '{}')).toEqual({
      expected_count: 2,
      unopened: true,
      q: stamp,
    });
    // Отметка снята, окно называет новое число; все четыре файла на месте.
    await expect(dialog.getByRole('checkbox', { name: 'Удаляю ровно 3' })).not.toBeChecked();
    await expect(dialog.getByText('Удалить все 3 файла, отобранные фильтром?')).toBeVisible();

    // Подтверждаю новое число: удалены три изображения, документ цел.
    await dialog.getByRole('checkbox', { name: 'Удаляю ровно 3' }).check();
    await dialog.getByRole('button', { name: 'Удалить', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect(JSON.parse(deletions[1] ?? '{}')).toEqual({
      expected_count: 3,
      unopened: true,
      q: stamp,
    });
    await expect(page.getByText('Под поиск и фильтры не подошёл ни один файл.')).toBeVisible();
    await page.getByRole('checkbox', { name: 'Давно не открывали' }).click();
    await expect(page.getByRole('checkbox', { name: 'Давно не открывали' })).not.toBeChecked();
    await expect(page.getByRole('article')).toHaveCount(1);
    await expect(card(page, doc)).toBeVisible();

    // Телефон и доступность с включённым отбором.
    await page.goto(`/files?q=${stamp}&unopened=1`);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await fitsWidth(page)).toBe(true);
    await expect(page.locator('[data-role="unopened-term"]')).toBeVisible();
    expect(problems).toEqual([]);
  } finally {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/files?q=${stamp}`);
    const left = await page.getByRole('article').count();
    if (left > 0) {
      await page.getByRole('button', { name: 'Удалить все отобранные' }).click();
      const dialog = page.getByRole('alertdialog');
      await dialog.getByRole('checkbox').check();
      await dialog.getByRole('button', { name: 'Удалить', exact: true }).click();
      await expect(page.getByRole('article')).toHaveCount(0);
    }
  }
});
