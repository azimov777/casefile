import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Строка описи по заголовку записи: номер записи зависит от истории задачи, заголовок — нет. */
function entryRow(page: Page, title: string) {
  return page.getByRole('row').filter({ has: page.getByRole('button', { name: title }) });
}

function serious(violations: { impact?: string | null; id: string }[]) {
  return violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => v.id);
}

test('карточка DEMO-6 рисуется одним запросом пакета и объясняет, что задачу держит', async ({
  page,
}) => {
  await silenceJournal(page);
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/tasks/')) calls.push(request.url());
  });

  await page.goto('/tasks/DEMO-6');

  const header = page.getByRole('banner');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-6');
  const card = page.getByRole('main');
  await expect(card.getByText('in_progress').first()).toBeVisible();
  await expect(card.getByText('заблокирована')).toBeVisible();

  // Кто именно держит — видно из связей, с ключом и статусом другой стороны.
  const links = page.getByRole('region', { name: 'Связи' });
  await expect(links.getByRole('link', { name: 'DEMO-2' })).toBeVisible();
  await expect(links.getByText('blocked_by')).toBeVisible();

  // Сводка целиком, без клика.
  const summary = page.getByRole('region', { name: 'Последняя сводка' });
  for (const part of ['Сделано', 'Осталось', 'Что мешает', 'Следующий шаг']) {
    await expect(summary.getByText(part, { exact: true })).toBeVisible();
  }

  await expect(page.getByText('Записей в деле: 7')).toBeVisible();
  await expect(header).toBeVisible();

  // Один запрос пакета и ни одного за телами записей.
  expect(calls.filter((url) => url.includes('/entries'))).toEqual([]);
  expect(calls).toHaveLength(1);
});

test('клик по вердикту читает ровно эту запись и показывает проверку, исход и доказательство', async ({
  page,
}) => {
  await silenceJournal(page);
  const entryCalls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/entries')) entryCalls.push(request.url());
  });

  await page.goto('/tasks/DEMO-6');

  const row = entryRow(page, 'Verdict on check 2: failed');
  const no = (await row.getByRole('rowheader').innerText()).trim();
  await row.getByRole('button', { name: 'Verdict on check 2: failed' }).click();

  const body = page.getByRole('cell').filter({ hasText: 'Проверка 2' });
  await expect(body).toContainText('failed');
  // Текст проверки берётся из `checks` задачи по номеру: в записи его нет.
  await expect(body).toContainText('Неприменимый оператор');
  await expect(body).toContainText('details.allowed');

  expect(entryCalls).toHaveLength(1);
  expect(new URL(entryCalls[0] as string).searchParams.getAll('nos')).toEqual([no]);
});

test('DEMO-4 показывает открытый блокирующий вопрос целиком, без клика', async ({ page }) => {
  await silenceJournal(page);
  const entryCalls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/entries')) entryCalls.push(request.url());
  });

  await page.goto('/tasks/DEMO-4');

  const questions = page.getByRole('region', { name: 'Открытые вопросы' });
  await expect(questions.getByText('блокирующий')).toBeVisible();
  await expect(questions.getByText('owner')).toBeVisible();
  await expect(questions).toContainText('Сколько храним?');
  expect(entryCalls).toEqual([]);
});

test('адрес с номером записи открывает карточку уже раскрытой', async ({ page }) => {
  await page.goto('/tasks/DEMO-6');
  const no = (await entryRow(page, 'Task created').getByRole('rowheader').innerText()).trim();

  await page.goto(`/tasks/DEMO-6?entry=${no}`);

  await expect(page.getByRole('button', { name: 'Task created' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
});

test('обзорные проверки нумерованы с единицы, как их считает вердикт', async ({ page }) => {
  await page.goto('/tasks/DEMO-6');

  const checks = page.getByRole('region', { name: 'Задание' }).getByRole('list').last();
  await expect(checks.getByRole('listitem')).toHaveCount(2);
  await expect(checks.getByRole('listitem').nth(1)).toContainText('Неприменимый оператор');
});

test('ключ в списке ведёт на карточку, несуществующая задача объясняется по-русски', async ({
  page,
}) => {
  await page.goto('/tasks?queue=DEMO');
  await page.getByRole('link', { name: 'DEMO-6' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-6');

  await page.goto('/tasks/DEMO-999');
  await expect(page.getByText(/Задачи с таким ключом нет/)).toBeVisible();
  await page.getByRole('link', { name: 'Вернуться к списку задач' }).click();
  await expect(page).toHaveURL(/\/tasks$/);
});

test('доступность ленты дела', async ({ page }) => {
  await page.goto('/tasks/DEMO-1/case');
  await expect(page.getByRole('article').first()).toBeVisible();

  const closed = await new AxeBuilder({ page }).analyze();
  expect(serious(closed.violations)).toEqual([]);

  // И с раскрытым отбором по типам: у флажков свои подписи и своя группа.
  await page.getByRole('button', { name: 'Записи агента' }).click();
  await expect(page.getByRole('article').first()).toBeVisible();

  const filtered = await new AxeBuilder({ page }).analyze();
  expect(serious(filtered.violations)).toEqual([]);
});

test('доступность карточки задачи', async ({ page }) => {
  await page.goto('/tasks/DEMO-6');
  await expect(page.getByText('Записей в деле: 7')).toBeVisible();

  const closed = await new AxeBuilder({ page }).analyze();
  expect(serious(closed.violations)).toEqual([]);

  await page.getByRole('button', { name: 'Verdict on check 2: failed' }).click();
  await expect(page.getByText('Проверка 2')).toBeVisible();

  const opened = await new AxeBuilder({ page }).analyze();
  expect(serious(opened.violations)).toEqual([]);
});

test('лента дела: все типы записей, отбор и ответ под вопросом', async ({ page }) => {
  await silenceJournal(page);
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/entries')) calls.push(request.url());
  });

  await page.goto('/tasks/DEMO-1/case');

  // Дело закрытой задачи демо содержит записи всех типов: это её смысл в демо-наборе.
  await expect(page.getByRole('article').first()).toBeVisible();
  const total = await page.getByRole('article').count();
  expect(total).toBeGreaterThan(10);

  // Одна страница ленты — один запрос записей.
  expect(calls).toHaveLength(1);

  // Отбор «Служебные» оставляет только записи трекера.
  await page.getByRole('button', { name: 'Служебные' }).click();
  await expect(page.getByRole('article')).not.toHaveCount(total);
  await expect(page.getByText('created').first()).toBeVisible();
  await expect(page.getByRole('article').filter({ hasText: 'decision' })).toHaveCount(0);
});

test('ответ на вопрос стоит под вопросом, а якорь подсвечивает запись', async ({ page }) => {
  await page.goto('/tasks/DEMO-4/case');

  // В деле DEMO-4 есть открытый вопрос: ответа под ним ещё нет, и это сказано словами.
  const question = page.getByRole('article').filter({ hasText: 'question' }).first();
  await expect(question).toBeVisible();
  await expect(question.getByText('Ответа пока нет.')).toBeVisible();

  await page.goto('/tasks/DEMO-6/case#4');
  const highlighted = page.getByRole('article').filter({ hasText: '#4' }).first();
  await expect(highlighted).toBeVisible();
});
