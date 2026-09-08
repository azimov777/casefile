import { expect, test } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

test('возврат в список не теряет отбор, с которым человек ушёл', async ({ page }) => {
  await silenceJournal(page);

  const listed = '/tasks?queue=DEMO&status=open';
  await page.goto(listed);
  // Дожидаемся строк, а не считаем сразу: `count()` не ждёт, и до прихода выдачи
  // таблица пуста — счётчик снял бы ноль и сравнивал его сам с собой.
  const rows = page.locator('tbody tr');
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();

  // Список → задача → дело: отбор едет с человеком состоянием перехода.
  await page.locator('tbody tr').first().getByRole('link').click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-\d+$/);
  // Точное имя: «Открыть всё дело лентой» внизу карточки ведёт туда же и попала бы
  // под неточное совпадение.
  await page.getByRole('link', { name: 'Дело', exact: true }).click();
  await expect(page).toHaveURL(/\/case$/);

  // И обратно — одной ссылкой, а не тремя нажатиями «назад».
  await page.getByRole('link', { name: 'К списку с отбором' }).click();
  await expect(page).toHaveURL(new RegExp(`${listed.replace('?', '\\?').replace(/&/g, '&')}$`));
  await expect(rows).toHaveCount(before);
});

test('прямой вход в задачу зовёт ко всем задачам и говорит об этом', async ({ page }) => {
  await silenceJournal(page);

  // Чистый контекст: истории нет, отбору взяться неоткуда — и интерфейс не делает
  // вид, что он есть.
  await page.goto('/tasks/DEMO-3');

  const back = page.getByRole('link', { name: 'Ко всем задачам' });
  await expect(back).toHaveAttribute('href', '/tasks');
  await expect(page.getByRole('link', { name: 'К списку с отбором' })).toHaveCount(0);

  await back.click();
  await expect(page).toHaveURL(/\/tasks$/);
});

test('переключение «Карточка — Дело» видно с любой глубины прокрутки', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1/case');

  const toggle = page.getByRole('link', { name: 'Карточка', exact: true });
  await expect(toggle).toBeInViewport();

  // В конец дела: раньше отсюда наверх вела только кнопка браузера.
  await page.keyboard.press('End');
  await page.mouse.wheel(0, 20_000);
  await expect(toggle).toBeInViewport();

  await toggle.click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-1$/);
});

test('номер записи вне отбора по типу объясняется, а не оставляет пустой экран', async ({
  page,
}) => {
  await silenceJournal(page);

  // Отбор оставляет только сводки, а названа запись `created` — она в отбор не попадает.
  await page.goto('/tasks/DEMO-1/case?type=summary&entry=1');

  await expect(page.getByText(/не попадает в отбор по типу/)).toBeVisible();

  await page.getByRole('button', { name: 'Показать все типы' }).click();
  // Точное совпадение: `DEMO-1#1` иначе находит и `DEMO-1#10`, и остальные.
  await expect(page.getByLabel('DEMO-1#1', { exact: true })).toHaveAttribute('data-highlighted');
});

test('номер записи, которой в деле нет, объясняется по-русски', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1/case?entry=999');

  await expect(page.getByText(/в деле нет/)).toBeVisible();
});

test('смена вида сохраняет отбор в обе стороны и не заводит второго пути', async ({ page }) => {
  await silenceJournal(page);

  const listed = '/tasks?queue=DEMO&status=open&status=in_progress&sort=key';
  await page.goto(listed);
  await expect(page.getByRole('table')).toBeVisible();

  // Таблица → доска: раньше отсюда уходили на голое `/tasks?view=board`, и очередь
  // с остальными условиями оставались позади молча.
  await page.getByRole('link', { name: 'Доска' }).click();
  await expect(page).toHaveURL(/view=board/);
  await expect(page).toHaveURL(/queue=DEMO/);
  await expect(page).toHaveURL(/status=in_progress/);
  await expect(page).toHaveURL(/sort=key/);
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();

  // И обратно тем же правилом: адрес возвращается к исходному посимвольно.
  await page.getByRole('link', { name: 'Таблица' }).click();
  await expect(page).toHaveURL(new RegExp(`${listed.replace('?', '\\?')}$`));

  // Второй точки переключения вида в интерфейсе нет: в шапке доска не раздел.
  await expect(page.getByRole('link', { name: 'Доска' })).toHaveCount(1);
});

test('возврат с доски в задачу и назад сохраняет и вид, и условия', async ({ page }) => {
  await silenceJournal(page);

  await page.goto('/tasks?queue=DEMO&view=board&assignee=demo_agent');
  const card = page.getByRole('article').first();
  await expect(card).toBeVisible();
  await card.getByRole('link').first().click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-\d+$/);

  // Место не врёт: очередь задачи прочитана из её ключа и подсвечена в панели —
  // подробнее это проверяет `side.spec.ts`.
  await expect(page.getByLabel('Где я')).toContainText('DEMO');

  await page.getByRole('link', { name: 'К списку с отбором' }).click();
  await expect(page).toHaveURL(/view=board/);
  await expect(page).toHaveURL(/assignee=demo_agent/);
});

test('из входящей ссылка «Все задачи» ведёт ко всем задачам, а не в чужой отбор', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/questions');

  const section = page.getByRole('link', { name: 'Все задачи' });
  await expect(section).toHaveAttribute('href', '/tasks');
  await section.click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(page.getByRole('link', { name: 'Доска' })).toBeVisible();
});
