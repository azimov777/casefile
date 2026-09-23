import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

/**
 * Чтение замечаний на живых демо-данных: в наборе есть закрытая задача с двумя
 * замечаниями человека — одно разобрано с исходом «принято в работу», второе ждёт
 * (`../app/services/demo.py`). Сценарий только читает и потому идёт в обеих
 * темах вместе с остальными читающими.
 */
test('неразобранное замечание видно на карточке закрытой задачи', async ({ page }) => {
  await page.goto('/tasks/DEMO-1');

  const remarks = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: 'Замечания' }) });
  await expect(remarks.getByText(/В отказе не видно/)).toBeVisible();

  // Действие есть и на закрытой задаче: именно на сделанное человек и смотрит, когда
  // говорит «вышло не то». Кнопка живёт в липкой навигации задачи (UI-25).
  await expect(
    page
      .getByRole('navigation', { name: /Навигация по задаче/ })
      .getByRole('button', { name: 'Оставить замечание' }),
  ).toBeVisible();
  // Именно статус шапки: слово `done` встречается и в теле сводки, и в описи. С UI-143
  // он стоит значением под подписью «Статус» в полосе свойств.
  await expect(
    page
      .locator('main header dl > div')
      .filter({ has: page.getByRole('term').getByText('Статус', { exact: true }) })
      .getByRole('definition'),
  ).toHaveText('done');
});

test('разбор стоит под своим замечанием, называет исход словами и ведёт в продолжение', async ({
  page,
}) => {
  await page.goto('/tasks/DEMO-1/case');

  // Полный заголовок замечания: слова «дыры в нумерации» стоят ещё и в теле решения,
  // которое эти дыры допустило, — короткий фильтр хватал бы его.
  const remark = page
    .getByRole('article')
    .filter({ hasText: 'Дыры в нумерации сбивают с толку' })
    .first();
  await expect(remark.getByText(/принято в работу/)).toBeVisible();

  // Ключ продолжения — ссылка: по ней человек уходит смотреть, где идёт работа.
  await remark.getByRole('link', { name: 'DEMO-2' }).first().click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-2/);
  await expect(page.getByRole('heading', { name: /DEMO-2/ })).toBeVisible();
  await expect(page.getByText('in_progress').first()).toBeVisible();
});

test('признак «замечаний» стоит в строке списка и на карточке доски, и по нему отбирают', async ({
  page,
}) => {
  await page.goto('/tasks?queue=DEMO');

  const row = page.getByRole('row').filter({ hasText: 'DEMO-1' });
  await expect(row.getByText('1 замечание без разбора')).toBeVisible();

  // Признак в панели отбора оставляет только задачи с неразобранными замечаниями.
  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await page.getByRole('button', { name: 'есть неразобранные замечания' }).click();
  await expect(page).toHaveURL(/remarks=true/);
  await expect(page.getByRole('row').filter({ hasText: 'DEMO-' })).toHaveCount(1);

  // На доске тот же признак: он живёт в одном представлении на оба вида. Столбцы
  // `done` и `cancelled` свёрнуты по умолчанию, а замечание висит на закрытой задаче,
  // поэтому адрес разворачивает всё — пустым `collapsed`.
  await page.goto('/tasks?queue=DEMO&view=board&collapsed=');
  // Карточка доски — `article` с ключом: ссылка на ней носит название задачи, а не
  // ключ, и признак лежит рядом с ней, а не внутри.
  await expect(
    page.getByRole('article').filter({ hasText: 'DEMO-1' }).getByText('1 замечание без разбора'),
  ).toBeVisible();
});

test('входящая показывает мои неразобранные замечания второй половиной', async ({ page }) => {
  await page.goto('/questions');

  const section = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: 'Мои замечания без разбора' }) });
  await expect(section.getByText(/В отказе не видно/)).toBeVisible();
  await expect(section.getByRole('link', { name: /^DEMO-1#\d+$/ })).toBeVisible();
});

test('карточка задачи и входящая с замечаниями проходят axe', async ({ page }) => {
  for (const address of ['/tasks/DEMO-1', '/questions']) {
    await page.goto(address);
    await expect(page.getByRole('heading').first()).toBeVisible();

    const scan = await new AxeBuilder({ page }).analyze();
    expect(scan.violations, `${address}: ${JSON.stringify(scan.violations, null, 2)}`).toEqual([]);
  }
});
