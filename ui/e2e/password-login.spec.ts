import AxeBuilder from '@axe-core/playwright';
import { expect, test, type BrowserContext } from '@playwright/test';
import { E2E_PASSWORD, LOGIN_URL, readE2eToken, side } from './contour';

/**
 * Установка, закрытая паролем владельца (`TRK-90`), — настоящий nginx образа и настоящий
 * API, без подмен. Второй экземпляр интерфейса поднимает `global-setup.ts` одноразовым
 * контейнером службы `ui` в режиме пароля; бэкенд у него общий с основным.
 *
 * Здесь проверяется то, чего не видит страничный тест: что `/config.json` за
 * `auth_request` действительно не отдаёт ключ без сеанса, что кука приходит `HttpOnly`,
 * что с ней ключ приезжает и переживает перезагрузку вкладки, и что выход гасит сеанс на
 * сервере, а не только в браузере.
 */
test.use({ baseURL: LOGIN_URL });

const SESSION_COOKIE = 'casefile_session';

async function sessionCookie(context: BrowserContext) {
  return (await context.cookies()).find((cookie) => cookie.name === SESSION_COOKIE);
}

test('без входа ключа нет: /config.json отвечает 401 и называет вход паролем', async ({
  request,
}) => {
  const config = await request.get('/config.json');

  expect(config.status()).toBe(401);
  expect(await config.json()).toEqual({ login: 'password' });
  expect(config.headers()['cache-control']).toBe('no-store');
});

test('чужой Host получает страницу, но не ключ: границу держит кука, а не имя', async ({
  request,
}) => {
  const host = { Host: `casefile.example.org:${new URL(LOGIN_URL).port}` };

  expect((await request.get('/', { headers: host })).status()).toBe(200);
  const config = await request.get('/config.json', { headers: host });
  expect(config.status()).toBe(401);
  expect(await config.text()).not.toContain(readE2eToken());
});

test('закрытая установка спрашивает пароль, а не токен', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText('Эта установка закрыта паролем владельца.')).toBeVisible();
  await expect(page.getByLabel('Пароль установки')).toHaveAttribute('type', 'password');
  await expect(page.getByLabel('Токен участника')).toHaveCount(0);
});

test('неверный пароль отказывает словами входа и куки не ставит', async ({ page, context }) => {
  await page.goto('/login');
  await page.getByLabel('Пароль установки').fill('certainly not the password');
  await page.getByRole('button', { name: 'Войти' }).click();

  await expect(page.getByRole('alert')).toHaveText('Пароль не подошёл.');
  expect(await sessionCookie(context)).toBeUndefined();
});

test('верный пароль отдаёт ключ, сеанс переживает перезагрузку, выход гасит его на сервере', async ({
  page,
  context,
}) => {
  await page.goto('/login');
  await page.getByLabel('Пароль установки').fill(E2E_PASSWORD);
  await page.getByRole('button', { name: 'Войти' }).click();

  await expect(page).toHaveURL(/\/tasks/);
  await expect(side(page).getByText('owner')).toBeVisible();

  // Кука сеанса скрипту не видна, едет только в запросах своего источника.
  const cookie = await sessionCookie(context);
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Strict', path: '/' });
  expect(await page.evaluate(() => document.cookie)).not.toContain(SESSION_COOKIE);
  // Пароль нигде в браузере не оседает, ключ — тоже: он живёт в памяти вкладки.
  const stored = await page.evaluate(() => JSON.stringify({ ...window.localStorage }));
  expect(stored).not.toContain(E2E_PASSWORD);
  expect(stored).not.toContain(readE2eToken());

  // С кукой установка отдаёт ключ — тот же, что у основного экземпляра.
  const config = await page.request.get('/config.json');
  expect(config.status()).toBe(200);
  expect(await config.json()).toEqual({ token: readE2eToken(), login: 'password' });

  // Перезагрузка вкладки не спрашивает пароль снова: ключ приезжает по куке.
  await page.reload();
  await expect(side(page).getByText('owner')).toBeVisible();
  await expect(page.getByLabel('Пароль установки')).toHaveCount(0);

  // Выход закрывает сеанс на сервере: та же кука, сохранённая до выхода, больше не годна.
  const kept = cookie?.value ?? '';
  await side(page).getByRole('button', { name: 'Выйти' }).click();
  await expect(page.getByLabel('Пароль установки')).toBeVisible();
  expect(await sessionCookie(context)).toBeUndefined();

  const replayed = await page.request.get('/config.json', {
    headers: { Cookie: `${SESSION_COOKIE}=${kept}` },
  });
  expect(replayed.status()).toBe(401);
});

test('доступность экрана пароля', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByLabel('Пароль установки')).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
