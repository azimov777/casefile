import { expect, test } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.use({ viewport: { width: 1440, height: 900 } });

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

test('свёрнутый отбор с двумя условиями занимает не больше строки', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&status=open&status=in_progress');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  const panel = page.getByRole('region', { name: 'Отбор задач' });
  const box = await panel.boundingBox();

  // Развёрнутая форма занимала около 295 px первого экрана; свёрнутая обязана
  // укладываться в строку — иначе чипы просто заменили бы одну потерю места другой.
  expect(box?.height ?? 0).toBeLessThanOrEqual(56);
  // Очередь среди условий не значится: она стала местом в интерфейсе (UI-38).
  const conditions = page.getByRole('list', { name: 'Условия отбора' });
  await expect(conditions).toContainText('статус open, in_progress');
  await expect(conditions).not.toContainText('очередь');
});

test('чип снимается клавиатурой, и фокус не падает на body', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&status=open');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  const remove = page.getByRole('button', { name: 'Убрать условие: статус open' });
  await remove.focus();
  await page.keyboard.press('Enter');

  await expect(page).toHaveURL(/queue=DEMO/);
  await expect(page).not.toHaveURL(/status=/);

  // Условие снято, кнопка исчезла — но фокус остался в интерфейсе, а не улетел
  // на `body`: иначе следующий Tab начинал бы обход страницы с начала.
  const focused = await page.evaluate(() => document.activeElement?.tagName ?? '');
  expect(focused).not.toBe('BODY');
});

test('список сортировки открывается с клавиатуры, ходит стрелками и закрывается Esc', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  const trigger = page.getByRole('combobox', { name: 'Сортировка' });
  await trigger.focus();
  await page.keyboard.press('Enter');

  const list = page.getByRole('listbox');
  await expect(list).toBeVisible();

  // `Esc` закрывает и возвращает фокус на триггер — это приходит вместе с Radix
  // и потому проверяется один раз, а не у каждого меню.
  await page.keyboard.press('Escape');
  await expect(list).toBeHidden();
  await expect(trigger).toBeFocused();

  // Ходьба стрелками: выделение переезжает на соседний пункт, не трогая значения.
  await page.keyboard.press('Enter');
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('[role="option"][data-highlighted]')).toHaveCount(1);

  // Выбор уезжает в адрес и в запрос.
  await page.getByRole('option', { name: 'по ключу', exact: true }).click();
  await expect(page).toHaveURL(/sort=key/);
  await expect(trigger).toContainText('по ключу');
});
