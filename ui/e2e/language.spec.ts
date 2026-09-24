import { expect, test, type ConsoleMessage, type Page } from '@playwright/test';
import { installWithoutKey } from './contour';

/*
 * Механизм языка: откуда он берётся, что его меняет и что при этом не теряется
 * (UI-77, UI-80).
 *
 * Порядок выбора проверяется четырьмя переходами: язык браузера — английский,
 * русский, неподдержанный (немецкий), и поверх всего — выбор человека, сделанный
 * раньше. Первые три задаются `locale` контекста, четвёртый — записью в
 * `localStorage` до загрузки страницы. Третьего способа нет: параметра `?lang=`
 * у интерфейса не заводится ни для человека, ни ради удобства теста (UI-76).
 *
 * Стадий две. Три перехода проверяются на `/login`: он не требует ни ключа,
 * ни демо-данных, и человек, не понимающий языка интерфейса, видит его первым.
 * Четвёртый — на настоящих экранах: выбор обязан держаться не на одной карточке
 * входа, а во всей оболочке и после перезагрузки.
 *
 * Фразы вписаны сюда руками, а не взяты из словаря: тест, берущий подпись оттуда же,
 * откуда её берёт код, проверяет связь ключа с элементом, но не то, что человек видит
 * английский текст. Здесь проверяется именно это, и потому список фраз короткий —
 * по одной на каждый вид текста экрана.
 */
const ENGLISH = {
  heading: 'Casefile',
  tokenLabel: 'Participant token',
  submit: 'Sign in',
  refusal: 'The token is unknown or revoked.',
};

const RUSSIAN = {
  heading: 'Casefile',
  tokenLabel: 'Токен участника',
  submit: 'Войти',
  refusal: 'Токен неизвестен или отозван.',
};

const LANGUAGE_STORAGE_KEY = 'tracker.language';

/**
 * Открывает экран входа на установке, которая ключа не выдаёт: контур выдаёт ключ всем,
 * и без этой подмены человек попадал бы сразу на задачи, экрана входа не увидев
 * (`e2e/login.spec.ts`).
 */
async function openLogin(page: Page): Promise<void> {
  await installWithoutKey(page);
  await page.goto('/login');
}

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

    await openLogin(page);

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
    await openLogin(page);

    await expect(page.getByRole('heading', { name: RUSSIAN.heading })).toBeVisible();
    await expect(page.getByLabel(RUSSIAN.tokenLabel)).toBeVisible();

    await refuse(page);
    await expect(page.getByRole('alert')).toHaveText(RUSSIAN.refusal);
  });
});

test.describe('язык браузера не поддержан', () => {
  test.use({ locale: 'de-DE' });

  test('немецкий браузер получает английский, а не русский', async ({ page }) => {
    await openLogin(page);

    await expect(page.getByRole('heading', { name: ENGLISH.heading })).toBeVisible();
    await expect(page.getByRole('button', { name: ENGLISH.submit })).toBeVisible();
  });
});

test.describe('выбор человека на экране входа', () => {
  test.use({ locale: 'en-US' });

  test('меняет подписи на месте, не теряя набранного, и переживает перезагрузку', async ({
    page,
  }) => {
    await openLogin(page);

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

test.describe('выбор человека против языка браузера', () => {
  // Браузер русский, а выбор — английский: проверяется, что побеждает выбор.
  test.use({ locale: 'ru-RU' });

  /**
   * Подписи оболочки, а не карточки входа: она стоит на каждом экране, и именно по ней
   * видно, что язык — свойство всего интерфейса, а не одного компонента.
   */
  const SHELL = { sections: 'Casefile sections', projects: 'Projects', inbox: 'Inbox' };

  test('английский из хранилища держится на всех экранах и переживает перезагрузку', async ({
    page,
  }) => {
    /*
     * Выбор сделан раньше — до первой загрузки страницы, как у человека, который
     * однажды нажал на переключатель. Значение ставится только там, где его нет:
     * иначе сценарий переписывал бы хранилище на каждом переходе и не отличил бы
     * «выбор пережил переход» от «его подставили заново».
     */
    await page.addInitScript(
      ([key, value]) => {
        if (window.localStorage.getItem(key) === null) window.localStorage.setItem(key, value);
      },
      [LANGUAGE_STORAGE_KEY, 'en'],
    );

    await page.goto('/tasks?project=DEMO');

    const shell = page.getByRole('complementary', { name: SHELL.sections });
    await expect(shell).toContainText(SHELL.projects);
    await expect(shell).toContainText(SHELL.inbox);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');

    // Карточка задачи и её дело — те же английские подписи, тот же выбор.
    await page.goto('/tasks/DEMO-1');
    await expect(page.getByRole('heading', { name: 'Assignment' })).toBeVisible();

    await page.goto('/tasks/DEMO-1/case');
    await expect(page.getByRole('heading', { name: 'Case DEMO-1' })).toBeVisible();

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Case DEMO-1' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');

    // Язык остался в хранилище и в адрес не уехал ни на одном из переходов.
    expect(await page.evaluate((key) => localStorage.getItem(key), LANGUAGE_STORAGE_KEY)).toBe(
      'en',
    );
    expect(page.url()).not.toContain('lang');

    /*
     * И переключатель оболочки уводит обратно на русский: он тот же самый, что и на
     * входе, и стоит на том же месте экрана (UI-77#12).
     */
    await page.getByRole('combobox', { name: 'Interface language' }).click();
    await page.getByRole('option', { name: 'Русский' }).click();
    await expect(page.getByRole('heading', { name: 'Дело DEMO-1' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  });
});
