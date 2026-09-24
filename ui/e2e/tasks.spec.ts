import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { shownKeys, side, silenceJournal, tasksByStatus } from './contour';

function rows(page: Page) {
  return page.locator('tbody tr');
}

function row(page: Page, key: string) {
  return page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: key }) });
}

test('отбор по статусу open даёт ровно открытые задачи демо и переживает перезагрузку', async ({
  page,
  request,
}) => {
  // Что открыто — по правде бэкенда, а не по памяти теста: выписанные здесь ключи
  // проверяли бы свежесть этой памяти, а не отбор. Именно так и вышло, когда задача,
  // ждавшая ответа владельца, ушла из `open` в `waiting` (TRK-15).
  const open = (await tasksByStatus(request)).get('open') ?? [];
  expect(open.length).toBeGreaterThan(0);

  await page.goto('/tasks?project=DEMO&status=open');

  await expect(rows(page)).toHaveCount(open.length);
  for (const key of open) {
    await expect(page.getByRole('rowheader', { name: key })).toBeVisible();
  }

  await page.reload();

  // Строка отбора называет условие словами, не заставляя открывать панель.
  await expect(page.getByRole('list', { name: 'Условия отбора' })).toContainText('статус open');

  // Проект стоит там, где он теперь живёт, — местом в боковой панели, а не полем
  // формы: подсветка переживает перезагрузку вместе с адресом (UI-38).
  await expect(side(page).getByRole('link', { name: /DEMO/ })).toHaveAttribute(
    'aria-current',
    'page',
  );

  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await expect(
    page
      .getByRole('dialog', { name: 'Условия отбора задач' })
      .getByRole('button', { name: 'статус open', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(rows(page)).toHaveCount(open.length);
});

test('признаки строки берутся из выдачи списка, без запроса на задачу', async ({
  page,
  request,
}) => {
  // Сколько строк — по правде бэкенда и без архива: `DEMO-7`, отменённая без единой
  // записи агента, в архиве с первой минуты (UI-97).
  const shown = await shownKeys(request);
  await silenceJournal(page);
  const calls: string[] = [];
  page.on('request', (call) => {
    if (call.url().includes('/api/v1/tasks')) calls.push(call.url());
  });

  await page.goto('/tasks?project=DEMO');
  await expect(rows(page)).toHaveCount(shown.length);

  await expect(row(page, 'DEMO-6').getByText(/^заблокирована/)).toBeVisible();
  // Блокирующий вопрос — не отдельный знак, а состояние знака вопросов: четвёртый
  // значок рядом с третьим перестаёт читаться (UI-31).
  await expect(
    row(page, 'DEMO-4').getByText('1 вопрос без ответа, из них 1 блокирующий'),
  ).toBeVisible();

  expect(calls.filter((url) => /\/api\/v1\/tasks\?/.test(url))).toHaveLength(1);
  expect(calls.filter((url) => /\/api\/v1\/tasks\/[^?]/.test(url))).toEqual([]);
});

test('опечатка в запросе объясняется позицией и списком допустимого, таблица остаётся', async ({
  page,
  request,
}) => {
  const shown = await shownKeys(request);
  await page.goto('/tasks?project=DEMO');
  await expect(rows(page)).toHaveCount(shown.length);

  await page.getByRole('button', { name: 'Запрос', exact: true }).click();
  await page.getByLabel('Запрос на языке бэкенда').fill('status: opne');
  await page.getByRole('button', { name: 'Применить' }).click();

  // Запрос ушёл склеенным с правилом архива, а символ назван в строке человека.
  const problem = page.getByRole('alert');
  await expect(problem).toContainText('Ошибка в символе 9');
  await expect(problem).toContainText('open');
  await expect(rows(page)).toHaveCount(shown.length);
});

test('сортировка живёт в адресе: вторая вкладка по той же ссылке показывает то же самое', async ({
  page,
  context,
}) => {
  await page.goto('/tasks?project=DEMO');

  // Дожидаемся именно пересортированной выдачи, а не только смены адреса: до её
  // прихода таблица показывает прежний порядок, и снятое с неё значение сравнивалось
  // бы с порядком второй вкладки, которая ждать не обязана.
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/tasks?') && response.url().includes('sort=key'),
    ),
    // Сортировка — список Radix: открывается кнопкой, значение выбирается пунктом.
    (async () => {
      await page.getByRole('combobox', { name: 'Сортировка' }).click();
      await page.getByRole('option', { name: 'по ключу', exact: true }).click();
    })(),
  ]);

  await expect(page).toHaveURL(/sort=key/);
  const first = await rows(page).first().locator('th').innerText();

  const copy = await context.newPage();
  await copy.goto(page.url());

  await expect(copy.getByRole('combobox', { name: 'Сортировка' })).toContainText('по ключу');
  expect(await rows(copy).first().locator('th').innerText()).toBe(first);
  await copy.close();
});

test('пустая выдача объясняется и предлагает сброс', async ({ page }) => {
  await page.goto('/tasks?project=DEMO&text=такоготочнонет');

  await expect(page.getByText('Задач по этим условиям нет')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сбросить фильтры' })).toBeEnabled();
});

/**
 * Ссылка на страницу, которой в этой выдаче нет: её переслали до того, как отбор сузили,
 * или просто набрали руками. Бэкенд отвечает на смещение за концом выдачи пустой
 * страницей и прежним `total` (TRK-41) — значит, экран обязан сказать, что задачи есть,
 * просто не здесь, и дать чем вернуться.
 *
 * Раньше отсюда проверялся негодный курсор в адресе. Курсора в адресе таблицы больше
 * нет — страница адресуется номером (UI-65), — и взять 4xx из адреса списка нечем:
 * негодный номер читается как первая страница. Отказ по коду проверяет
 * `resilience.spec.ts`, подменяя ответ в браузере.
 */
test('ссылка на страницу за концом выдачи объясняется и возвращает рядом', async ({ page }) => {
  await page.goto('/tasks?project=DEMO&page=99');

  await expect(page.getByText(/по этим условиям есть \d+ задач/)).toBeVisible();
  // Сброс отбора здесь ни при чём: условия нашли задачи, кончилась выдача.
  await expect(page.getByRole('button', { name: 'Сбросить фильтры' })).toHaveCount(0);

  const pager = page.getByRole('navigation', { name: 'Страницы выдачи' });
  await pager.getByRole('link', { name: 'Страница 1', exact: true }).click();

  await expect(page).not.toHaveURL(/page=/);
  await expect(rows(page).first()).toBeVisible();
});

test('доступность списка задач', async ({ page, request }) => {
  const shown = await shownKeys(request);
  await page.goto('/tasks?project=DEMO');
  await expect(rows(page)).toHaveCount(shown.length);

  // Панель надо открыть: закрытую её `axe` не увидит, а проверять надо и её —
  // сценарий идёт в обеих темах, и переключатели в тёмной проверены только отсюда.
  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Условия отбора задач' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.keyboard.press('Escape');

  // И режим запроса: его поле живёт вместо поиска и панели.
  await page.getByRole('button', { name: 'Запрос', exact: true }).click();
  await expect(page.getByLabel('Запрос на языке бэкенда')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
