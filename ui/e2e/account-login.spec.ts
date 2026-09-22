import AxeBuilder from '@axe-core/playwright';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { E2E_EMAIL, E2E_PASSWORD, LOGIN_URL, readE2eToken, side } from './contour';

/**
 * Режим входа по учётным записям (`TRK-113`) — настоящий nginx образа и настоящий API, без
 * подмен. Второй экземпляр интерфейса поднимает `global-setup.ts` одноразовым контейнером
 * службы `ui` в режиме входа; бэкенд у него общий с основным. Учётная запись —
 * администратор `owner@localhost`: пароль `E2E_PASSWORD` перенесён в неё из
 * `TRACKER_PASSWORD_HASH` контура, как у установки, обновлённой с прежнего пароля.
 *
 * Здесь проверяется то, чего не видит страничный тест: что `/config.json` не отдаёт ключа
 * никому, что кука приходит `HttpOnly`, что по ней токен сеанса приезжает после
 * перезагрузки, и что выход гасит сеанс на сервере, а не только в браузере. Два человека в
 * двух браузерах и управление людьми — `people.spec.ts`.
 */
test.use({ baseURL: LOGIN_URL });

const SESSION_COOKIE = 'casefile_session';

async function sessionCookie(context: BrowserContext) {
  return (await context.cookies()).find((cookie) => cookie.name === SESSION_COOKIE);
}

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.getByLabel('Почта').fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
}

test('ключа нет никому: /config.json отвечает 401 и называет вход', async ({ request }) => {
  const config = await request.get('/config.json');

  expect(config.status()).toBe(401);
  expect(await config.json()).toEqual({ login: 'password' });
  expect(config.headers()['cache-control']).toBe('no-store');
});

test('чужой Host получает страницу, но не ключ', async ({ request }) => {
  const host = { Host: `casefile.example.org:${new URL(LOGIN_URL).port}` };

  expect((await request.get('/', { headers: host })).status()).toBe(200);
  const config = await request.get('/config.json', { headers: host });
  expect(config.status()).toBe(401);
  expect(await config.text()).not.toContain(readE2eToken());
});

test('экран входа спрашивает почту и пароль, а не токен и не пароль установки', async ({
  page,
}) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText('Войдите своей почтой и паролем.')).toBeVisible();
  await expect(page.getByLabel('Почта')).toHaveAttribute('type', 'email');
  await expect(page.getByLabel('Пароль', { exact: true })).toHaveAttribute('type', 'password');
  await expect(page.getByLabel('Токен участника')).toHaveCount(0);
  await expect(page.getByLabel('Пароль установки')).toHaveCount(0);
});

test('неверный пароль отказывает словами входа и куки не ставит', async ({ page, context }) => {
  await page.goto('/login');
  await signIn(page, E2E_EMAIL, 'certainly not the password');

  await expect(page.getByRole('alert')).toHaveText('Почта или пароль не подошли.');
  expect(await sessionCookie(context)).toBeUndefined();
});

test('вход отдаёт свой токен сеанса, он переживает перезагрузку, выход гасит его на сервере', async ({
  page,
  context,
}) => {
  await page.goto('/login');
  await signIn(page, E2E_EMAIL, E2E_PASSWORD);

  await expect(page).toHaveURL(/\/tasks/);
  await expect(side(page).getByText('owner', { exact: true })).toBeVisible();
  await expect(side(page).getByRole('link', { name: /owner@localhost/ })).toBeVisible();

  // Кука сеанса скрипту не видна, едет только в запросах своего источника.
  const cookie = await sessionCookie(context);
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Strict', path: '/' });
  expect(await page.evaluate(() => document.cookie)).not.toContain(SESSION_COOKIE);

  // Токен сеанса — свой, а не ключ установки: тот `/config.json` не отдаёт и после входа.
  const config = await page.request.get('/config.json');
  expect(config.status()).toBe(401);
  const session = await page.request.get('/api/v1/session');
  expect(session.status()).toBe(200);
  const token = ((await session.json()) as { data: { token: string } }).data.token;
  expect(token).not.toBe(readE2eToken());

  // Пароль нигде в браузере не оседает, токен — тоже: он живёт в памяти вкладки.
  const stored = await page.evaluate(() =>
    JSON.stringify({ ...window.localStorage, ...window.sessionStorage }),
  );
  expect(stored).not.toContain(E2E_PASSWORD);
  expect(stored).not.toContain(token);

  // Перезагрузка вкладки не спрашивает пароль снова: токен приезжает по куке.
  await page.reload();
  await expect(side(page).getByText('owner', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Почта')).toHaveCount(0);

  // Выход закрывает сеанс на сервере: кука, сохранённая до выхода, больше не годна, а
  // токен сеанса отозван сразу, а не на следующей перезагрузке.
  const kept = cookie?.value ?? '';
  await side(page).getByRole('button', { name: 'Выйти' }).click();
  await expect(page.getByLabel('Почта')).toBeVisible();
  expect(await sessionCookie(context)).toBeUndefined();

  const replayed = await page.request.get('/api/v1/session', {
    headers: { Cookie: `${SESSION_COOKIE}=${kept}` },
  });
  expect(replayed.status()).toBe(401);
  const revoked = await page.request.get('/api/v1/bootstrap', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(revoked.status()).toBe(401);
});

test('доступность экрана входа', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByLabel('Почта')).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
