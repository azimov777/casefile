import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { E2E_EMAIL, E2E_PASSWORD, LOGIN_URL, compose, side } from './contour';

/**
 * Перенос установки (UI-135): администратор скачивает архив кнопкой и принимает его на
 * свежей установке — без терминала. Единственный сценарий здесь, которому мало контура
 * `global-setup.ts`: приём проверяется только пустой установкой, а общий контур несёт
 * демо-данные с самого начала. Поэтому сценарий поднимает **вторую**, полностью пустую
 * установку — тем же образом compose, тем же образом контура (`../docker-compose.yml`),
 * но под своим именем проекта и своим портом `ui`, — и гасит её сам.
 *
 * Вторая установка не трогает общую демо-базу ни при подъёме, ни при приёме: у неё своя
 * `db` и свой `api`. Ключ её `local-token` тоже сверяет свой файл, а не тот, что читают
 * соседние сценарии (`readE2eToken`, `.secrets/ui-token`), — он ушёл бы в конфликт с их
 * подъёмом: свой `--output .secrets/moving-target-ui-token` рядом. Имя ключа
 * (`--name local-ui`) названо явно тем же именем, каким его завела бы установка
 * `install.sh`, а не своим: ответ приёма (`ArchiveImportRead.machine_keys`) называет
 * уцелевшие ключи по имени — тот же приём и то же имя, что несёт архив источника.
 *
 * Сценарий пишущий (заводит вторую установку и меняет её данные необратимо), поэтому
 * идёт проектом «запись»: `playwright.config.ts` держит там один воркер, и с общей демо-
 * установкой он не расходится по времени ни с одним соседним пишущим сценарием.
 */
test.describe.configure({ timeout: 180_000 });

const PROJECT = process.env.COMPOSE_PROJECT_NAME ?? 'tracker-ui';
const TARGET_PROJECT = `${PROJECT}-moving-target`;
/** Порт вдали от любого занятого этим деревом: свой `UI_PORT` плюс запас. */
const TARGET_PORT = String(Number(process.env.UI_PORT ?? '8081') + 900);
const TARGET_URL = `http://localhost:${TARGET_PORT}`;
const TARGET_TOKEN_FILE = resolve(process.cwd(), '.secrets/moving-target-ui-token');

function composeTarget(args: string[], env: Record<string, string> = {}): string {
  return compose(args, { COMPOSE_PROJECT_NAME: TARGET_PROJECT, ...env });
}

/**
 * Ключ администратора второй установки, набора `main`, под именем `local-ui` — тем же
 * приёмом, что и у настоящей установки (`local-token`, но со своим файлом). Секрета
 * `local-token` не печатает никогда (UI-75#6), поэтому он читается из файла, который
 * команда сама и написала.
 */
function issueTargetKey(): string {
  composeTarget([
    'run',
    '--rm',
    'local-token',
    ...['python', '-m', 'app.cli', 'local-token'],
    ...['--output', '.secrets/moving-target-ui-token', '--name', 'local-ui'],
  ]);
  return readFileSync(TARGET_TOKEN_FILE, 'utf8').trim();
}

test.beforeAll(() => {
  composeTarget(['up', '-d', '--wait', 'api']);
  composeTarget(['run', '--rm', 'migrate']);
  composeTarget(['run', '--rm', 'init']);
  const token = issueTargetKey();
  composeTarget(['up', '-d', '--wait', 'ui'], { TRACKER_UI_TOKEN: token, UI_PORT: TARGET_PORT });
});

test.afterAll(() => {
  try {
    composeTarget(['down', '-v']);
  } catch (error) {
    // Гашение — уборка, а не часть проверки: провал самого сценария не должен потеряться
    // за отказом `docker compose down`.
    console.error('не удалось погасить вторую установку', error);
  }
});

/** Сколько задач нашлось на списке: строка счётчика целиком — общий признак «те же задачи». */
async function found(page: Page): Promise<string> {
  const counter = page.getByText(/^Нашл(ась|ось) \d+ задач/);
  await expect(counter).toBeVisible();
  return (await counter.textContent()) ?? '';
}

test('администратор скачивает архив и принимает его на свежей установке; повторный приём отказывает', async ({
  page,
  browser,
}) => {
  // Источник — общая демо-установка контура, тем же ключом, что у любого читающего
  // сценария: /moving открыт администратору владельца без единого действия входа.
  // Счётчик задач — примета списка, а не экрана переноса, поэтому снимается на /tasks.
  await page.goto('/tasks');
  const sourceProjects = await found(page);

  await page.goto('/moving');
  await expect(page.getByRole('heading', { level: 1, name: 'Перенос установки' })).toBeVisible();

  const download = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Скачать архив' }).click(),
  ]).then(([download]) => download);
  const filename = download.suggestedFilename();
  expect(filename).toMatch(/^casefile-archive-\d{4}-\d{2}-\d{2}\.json$/);
  // `download.path()` лежит под именем Playwright, а не под тем, что предложил экран:
  // приёмник должен увидеть то самое имя файла, что показывает диалог подтверждения.
  const archivePath = test.info().outputPath(filename);
  await download.saveAs(archivePath);

  // Приёмник — вторая, пустая установка (`beforeAll`): свой браузерный контекст со
  // своим адресом (`baseURL` — относительные переходы дальше идут в неё), свой ключ
  // администратора, но тот же экран и тот же путь кнопок.
  const targetContext = await browser.newContext({ baseURL: TARGET_URL, locale: 'ru-RU' });
  const target = await targetContext.newPage();
  await target.goto('/moving');
  await expect(target.getByRole('heading', { level: 1, name: 'Перенос установки' })).toBeVisible();

  async function chooseAndConfirm() {
    await target.getByLabel('Файл архива').setInputFiles(archivePath);
    await target.getByRole('button', { name: 'Принять', exact: true }).click();
    const confirm = target.getByRole('alertdialog', { name: 'Заменить эту установку архивом?' });
    await expect(confirm).toBeVisible();
    // Точное имя файла отличает подпись от заголовка-обёртки «Файл архива: …», где то
    // же имя тоже встречается подстрокой.
    await expect(confirm.getByText(filename, { exact: true })).toBeVisible();
    await confirm.getByRole('button', { name: 'Принять, заменив всё' }).click();
    return confirm;
  }

  const confirm = await chooseAndConfirm();
  const result = target.getByRole('region', { name: 'Итог приёма' });
  await expect(result).toBeVisible();
  await expect(confirm).toHaveCount(0);
  // Итог называет то, что вернул бэкенд — ревизии и уцелевшие ключи этой машины.
  await expect(result.getByText('local-ui', { exact: false })).toBeVisible();

  // Доска новой установки продолжает работать её собственным ключом, без перезагрузки
  // (решение TRK-100#19/#20), и показывает тот же проект и те же задачи, что источник.
  await target.goto('/tasks');
  await expect(side(target).getByRole('link', { name: /^DEMO/ })).toBeVisible();
  expect(await found(target)).toBe(sourceProjects);

  // Повторный приём того же архива — установка больше не пустая.
  await target.goto('/moving');
  const secondConfirm = await chooseAndConfirm();
  // Предупреждение окна тоже `role="alert"` (тот же `tone="danger"`, что у отказа), и
  // ролью в окне на этот момент — два элемента; отказ поэтому ищется текстом.
  await expect(
    secondConfirm.getByText(
      'Принять архив может только установка без проектов — принимайте в свежую.',
    ),
  ).toBeVisible();
  await expect(secondConfirm).toBeVisible();

  await targetContext.close();
});

test('неадминистратору в режиме входа пункта панели и кнопок нет', async ({ page, browser }) => {
  const stamp = Date.now().toString(36);
  const email = `mate-moving-${stamp}@example.com`;
  const name = `mate_moving_${stamp}`;

  await page.goto(`${LOGIN_URL}/login`);
  await page.getByLabel('Почта').fill(E2E_EMAIL);
  await page.getByLabel('Пароль', { exact: true }).fill(E2E_PASSWORD);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/tasks/);

  await side(page).getByRole('link', { name: 'Люди' }).click();
  await page.getByRole('button', { name: 'Завести человека' }).click();
  const form = page.getByRole('dialog', { name: 'Завести человека' });
  await form.getByLabel('Почта').fill(email);
  await form.getByLabel('Имя').fill(name);
  await form.getByRole('button', { name: 'Завести' }).click();
  const once = page.getByRole('dialog', { name: `Учётная запись ${email} заведена` });
  const password = (await once.locator('pre, code').last().textContent())?.trim() ?? '';
  await once.getByRole('button', { name: 'Я сохранил' }).click();

  const mateContext = await browser.newContext({ baseURL: LOGIN_URL, locale: 'ru-RU' });
  const mate = await mateContext.newPage();
  await mate.goto('/login');
  await mate.getByLabel('Почта').fill(email);
  await mate.getByLabel('Пароль', { exact: true }).fill(password);
  await mate.getByRole('button', { name: 'Войти' }).click();
  await expect(mate).toHaveURL(/\/tasks/);

  // Пункта панели нет.
  await expect(side(mate).getByRole('link', { name: 'Перенос установки' })).toHaveCount(0);

  // Прямая ссылка не спрашивает архив и не показывает действий — только объяснение.
  const asked: string[] = [];
  mate.on('request', (request) => asked.push(new URL(request.url()).pathname));
  await mate.goto('/moving');
  await expect(
    mate.getByText('Переносом установки распоряжается её администратор.', { exact: false }),
  ).toBeVisible();
  await expect(mate.getByRole('button', { name: 'Скачать архив' })).toHaveCount(0);
  await expect(mate.getByRole('button', { name: 'Принять', exact: true })).toHaveCount(0);
  expect(asked).not.toContain('/api/v1/installation/archive');

  // Снимок для дела: телефон — полноценная цель (UI-134#3), не только широкий экран.
  await mate.setViewportSize({ width: 390, height: 844 });
  await mate.screenshot({
    path: test.info().outputPath('moving-non-admin-390.png'),
    fullPage: true,
  });

  await mateContext.close();
});
