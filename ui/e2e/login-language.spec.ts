import { expect, test, type ConsoleMessage, type Page } from '@playwright/test';

/*
 * Механизм языка на экране входа: откуда берётся язык, что его меняет и что при этом
 * не теряется (UI-77).
 *
 * Фразы вписаны сюда руками, а не взяты из словаря: тест, берущий подпись оттуда же,
 * откуда её берёт код, проверяет связь ключа с элементом, но не то, что человек видит
 * английский текст. Здесь проверяется именно это, и потому список фраз короткий —
 * по одной на каждый вид текста экрана.
 */
const ENGLISH = {
  heading: 'Tracker',
  tokenLabel: 'Participant token',
  submit: 'Sign in',
  refusal: 'The token is unknown or revoked.',
};

const RUSSIAN = {
  heading: 'Трекер',
  tokenLabel: 'Токен участника',
  submit: 'Войти',
  refusal: 'Токен неизвестен или отозван.',
};

const LANGUAGE_STORAGE_KEY = 'tracker.language';

/** Жалобы `i18next`: пропавший ключ он не роняет, а пишет в журнал. */
function i18nComplaints(messages: ConsoleMessage[]): string[] {
  return messages
    .map((message) => message.text())
    .filter((text) => text.includes('i18next') || text.includes('missingKey'));
}

async function refuse(page: Page): Promise<void> {
  await page.getByRole('textbox').fill('trk_definitely_not_a_token');
  await page.getByRole('button').filter({ hasText: /.+/ }).first().click();
}

test.describe('язык браузера — английский', () => {
  test.use({ locale: 'en-US' });

  test('чистое хранилище: экран входа английский целиком, включая текст отказа', async ({
    page,
  }) => {
    const messages: ConsoleMessage[] = [];
    const requests: string[] = [];
    page.on('console', (message) => messages.push(message));
    page.on('request', (request) => requests.push(request.url()));

    await page.goto('/login');

    await expect(page.getByRole('heading', { name: ENGLISH.heading })).toBeVisible();
    await expect(page.getByLabel(ENGLISH.tokenLabel)).toBeVisible();
    await expect(page.getByRole('button', { name: ENGLISH.submit })).toBeVisible();

    await page.getByLabel(ENGLISH.tokenLabel).fill('trk_definitely_not_a_token');
    await page.getByRole('button', { name: ENGLISH.submit }).click();
    await expect(page.getByRole('alert')).toHaveText(ENGLISH.refusal);

    // Русского на экране нет ни в тексте, ни в подписях для программы чтения с экрана.
    const spoken = await page.evaluate(() => {
      const nodes = Array.from(document.querySelectorAll('[aria-label],[title],[placeholder]'));
      const labels = nodes.flatMap((node) => [
        node.getAttribute('aria-label'),
        node.getAttribute('title'),
        node.getAttribute('placeholder'),
      ]);
      return [document.body.innerText, ...labels].filter((value) => value !== null).join('\n');
    });
    expect(spoken).not.toMatch(/[А-Яа-яЁё]/);

    // Словари вшиты в сборку: за подписями в сеть никто не ходит.
    expect(requests.filter((url) => /locales?|i18n|translation/i.test(url))).toEqual([]);
    expect(i18nComplaints(messages)).toEqual([]);
  });
});

test.describe('язык браузера — русский', () => {
  test.use({ locale: 'ru-RU' });

  test('чистое хранилище: экран входа русский', async ({ page }) => {
    await page.goto('/login');

    await expect(page.getByRole('heading', { name: RUSSIAN.heading })).toBeVisible();
    await expect(page.getByLabel(RUSSIAN.tokenLabel)).toBeVisible();

    await refuse(page);
    await expect(page.getByRole('alert')).toHaveText(RUSSIAN.refusal);
  });
});

test.describe('язык браузера не поддержан', () => {
  test.use({ locale: 'de-DE' });

  test('немецкий браузер получает английский, а не русский', async ({ page }) => {
    await page.goto('/login');

    await expect(page.getByRole('heading', { name: ENGLISH.heading })).toBeVisible();
    await expect(page.getByRole('button', { name: ENGLISH.submit })).toBeVisible();
  });
});

test.describe('выбор человека', () => {
  test.use({ locale: 'en-US' });

  test('меняет подписи на месте, не теряя набранного, и переживает перезагрузку', async ({
    page,
  }) => {
    await page.goto('/login');

    const field = page.getByLabel(ENGLISH.tokenLabel);
    await field.fill('trk_half_typed');

    await page.getByRole('combobox', { name: 'Interface language' }).click();
    await page.getByRole('option', { name: 'Русский' }).click();

    // Подписи сменились сразу: перезагрузки не было, а набранное осталось на месте.
    await expect(page.getByRole('heading', { name: RUSSIAN.heading })).toBeVisible();
    await expect(page.getByLabel(RUSSIAN.tokenLabel)).toHaveValue('trk_half_typed');

    // Выбор живёт в хранилище браузера и никуда больше не уезжает.
    expect(await page.evaluate((key) => localStorage.getItem(key), LANGUAGE_STORAGE_KEY)).toBe(
      'ru',
    );
    expect(page.url()).not.toContain('lang');

    await page.reload();
    await expect(page.getByRole('heading', { name: RUSSIAN.heading })).toBeVisible();
    await expect(page.getByRole('button', { name: RUSSIAN.submit })).toBeVisible();
  });
});
