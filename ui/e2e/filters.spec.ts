import { expect, test, type Locator } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

test.use({ viewport: { width: 1440, height: 900 } });

test('строка отбора с двумя условиями занимает не больше двух строк', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO&status=open&status=in_progress');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  const panel = page.getByRole('region', { name: 'Отбор задач' });
  const box = await panel.boundingBox();

  // Строка инструментов и строка состояния: условия не прячутся за раскрытием, но и
  // первый экран списка не отдаётся форме — прежняя развёрнутая занимала около 295 px.
  expect(box?.height ?? 0).toBeLessThanOrEqual(72);
  // Проект среди условий не значится: он стал местом в интерфейсе (UI-38).
  const conditions = page.getByRole('list', { name: 'Условия отбора' });
  await expect(conditions).toContainText('статус open, in_progress');
  await expect(conditions).not.toContainText('проект');
});

test('приоритет, исполнитель и признак ставятся из панели и переживают перезагрузку чипами', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  const menu = page.getByRole('dialog', { name: 'Условия отбора задач' });
  await menu.getByRole('button', { name: 'приоритет high', exact: true }).click();
  await expect(page).toHaveURL(/priority=high/);
  // Панель не закрывается от нажатия: второе условие ставится следом.
  await menu.getByRole('button', { name: 'есть открытые вопросы', exact: true }).click();
  await expect(page).toHaveURL(/questions=true/);
  await menu.getByLabel('Исполнитель').fill('demo_agent');
  await menu.getByLabel('Исполнитель').press('Enter');
  await expect(page).toHaveURL(/assignee=demo_agent/);

  await page.reload();

  // Панель закрыта, а включённое названо чипами без всякого раскрытия.
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const conditions = page.getByRole('list', { name: 'Условия отбора' });
  await expect(conditions).toContainText('приоритет high');
  await expect(conditions).toContainText('исполнитель demo_agent');
  await expect(conditions).toContainText('есть открытые вопросы');
  await expect(page).toHaveURL(/priority=high/);
  await expect(page).toHaveURL(/assignee=demo_agent/);
  await expect(page).toHaveURL(/questions=true/);

  // Панель по-прежнему показывает то же самое нажатым.
  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await expect(menu.getByRole('button', { name: 'приоритет high', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  // `Esc` закрывает панель и возвращает фокус на кнопку — это приходит с Radix.
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(page.getByRole('button', { name: 'Фильтр', exact: true })).toBeFocused();
});

test('запрос: ошибка объясняется у поля, верный отменяет простой отбор', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO&status=open');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  await page.getByRole('button', { name: 'Запрос', exact: true }).click();
  const field = page.getByLabel('Запрос на языке бэкенда');
  await expect(field).toBeFocused();
  await field.fill('status: opne');
  await field.press('Enter');

  const problem = page.getByRole('alert');
  await expect(problem).toContainText('Ошибка в символе 9');
  await expect(problem).toContainText('in_progress');

  await field.fill('status: in_progress');
  await field.press('Enter');
  await expect(problem).toBeHidden();
  await expect(page).toHaveURL(/query=status/);
  // Простой отбор в адресе остался, но выдачу решает запрос: в строках только
  // `in_progress`, хотя `status=open` никто не снимал.
  await expect(page).toHaveURL(/status=open/);
  const statuses = page.locator('tbody tr [data-mark="status"]');
  await expect(statuses.first()).toContainText('in_progress');
  for (const text of await statuses.allTextContents()) expect(text).toContain('in_progress');
  await expect(page.getByRole('list', { name: 'Условия отбора' })).toHaveCount(0);

  // Выход из режима снимает запрос, и простой отбор возвращается чипом.
  await page.getByRole('button', { name: 'Запрос', exact: true }).click();
  await expect(page).not.toHaveURL(/query=/);
  await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText('статус open');
});

test('чип снимается клавиатурой, и фокус не падает на body', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO&status=open');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  const remove = page.getByRole('button', { name: 'Убрать условие: статус open' });
  await remove.focus();
  await page.keyboard.press('Enter');

  await expect(page).toHaveURL(/project=DEMO/);
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
  await page.goto('/tasks?project=DEMO');
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

test('на доске тот же порядок: выбранный уходит в запрос каждого столбца', async ({ page }) => {
  await silenceJournal(page);
  const sorts: string[] = [];
  page.on('request', (call) => {
    const url = new URL(call.url());
    if (url.pathname === '/api/v1/tasks' && url.searchParams.has('status')) {
      sorts.push(url.searchParams.getAll('sort').join(','));
    }
  });

  await page.goto('/tasks?project=DEMO&view=board');
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();

  const trigger = page.getByRole('combobox', { name: 'Сортировка' });
  await trigger.click();
  sorts.length = 0;
  await page.getByRole('option', { name: 'сначала важные', exact: true }).click();

  await expect(page).toHaveURL(/sort=-priority/);
  await expect.poll(() => sorts.length).toBeGreaterThan(0);
  expect(new Set(sorts)).toEqual(new Set(['-priority']));
});

/**
 * Смещение шеврона `Select` относительно оптической оси подписи: центр последнего
 * `svg` внутри триггера (шеврон — всегда последний, `select.tsx`) минус центр строки
 * значения. Ноль — шеврон стоит на оси; метод общий для любого `Select`, не только
 * языка (UI-146).
 */
function chevronOffset(trigger: Locator): Promise<number> {
  return trigger.evaluate((node) => {
    const svgs = Array.from(node.querySelectorAll('svg'));
    const chevron = svgs[svgs.length - 1] as Element;
    const value = node.querySelector('span.truncate') as Element;
    const chevronBox = chevron.getBoundingClientRect();
    const valueBox = value.getBoundingClientRect();
    return (chevronBox.top + chevronBox.bottom) / 2 - (valueBox.top + valueBox.bottom) / 2;
  });
}

test('шеврон выбора языка стоит на одной оси с подписью, как и шеврон сортировки (UI-146)', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  /*
   * Замер снят после `document.fonts.ready` (`docs/notes/ui.md`, «Замер геометрии
   * снимается после document.fonts.ready»): до этого текст набран запасной
   * гарнитурой, и метрика строки отличается от той, что видит человек.
   */
  await fontsReady(page);

  const language = page.getByRole('combobox', { name: 'Язык интерфейса' });
  const sort = page.getByRole('combobox', { name: 'Сортировка' });
  await expect(language).toBeVisible();
  await expect(sort).toBeVisible();

  const offsets = {
    language: Math.round((await chevronOffset(language)) * 100) / 100,
    sort: Math.round((await chevronOffset(sort)) * 100) / 100,
  };
  const report = JSON.stringify(offsets);

  // Оба шеврона — один и тот же `Select`, и держатся одним правилом: расхождение
  // с осью подписи не больше пикселя у обоих, не только у того, где его заметили.
  expect(Math.abs(offsets.language), report).toBeLessThanOrEqual(1);
  expect(Math.abs(offsets.sort), report).toBeLessThanOrEqual(1);
});
