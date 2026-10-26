import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { E2E_EMAIL, E2E_PASSWORD, LOGIN_URL, side } from './contour';

/**
 * «Настройки» (TRK-749, слово владельца TRK~31#4): семь параметров установки со
 * значением, умолчанием и источником. Администратор правит и сбрасывает значение,
 * остальные видят его без полей ввода. Настоящие nginx и API, без подмен.
 *
 * Сценарий пишущий — меняет настройки общей установки, — поэтому идёт проектом «запись»,
 * после читающих. Каждая правка возвращается в `finally`: страница и обрезка MCP — это
 * настройки живого бэкенда контура, и соседний сценарий не должен читать чужое значение.
 */
const ROWS = [
  'Срок сеанса',
  'Срок подключения агента',
  'Размер страницы MCP',
  'Обрезка текста в MCP',
  'Проверка новых выпусков',
  'Предельный размер файла',
  'Срок изображений без открытия',
];

function row(page: Page, title: string) {
  return page.getByRole('article', { name: title, exact: true });
}

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto(`${LOGIN_URL}/login`);
  await page.getByLabel('Почта').fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/tasks/);
}

/** Страница без бокового перелива: телефон — полноценная цель (UI-134#3). */
async function fitsWidth(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
}

test('на своей машине владелец — администратор: семь строк, правка, сброс', async ({ page }) => {
  await page.goto('/tasks');
  await side(page).getByRole('link', { name: 'Настройки' }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Настройки' })).toBeVisible();

  // Семь строк: название, значение, источник, умолчание, кто менял.
  for (const title of ROWS) await expect(row(page, title)).toBeVisible();
  await expect(page.getByRole('article')).toHaveCount(7);
  const pageSize = row(page, 'Размер страницы MCP');
  await expect(pageSize.locator('[data-role="source"]')).toHaveText(/окружение|умолчание/);
  await expect(pageSize.locator('[data-role="default"]')).toContainText('25');
  await expect(pageSize.locator('[data-role="changed"]')).toContainText('не менялась');

  try {
    // Меняю на 10: значение и источник «база», кто и когда.
    const field = pageSize.getByLabel('Новое значение');
    await field.fill('10');
    await pageSize.getByRole('button', { name: 'Сохранить' }).click();
    await expect(pageSize.locator('[data-role="value"]')).toHaveText(/^10 /);
    await expect(pageSize.locator('[data-role="source"]')).toHaveText('база');
    await expect(pageSize.locator('[data-role="changed"]')).toContainText('owner');

    // Значение пережило перезагрузку: оно в базе, а не в браузере.
    await page.reload();
    await expect(row(page, 'Размер страницы MCP').locator('[data-role="value"]')).toHaveText(
      /^10 /,
    );

    // Отказ вне пределов: текст рядом с полем, прежнее значение цело.
    const limit = row(page, 'Обрезка текста в MCP');
    const before = await limit.locator('[data-role="value"]').textContent();
    await limit.getByLabel('Новое значение').fill('100');
    await limit.getByRole('button', { name: 'Сохранить' }).click();
    await expect(limit.getByRole('alert')).toContainText('Вне пределов');
    await expect(limit.getByRole('alert')).toContainText('200');
    await expect(limit.getByLabel('Новое значение')).toHaveValue('100');
    await expect(limit.locator('[data-role="value"]')).toHaveText(before ?? '');
    await expect(limit.locator('[data-role="source"]')).not.toHaveText('база');

    // Срок вписывается в выбранной единице, предел файла — в мегабайтах.
    const ttl = row(page, 'Срок подключения агента');
    await expect(ttl.getByLabel('Единица')).toHaveValue('days');

    // Сброс: источник снова не «база».
    await row(page, 'Размер страницы MCP')
      .getByRole('button', { name: 'Брать из окружения' })
      .click();
    await expect(row(page, 'Размер страницы MCP').locator('[data-role="source"]')).toHaveText(
      /окружение|умолчание/,
    );
    await expect(row(page, 'Размер страницы MCP').locator('[data-role="value"]')).not.toHaveText(
      /^10 /,
    );
    await expect(
      row(page, 'Размер страницы MCP').getByRole('button', { name: 'Брать из окружения' }),
    ).toHaveCount(0);
  } finally {
    const reset = row(page, 'Размер страницы MCP').getByRole('button', {
      name: 'Брать из окружения',
    });
    if ((await reset.count()) > 0) await reset.click();
  }
});

test('экран без нарушений доступности и без бокового перелива на телефоне', async ({ page }) => {
  await page.goto('/settings');
  await expect(page.getByRole('article')).toHaveCount(7);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await fitsWidth(page)).toBe(true);
  await expect(page.getByRole('button', { name: 'Сохранить' }).first()).toBeVisible();
});

test('в режиме входа администратор правит, товарищ без флага видит значения без полей ввода', async ({
  page,
  browser,
}) => {
  const stamp = Date.now().toString(36);
  const email = `settings-${stamp}@example.com`;
  const name = `settings_${stamp}`;

  await signIn(page, E2E_EMAIL, E2E_PASSWORD);
  await page.goto(`${LOGIN_URL}/people`);
  await page.getByRole('button', { name: 'Завести человека' }).click();
  const form = page.getByRole('dialog', { name: 'Завести человека' });
  await form.getByLabel('Почта').fill(email);
  await form.getByLabel('Имя').fill(name);
  await form.getByRole('button', { name: 'Завести' }).click();
  const once = page.getByRole('dialog', { name: `Учётная запись ${email} заведена` });
  const password = (await once.locator('pre, code').last().textContent())?.trim() ?? '';
  expect(password.length).toBeGreaterThanOrEqual(12);
  await once.getByRole('button', { name: 'Я сохранил' }).click();

  // Администратор: поля и кнопки на месте.
  await page.goto(`${LOGIN_URL}/settings`);
  await expect(page.getByRole('article')).toHaveCount(7);
  await expect(page.getByRole('button', { name: 'Сохранить' })).toHaveCount(7);

  const context = await browser.newContext({ baseURL: LOGIN_URL, locale: 'ru-RU' });
  const mate = await context.newPage();
  try {
    await signIn(mate, email, password);
    await side(mate).getByRole('link', { name: 'Настройки' }).click();
    await expect(mate).toHaveURL(/\/settings$/);

    // Значения видны, объяснение названо, поле ввода и «Сохранить» — нет.
    await expect(mate.getByRole('article')).toHaveCount(7);
    for (const title of ROWS) await expect(row(mate, title)).toBeVisible();
    await expect(
      mate.getByText('Настройки правит администратор установки', { exact: false }),
    ).toBeVisible();
    await expect(mate.getByRole('main').getByRole('textbox')).toHaveCount(0);
    await expect(mate.getByRole('main').getByRole('combobox')).toHaveCount(0);
    await expect(mate.getByRole('button', { name: 'Сохранить' })).toHaveCount(0);
    await expect(mate.getByRole('button', { name: 'Брать из окружения' })).toHaveCount(0);

    const results = await new AxeBuilder({ page: mate }).analyze();
    expect(results.violations).toEqual([]);

    await mate.setViewportSize({ width: 390, height: 844 });
    expect(await fitsWidth(mate)).toBe(true);

    // Прямой запрос правки без флага отказывает: защита на сервере, а не только в экране.
    const refused = await mate.evaluate(async () => {
      const response = await fetch('/api/v1/settings/mcp_page_size', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: '10' }),
      });
      return response.status;
    });
    expect([401, 403]).toContain(refused);
  } finally {
    await context.close();
  }
});
