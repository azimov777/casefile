import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Browser, type Page } from '@playwright/test';
import { E2E_EMAIL, E2E_PASSWORD, LOGIN_URL, side } from './contour';

/**
 * Люди установки в режиме входа (`TRK-113`, UI-122): администратор заводит товарища из
 * интерфейса, оба работают одновременно в двух браузерах, выход одного не трогает другого,
 * отключённый больше не входит. Настоящий nginx и настоящий API второго экземпляра
 * интерфейса (`global-setup.ts`), без подмен.
 *
 * Сценарий пишущий — заводит учётную запись, — поэтому идёт проектом «запись», после
 * читающих. Почта и имя товарища уникальны на прогон: контур гасится с базой
 * (`global-teardown.ts`), но повторный запуск без него не должен упираться в занятое.
 */
test.use({ baseURL: LOGIN_URL });

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Почта').fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
}

/** Второй браузер: свой контекст — свои куки, свой токен, другой человек. */
async function secondBrowser(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: LOGIN_URL, locale: 'ru-RU' });
  return context.newPage();
}

/** Сколько задач нашлось на списке: строка счётчика целиком. */
async function found(page: Page): Promise<string> {
  const counter = page.getByText(/^Нашл(ась|ось) \d+ задач/);
  await expect(counter).toBeVisible();
  return (await counter.textContent()) ?? '';
}

test('администратор заводит товарища, оба работают одновременно, отключённый не входит', async ({
  page,
  browser,
}) => {
  const stamp = Date.now().toString(36);
  const email = `mate-${stamp}@example.com`;
  const name = `mate_${stamp}`;

  // Администратор входит и открывает «Люди» из панели.
  await signIn(page, E2E_EMAIL, E2E_PASSWORD);
  await expect(page).toHaveURL(/\/tasks/);
  const adminSees = await found(page);
  await side(page).getByRole('link', { name: 'Люди' }).click();
  await expect(page).toHaveURL(/\/people$/);
  await expect(page.getByRole('article', { name: `Учётная запись ${E2E_EMAIL}` })).toBeVisible();

  // Заводит товарища со сгенерированным паролем и видит пароль один раз.
  await page.getByRole('button', { name: 'Завести человека' }).click();
  const form = page.getByRole('dialog', { name: 'Завести человека' });
  await form.getByLabel('Почта').fill(email);
  await form.getByLabel('Имя').fill(name);
  await form.getByRole('button', { name: 'Завести' }).click();

  const once = page.getByRole('dialog', { name: `Учётная запись ${email} заведена` });
  await expect(once).toBeVisible();
  const password = (await once.locator('pre, code').last().textContent())?.trim() ?? '';
  expect(password.length).toBeGreaterThanOrEqual(12);
  // Пароль не в адресе и не в хранилищах браузера.
  expect(page.url()).not.toContain(password);
  const stored = await page.evaluate(() =>
    JSON.stringify({ ...window.localStorage, ...window.sessionStorage }),
  );
  expect(stored).not.toContain(password);
  await once.getByRole('button', { name: 'Я сохранил' }).click();
  await expect(page.getByText(password)).toHaveCount(0);
  await expect(page.getByRole('article', { name: `Учётная запись ${email}` })).toBeVisible();

  // Товарищ входит выданным паролем во втором браузере и видит те же задачи.
  const mate = await secondBrowser(browser);
  await signIn(mate, email, password);
  await expect(mate).toHaveURL(/\/tasks/);
  await expect(side(mate).getByText(name, { exact: true })).toBeVisible();
  await expect(side(mate).getByRole('link', { name: new RegExp(email) })).toBeVisible();
  expect(await found(mate)).toBe(adminSees);
  await expect(mate.getByRole('link', { name: 'DEMO-1', exact: true })).toBeVisible();

  // Людей неадминистратору нет ни пунктом, ни прямой ссылкой, и список не спрашивается.
  await expect(side(mate).getByRole('link', { name: 'Люди' })).toHaveCount(0);
  const asked: string[] = [];
  mate.on('request', (request) => asked.push(new URL(request.url()).pathname));
  await mate.goto('/people');
  await expect(
    mate.getByText('Людьми управляет администратор установки.', { exact: false }),
  ).toBeVisible();
  await expect(mate.getByRole('button', { name: 'Завести человека' })).toHaveCount(0);
  expect(asked).not.toContain('/api/v1/accounts');

  // Выход товарища не трогает администратора: у каждого свой токен и своя кука.
  await side(mate).getByRole('button', { name: 'Выйти' }).click();
  await expect(mate.getByLabel('Почта')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('article', { name: `Учётная запись ${email}` })).toBeVisible();
  await expect(side(page).getByRole('link', { name: /owner@localhost/ })).toBeVisible();

  // Товарищ входит снова, и администратор отключает его, пока тот работает.
  await signIn(mate, email, password);
  await expect(mate).toHaveURL(/\/tasks/);
  await page
    .getByRole('article', { name: `Учётная запись ${email}` })
    .getByRole('button', { name: 'Отключить' })
    .click();
  const confirm = page.getByRole('alertdialog', { name: `Отключить ${email}?` });
  await confirm.getByRole('button', { name: 'Отключить' }).click();
  await expect(confirm).toHaveCount(0);
  await expect(
    page
      .getByRole('article', { name: `Учётная запись ${email}` })
      .getByText('отключена', { exact: true }),
  ).toBeVisible();

  // Отключение отозвало токен сеанса: следующий же запрос уводит товарища на вход, и
  // верный пароль больше не пускает.
  await side(mate).getByRole('link', { name: 'Входящая' }).click();
  await expect(mate.getByLabel('Почта')).toBeVisible();
  await signIn(mate, email, password);
  await expect(mate.getByRole('alert')).toHaveText(
    'Эта учётная запись отключена. Обратитесь к администратору установки.',
  );
  await expect(mate).toHaveURL(/\/login$/);

  await mate.context().close();
});

test('экраны людей и своей учётной записи: доступность и узкое окно', async ({ page }) => {
  await signIn(page, E2E_EMAIL, E2E_PASSWORD);
  await expect(page).toHaveURL(/\/tasks/);

  for (const path of ['/people', '/account']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText('Спрашиваем установку, кто вы…')).toHaveCount(0);

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);

    // Телефон — полноценная цель (UI-134#3): вбок страница не едет.
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.setViewportSize({ width: 1280, height: 720 });
  }

  // Окно заведения — тоже без нарушений.
  await page.goto('/people');
  await page.getByRole('button', { name: 'Завести человека' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  const dialog = await new AxeBuilder({ page }).analyze();
  expect(dialog.violations).toEqual([]);
});
