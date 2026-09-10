import { expect, test, type Page } from '@playwright/test';
import { readE2eToken, side } from './contour';

const token = readE2eToken();

/**
 * Ключ от установки в настоящем браузере и на собранном образе.
 *
 * Файл конфигурации кладёт рядом со статикой контур (`UI-75`), и здесь он подменяется
 * перехватом запроса: проверяется сторона приложения — берёт ли оно ключ, ждёт ли
 * ответа, убирает ли выход. Ответ отдаётся с задержкой: без неё «страж дождался»
 * ничем не отличалось бы от «страж успел».
 */
async function installGives(page: Page, body: string, delayMs = 300): Promise<void> {
  await page.route('**/config.json', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    await route.fulfill({ contentType: 'application/json', body });
  });
}

test('с ключом от установки первый экран — задачи, и входа не было ни на кадр', async ({
  page,
}) => {
  await installGives(page, JSON.stringify({ token }));

  const seenLogin: string[] = [];
  page.on('framenavigated', (frame) => seenLogin.push(frame.url()));

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Задачи' })).toBeVisible();
  await expect(side(page).getByText('owner')).toBeVisible();

  // Ни поля токена, ни адреса `/login` — человек ключа не видел и не вводил.
  await expect(page.getByLabel('Токен участника')).toHaveCount(0);
  expect(seenLogin.filter((url) => url.includes('/login'))).toEqual([]);
  expect(page.url()).toContain('/tasks');

  // Выхода нет: человек не входил, и возвращать его на тот же экран незачем.
  await expect(side(page).getByRole('button', { name: 'Выйти' })).toHaveCount(0);

  // Ключ живёт в памяти вкладки: перезагрузка спросит установку заново.
  expect(await page.evaluate(() => window.localStorage.getItem('tracker.token'))).toBeNull();

  // Живой поток подхватил тот же ключ: заголовок собирается одной функцией на все пути.
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
});

test('медленная конфигурация не даёт вспышки входа', async ({ page }) => {
  // Полторы секунды — заведомо больше, чем занимает первая отрисовка.
  await installGives(page, JSON.stringify({ token }), 1_500);

  await page.goto('/', { waitUntil: 'commit' });

  // Пока установку спрашивают, экрана входа нет: он появился бы враньём — ключ есть.
  await expect(page.getByLabel('Токен участника')).toHaveCount(0);
  await page.waitForTimeout(700);
  await expect(page.getByLabel('Токен участника')).toHaveCount(0);

  await expect(page.getByRole('heading', { name: 'Задачи' })).toBeVisible({ timeout: 10_000 });
});

test('пустая конфигурация оставляет прежний путь: экран входа и выход на месте', async ({
  page,
}) => {
  // Объект без ключа — то же самое, что отсутствие файла: так выглядит установка,
  // где людей несколько и ключ у каждого свой.
  await installGives(page, '{}');

  await page.goto('/');

  await expect(page.getByLabel('Токен участника')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);

  await page.getByLabel('Токен участника').fill(token);
  await page.getByRole('button', { name: 'Войти' }).click();

  await expect(page).toHaveURL(/\/tasks$/);
  await expect(side(page).getByRole('button', { name: 'Выйти' })).toBeVisible();
});

test('без файла конфигурации образ отдаёт страницу, и это тоже «ключа нет»', async ({ page }) => {
  // Перехвата здесь нет: `/config.json` идёт к nginx как есть. Одностраничное
  // приложение отвечает на неизвестный путь разметкой `index.html`, а не `404`, —
  // и ветка «ключа нет» обязана держаться на неразборчивом теле, а не на коде ответа.
  const response = await page.request.get('/config.json');
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('<!doctype html>');

  await page.goto('/');

  await expect(page.getByLabel('Токен участника')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
