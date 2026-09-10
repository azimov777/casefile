import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { fontsReady, shellReady, silenceJournal } from './contour';

function row(page: Page, key: string): Locator {
  return page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: key }) });
}

/**
 * Ждёт, пока страница перестанет двигаться под замером.
 *
 * Шапка догружает участника и счётчик вопросов уже после первой отрисовки и при этом
 * меняет свою высоту — таблица под ней съезжает. Координата, снятая до этого, ведёт
 * мимо: клик приходится на соседнюю строку или на пустоту. В одиночном прогоне
 * успевало, в полном — нет.
 */
async function settled(page: Page): Promise<void> {
  await shellReady(page);
  await expect(page.locator('tbody tr').first()).toBeVisible();
}

/**
 * Протяжка мышью по тексту элемента: от левого края до правого по середине высоты.
 * `page.mouse`, а не `dragTo`: нужен именно жест выделения, а не перетаскивание.
 */
async function dragAcross(page: Page, target: Locator): Promise<void> {
  // Замер снимается тем шрифтом, которым страница будет жить: Fira приходит с
  // внешнего хоста и после подстановки двигает края ячейки на несколько пикселей.
  await fontsReady(page);
  const box = await target.boundingBox();
  if (box === null) throw new Error('Не найден элемент для протяжки');
  await page.mouse.move(box.x + 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 2, box.y + box.height / 2, { steps: 12 });
  await page.mouse.up();
}

test('в задачу ведёт название и пустое место строки, а не только ключ', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  // Название — самая широкая и самая заметная ячейка: раньше это был мёртвый текст.
  await row(page, 'DEMO-3').getByRole('link').click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-3$/);

  // Пустое место строки: последняя ячейка, с подписью времени. Ссылок в ней нет,
  // и уводит отсюда обработчик строки, а не растяжка (UI-39).
  await page.goBack();
  await settled(page);
  await row(page, 'DEMO-3').getByRole('cell').last().click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-3$/);
});

test('клик по ключу ведёт в ту же задачу: он перестал быть мишенью, но не перестал работать', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await settled(page);

  // Ключ ничем не перекрыт: человек целится в него и попадает в задачу, потому что
  // мишень — вся строка целиком, а не отдельные её куски.
  await row(page, 'DEMO-3').getByRole('rowheader').click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-3$/);
});

/**
 * Растяжка не должна отнять выделение у того, что выделяют: имени исполнителя,
 * времени. Название задачи в этот список не входит и не может входить —
 * оно и есть ссылка, а текст внутри ссылки Chromium протяжкой не выделяет вовсе
 * (проверено зондом, разбор в деле UI-16). Клик по названию важнее: ради него
 * задача и заведена.
 */
test('текст вне ссылки выделяется и не уводит со страницы', async ({ page }) => {
  await silenceJournal(page);
  // Отбор по исполнителю: нужны строки, у которых имя исполнителя вообще есть.
  await page.goto('/tasks?queue=DEMO&assignee=demo_agent');
  await settled(page);

  const assignee = page.locator('tbody tr').first().getByText('demo_agent', { exact: true });
  await dragAcross(page, assignee);

  expect(await page.evaluate(() => window.getSelection()?.toString() ?? '')).toContain(
    'demo_agent',
  );
  // Выделив имя, человек остался там, где был: протяжка — не намерение уйти.
  await expect(page).toHaveURL(/\/tasks\?/);
});

test('cmd-клик по строке открывает задачу второй вкладкой', async ({ page, context }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  const modifier = process.platform === 'darwin' ? 'Meta' : 'Control';
  const [opened] = await Promise.all([
    context.waitForEvent('page'),
    row(page, 'DEMO-3')
      .getByRole('link')
      .click({ modifiers: [modifier] }),
  ]);

  // Ждать надо адрес, а не загрузку: только что открытая вкладка успевает побывать
  // на `about:blank`, и `waitForLoadState` возвращается на ней же — тогда проверка
  // читает `blank` вместо пути задачи и падает через раз.
  await opened.waitForURL(/\/tasks\/DEMO-3$/);
  expect(new URL(opened.url()).pathname).toBe('/tasks/DEMO-3');
  // Исходная вкладка осталась там же: это настоящая ссылка, а не переход по клику.
  await expect(page).toHaveURL(/\/tasks\?/);
  await opened.close();

  // То же самое по пустому месту строки: ссылки там нет, и вторую вкладку открывает
  // обработчик строки. Жест человека один и тот же, значит и ответ обязан быть один.
  await settled(page);
  const [aside] = await Promise.all([
    context.waitForEvent('page'),
    row(page, 'DEMO-3')
      .getByRole('cell')
      .last()
      .click({ modifiers: [modifier] }),
  ]);

  await aside.waitForURL(/\/tasks\/DEMO-3$/);
  await expect(page).toHaveURL(/\/tasks\?/);
  await aside.close();
});

test('обход табом даёт одну остановку на строку, и фокус виден', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await settled(page);
  await expect(page.locator('tbody tr')).toHaveCount(7);

  // Ставим фокус на ссылку первой строки и считаем, сколько шагов до второй.
  const first = page.locator('tbody tr').first().getByRole('link');
  await first.focus();

  await page.keyboard.press('Tab');
  const second = page.locator('tbody tr').nth(1).getByRole('link');
  await expect(second).toBeFocused();

  // Обводку рисует сама строка, а не ссылка внутри неё: остановка одна на задачу,
  // и показать надо задачу целиком. Проверяется на `<tr>`, потому что растяжки,
  // которой это рисовалось раньше, больше нет (UI-39).
  const outline = await second.evaluate((node) => {
    const rowElement = node.closest('tr');
    if (rowElement === null) throw new Error('Ссылка названия оказалась вне строки таблицы');
    const style = getComputedStyle(rowElement);
    return { style: style.outlineStyle, width: style.outlineWidth };
  });
  expect(outline.style).not.toBe('none');
  expect(outline.width).not.toBe('0px');
});

test('доступность списка и доски с растянутой ссылкой', async ({ page }) => {
  await silenceJournal(page);

  for (const address of ['/tasks?queue=DEMO', '/tasks?queue=DEMO&view=board']) {
    await page.goto(address);
    const found = await new AxeBuilder({ page }).analyze();
    const serious = found.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => violation.id);
    expect(serious, address).toEqual([]);
  }
});

test('карточка доски ведёт в задачу целиком', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&view=board');
  await shellReady(page);

  const card = page.getByRole('article').filter({ hasText: 'DEMO-3' }).first();
  await expect(card).toBeVisible();

  // Пустое место карточки: левый верхний угол, отступ рядом с ключом. Точка задана
  // относительно самой карточки, поэтому Playwright пересчитает её в момент клика,
  // а не по замеру, снятому раньше.
  await card.click({ position: { x: 6, y: 6 }, force: true });
  await expect(page).toHaveURL(/\/tasks\/DEMO-3$/);

  await page.goBack();
  await page.getByRole('article').filter({ hasText: 'DEMO-3' }).first().getByRole('link').click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-3$/);
});
