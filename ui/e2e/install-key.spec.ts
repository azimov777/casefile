import { expect, test, type Page } from '@playwright/test';
import { installWithoutKey, readE2eToken, side } from './contour';

const token = readE2eToken();

/**
 * Ключ от установки в настоящем браузере, на собранном образе и на настоящем контуре.
 *
 * Первый сценарий ничего не подменяет: конфигурацию рядом со статикой положил сам контур
 * (`local-token` выпустил ключ в файл, `docker/config-json.sh` положил его при старте
 * контейнера), и открытый адрес — это в точности путь человека.
 *
 * Остальные подменяют один запрос, чтобы получить то, чего у этого контура нет:
 * медленную конфигурацию, пустую и отсутствующую.
 */
async function installGives(page: Page, body: string, delayMs = 300): Promise<void> {
  await page.route('**/config.json', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    await route.fulfill({ contentType: 'application/json', body });
  });
}

test('открыл адрес — вижу задачи, ничего не вводив', async ({ page }) => {
  // Конфигурация от контура, как её видит браузер. `no-store` — это свой `location`
  // в `docker/nginx.conf.template`: без него ключ приезжал бы из кэша и переживал
  // перевыпуск.
  const config = await page.request.get('/config.json');
  expect(config.status()).toBe(200);
  expect(config.headers()['cache-control']).toBe('no-store');
  expect(((await config.json()) as { token?: string }).token).toBe(token);

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

test('без конфигурации — экран входа, и красной плашки при этом нет', async ({ page }) => {
  // Так отвечает образ, которому ключа не дали: `location = /config.json` отдаёт `404`.
  // Ветка «ключа нет» держится при этом не на коде ответа, а на неразборчивом теле —
  // общее правило одностраничного приложения ответило бы `200` с разметкой.
  await installWithoutKey(page);

  await page.goto('/');

  await expect(page.getByLabel('Токен участника')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
