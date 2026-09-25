import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, side } from './contour';

/*
 * Архив проекта в интерфейсе (UI-176): архивирование и восстановление с причиной,
 * флажок «Архивные проекты» в панели с пометкой архивных, задачи архивного проекта без
 * ответа и замечания; `axe` в окнах и в панели с флажком.
 *
 * Сценарий пишущий — заводит проекты, задачи и вопросы, архивирует — и идёт в проекте
 * «запись». Каждый тест заводит свой проект с меткой прогона: архив замораживает проект
 * целиком, и общий на все тесты проект связал бы их порядком. Удалить проект нельзя —
 * архивные просто остаются скрытыми. Ключ прогона — ключ установки контура: набор `main`.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Заводит проект прогона с буквой-меткой теста; ключ не длиннее 16 знаков. */
async function createProject(request: APIRequestContext, mark: string): Promise<string> {
  const key = `${mark}${RUN}`.slice(0, 16);
  const response = await request.post('/api/v1/projects', {
    headers: auth(),
    data: { key, title: `Архив прогона ${RUN}`, description: 'Заведён сквозным тестом UI-176.' },
  });
  expect(response.status()).toBe(201);
  return key;
}

/** Задача в проекте с открытым вопросом — ей есть что ответить и к чему придраться. */
async function taskWithQuestion(request: APIRequestContext, project: string): Promise<string> {
  const created = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: { project, title: 'Задача архивного проекта', description: 'Сквозной тест UI-176.' },
  });
  expect(created.status()).toBe(201);
  const key = ((await created.json()) as { data: { key: string } }).data.key;
  const asked = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: auth(),
    data: {
      type: 'question',
      title: 'Хранить ли дело вечно?',
      body: 'Вопрос сквозного теста UI-176.',
      payload: { addressees: ['owner'], blocking: false },
    },
  });
  expect(asked.status()).toBe(201);
  return key;
}

async function archive(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/projects/${key}/archive`, {
    headers: auth(),
    data: { reason: 'Архив сквозного теста UI-176.' },
  });
  expect(response.status()).toBe(200);
}

/** Дело проекта одной строкой: в нём ищут причину архива и восстановления. */
async function caseText(request: APIRequestContext, key: string): Promise<string> {
  const response = await request.get(`/api/v1/projects/${key}/entries`, { headers: auth() });
  expect(response.status()).toBe(200);
  return JSON.stringify(await response.json());
}

/** Строка проекта в панели: ссылка на его задачи, имя начинается с ключа. */
function projectRow(page: Page, key: string) {
  return side(page).getByRole('link', { name: new RegExp(`^${key}`) });
}

test('архив с причиной убирает проект из панели; флажок показывает его с пометкой; восстановление возвращает', async ({
  page,
}) => {
  const key = await createProject(page.request, 'A');
  const writes: { method: string; url: string }[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/(archive|restore)$/.test(request.url())) {
      writes.push({ method: request.method(), url: request.url() });
    }
  });

  await page.goto(`/projects/${key}`);
  await expect(projectRow(page, key)).toBeVisible();

  // Без причины — ни запроса, ни архива: упрёк под полем.
  await page.getByRole('button', { name: 'В архив', exact: true }).click();
  const dialog = page.getByRole('alertdialog', { name: `Отправить ${key} в архив?` });
  await dialog.getByRole('button', { name: 'Отправить в архив' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Без причины проект в архив не уходит');
  expect(writes).toEqual([]);

  await dialog.getByLabel('Причина').fill('Работа переехала в другой проект');
  await dialog.getByRole('button', { name: 'Отправить в архив' }).click();
  await expect(dialog).toBeHidden();
  expect(writes).toHaveLength(1);
  // Причина доехала до дела проекта записью `archived` — сверка с бэкендом, а не с
  // телом запроса в браузере.
  expect(await caseText(page.request, key)).toContain('Работа переехала в другой проект');

  // Экран остаётся и говорит, что проект в архиве; правки на нём нет, а фокус — на той
  // же кнопке, ставшей «Восстановить».
  await expect(page.getByText('Проект в архиве с', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Изменить', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Добавить атрибут' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Написать заметку' })).toHaveCount(0);
  const restore = page.getByRole('button', { name: 'Восстановить', exact: true });
  await expect(restore).toBeFocused();

  // Из панели проект ушёл: его скрыл бэкенд.
  await expect(projectRow(page, key)).toHaveCount(0);

  // Флажок показывает его с пометкой, и его экран открывается из панели.
  const toggle = side(page).getByRole('checkbox', { name: 'Архивные проекты' });
  await toggle.check();
  await expect(projectRow(page, key)).toContainText('в архиве');
  await expect(projectRow(page, 'DEMO')).not.toContainText('в архиве');
  await page.goto('/tasks');
  // Выбор переживает переход и перезагрузку: он живёт в браузере, а не в адресе.
  await page.reload();
  await expect(toggle).toBeChecked();
  expect(new URL(page.url()).search).toBe('');
  await side(page)
    .getByRole('link', { name: `О проекте ${key}` })
    .click();
  await expect(page).toHaveURL(new RegExp(`/projects/${key}$`));
  await expect(page.getByText('Проект в архиве с', { exact: false })).toBeVisible();

  // Восстановление — тоже только с причиной.
  await toggle.uncheck();
  await expect(projectRow(page, key)).toHaveCount(0);
  await restore.click();
  const back = page.getByRole('dialog', { name: `Восстановить ${key}` });
  await back.getByRole('button', { name: 'Восстановить проект' }).click();
  await expect(back.getByRole('alert')).toContainText('Без причины проект не восстанавливается');
  expect(writes).toHaveLength(1);
  await back.getByLabel('Причина').fill('Вернулись к работе');
  await back.getByRole('button', { name: 'Восстановить проект' }).click();
  await expect(back).toBeHidden();
  expect(await caseText(page.request, key)).toContain('Вернулись к работе');
  expect(writes.map((write) => new URL(write.url).pathname)).toEqual([
    `/api/v1/projects/${key}/archive`,
    `/api/v1/projects/${key}/restore`,
  ]);

  // Проект снова в панели без флажка, без пометки, и правка на экране вернулась.
  await expect(projectRow(page, key)).toBeVisible();
  await expect(projectRow(page, key)).not.toContainText('в архиве');
  await expect(page.getByText('Проект в архиве с', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Изменить', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'В архив', exact: true })).toBeFocused();
});

test('на задаче архивного проекта нет ни ответа, ни замечания; на задаче активного — есть', async ({
  page,
}) => {
  const project = await createProject(page.request, 'T');
  const task = await taskWithQuestion(page.request, project);

  // Пока проект активный, обе формы на месте.
  await page.goto(`/tasks/${task}`);
  await expect(page.getByRole('button', { name: 'Ответить' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Оставить замечание' })).toBeVisible();
  await page.getByRole('button', { name: 'Ответить' }).click();
  await expect(page.getByRole('textbox')).toHaveCount(1);

  await archive(page.request, project);

  // Архивный: вопрос читается, а отвечать и замечать нечем — и сказано почему. Адрес,
  // зовущий ответить (`?entry=N`), формы тоже не раскрывает.
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes('/api/v1/'))
      writes.push(request.url());
  });
  await page.goto(`/tasks/${task}`);
  await expect(page.getByText(`Проект ${project} в архиве`, { exact: false })).toBeVisible();
  await expect(page.getByText('Вопрос сквозного теста UI-176.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ответить' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Оставить замечание' })).toHaveCount(0);
  await expect(page.getByRole('textbox')).toHaveCount(0);
  await page.getByRole('link', { name: `Открыть проект ${project}` }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${project}$`));
  expect(writes).toEqual([]);
});

for (const colorScheme of ['light', 'dark'] as const) {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`окна архива и панель с флажком без нарушений axe: ${colorScheme}, ${viewport.width}px`, async ({
      page,
    }) => {
      const key = await createProject(
        page.request,
        `X${colorScheme === 'light' ? 'L' : 'D'}${viewport.width}`,
      );
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize(viewport);
      await page.goto(`/projects/${key}`);
      await expect(page.getByRole('heading', { level: 1 })).toContainText(key);
      await fontsReady(page);

      // Окно архива: `axe`, затем `Esc` возвращает фокус на кнопку.
      await page.getByRole('button', { name: 'В архив', exact: true }).click();
      const dialog = page.getByRole('alertdialog', { name: `Отправить ${key} в архив?` });
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: 'Отправить в архив' }).click();
      await expect(dialog.getByRole('alert')).toBeVisible();
      let report = await new AxeBuilder({ page }).analyze();
      expect(report.violations, 'В архив').toEqual([]);
      await page.keyboard.press('Escape');
      await expect(dialog).toBeHidden();
      await expect(page.getByRole('button', { name: 'В архив', exact: true })).toBeFocused();

      // Архивный проект: плашка и окно восстановления.
      await archive(page.request, key);
      await page.reload();
      await expect(page.getByText('Проект в архиве с', { exact: false })).toBeVisible();
      report = await new AxeBuilder({ page }).analyze();
      expect(report.violations, 'экран архивного проекта').toEqual([]);
      await page.getByRole('button', { name: 'Восстановить', exact: true }).click();
      const back = page.getByRole('dialog', { name: `Восстановить ${key}` });
      await expect(back).toBeVisible();
      report = await new AxeBuilder({ page }).analyze();
      expect(report.violations, 'Восстановить').toEqual([]);
      await page.keyboard.press('Escape');
      await expect(back).toBeHidden();

      // Панель с включённым флажком и архивным проектом в ней; на телефоне — шторкой.
      const narrow = viewport.width < 800;
      if (narrow) await page.getByRole('button', { name: /Показать разделы/ }).click();
      const panel = narrow ? page.getByRole('dialog', { name: 'Разделы Casefile' }) : side(page);
      await panel.getByRole('checkbox', { name: 'Архивные проекты' }).check();
      await expect(panel.getByRole('link', { name: new RegExp(`^${key}`) })).toContainText(
        'в архиве',
      );
      report = await new AxeBuilder({ page }).analyze();
      expect(report.violations, 'панель с архивными').toEqual([]);

      const over = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(over).toBeLessThanOrEqual(0);
    });
  }
}
