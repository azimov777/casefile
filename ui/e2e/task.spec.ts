import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, motionSettled, silenceJournal } from './contour';

/** Строка описи по заголовку записи: номер записи зависит от истории задачи, заголовок — нет. */
function entryRow(page: Page, title: string) {
  return page.getByRole('row').filter({ has: page.getByRole('button', { name: title }) });
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
  await expect(card.getByText(/^заблокирована/)).toBeVisible();

  // Кто именно держит — видно из связей, с ключом и статусом другой стороны.
  const links = page.getByRole('region', { name: 'Связи' });
  await expect(links.getByRole('link', { name: 'DEMO-2' })).toBeVisible();
  await expect(links.getByText('blocked_by')).toBeVisible();

  // Сводка целиком, без клика.
  const summary = page.getByRole('region', { name: 'Последняя сводка' });
  for (const part of ['Сделано', 'Осталось', 'Что мешает', 'Следующий шаг']) {
    await expect(summary.getByText(part, { exact: true })).toBeVisible();
  }

  await expect(page.getByText('В деле 7 записей')).toBeVisible();
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

  const row = entryRow(page, 'Обзорная проверка 2');
  const no = (await row.getByRole('rowheader').innerText()).trim();
  await row.getByRole('button', { name: /Обзорная проверка 2/ }).click();

  await expect(row).toContainText('failed');
  // Текст проверки берётся из `checks` задачи по номеру: в записи его нет.
  const body = page.getByRole('cell').filter({ hasText: 'Неприменимый оператор' });
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
  const no = (await entryRow(page, 'Задача заведена').getByRole('rowheader').innerText()).trim();

  await page.goto(`/tasks/DEMO-6?entry=${no}`);

  await expect(page.getByRole('button', { name: 'Задача заведена' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
});

/*
 * UI-126: раскрытие записи в описи не должно дёргать прокрутку. Раньше `IndexRow`
 * звал `scrollIntoView({ block: 'center' })` на каждом клике — не только при
 * переходе по ссылке `TRK-42#12`, ради которого движение и было написано, — потому
 * что раскрытие руками тоже пишет номер записи в адрес (`rememberOpen`), и следующая
 * отрисовка видела тот же признак, что и переход по ссылке.
 *
 * DEMO-1 — единственная задача демо с длинной описью (за порогом `LONG_INDEX`, отсюда
 * кнопка «К свежей записи») и записью `section_changed` «Правка раздела goal» —
 * тем самым примером, которым описан дефект.
 */
test('раскрытие записи в длинной описи не двигает прокрутку: строка остаётся, где по ней кликнули', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1');
  await fontsReady(page);

  // Опись действительно длинная: короткая кнопки прыжков не показывает вовсе
  // (`в короткой описи прыжков нет` выше).
  await expect(page.getByRole('button', { name: 'К свежей записи' })).toBeVisible();

  const row = entryRow(page, 'Правка раздела goal');
  const button = row.getByRole('button', { name: 'Правка раздела goal' });

  /** Положение строки в документе — не в окне: важно, не съехала ли сама прокрутка. */
  async function documentTop(): Promise<number> {
    const box = await row.boundingBox();
    return box === null ? -1 : box.y + (await page.evaluate(() => window.scrollY));
  }

  await expect(row).toBeVisible();
  const target = (await documentTop()) - (page.viewportSize()?.height ?? 720) / 2;
  // «Прокрутить к середине»: запись видна примерно посередине окна, а не у края, —
  // положение, которое центрирующий прыжок обязан был бы менять, а не удержать.
  await page.evaluate((y) => window.scrollTo(0, Math.max(0, y)), target);

  const before = { scrollY: await page.evaluate(() => window.scrollY), top: await documentTop() };
  expect(before.top).toBeGreaterThan(0);

  await button.click();

  // Тело раскрытой записи пришло и видно целиком — раньше, чем судить о прокрутке.
  await expect(page.getByText('Было', { exact: true })).toBeVisible();
  await expect(page.getByText('Стало', { exact: true })).toBeVisible();
  // Само раскрытие едет строками сетки (`Reveal`): движение обязано улечься до замера,
  // иначе кадр посреди хода — это шум, а не то, что человек видит в покое.
  await motionSettled(page.locator('[data-reveal="place"]'));

  const after = { scrollY: await page.evaluate(() => window.scrollY), top: await documentTop() };
  expect(Math.abs(after.scrollY - before.scrollY)).toBeLessThanOrEqual(1);
  expect(Math.abs(after.top - before.top)).toBeLessThanOrEqual(1);

  // Свернуть обратно — тот же путь, то же требование: закрытие тоже не прыгает.
  await button.click();
  await expect(page.getByText('Было', { exact: true })).toBeHidden();
  await motionSettled(page.locator('tbody'));
  expect(
    Math.abs((await page.evaluate(() => window.scrollY)) - before.scrollY),
  ).toBeLessThanOrEqual(1);
});

test('переход по ссылке на запись в конце длинной описи по-прежнему приводит её в поле зрения', async ({
  page,
}) => {
  await page.goto('/tasks/DEMO-1');
  // Второе, неразобранное замечание — гарантированно последняя запись дела DEMO-1
  // (`_remarks_on_done` дописывает его последним), а значит и последняя строка
  // длинной описи: без прокрутки её не видно ни при какой высоте окна.
  const title = 'В отказе не видно, какой именно номер не был выдан';
  const last = entryRow(page, title);
  const no = (await last.getByRole('rowheader').innerText()).trim();

  await page.goto(`/tasks/DEMO-1?entry=${no}`);

  const opened = entryRow(page, title).getByRole('button', { name: title });
  await expect(opened).toHaveAttribute('aria-expanded', 'true');
  await expect(opened).toBeInViewport();
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
  // Ссылка в строке одна и названа названием задачи: в задачу ведёт вся строка,
  // а ключ перестал быть единственной мишенью (`task-row.tsx`).
  await page
    .getByRole('row')
    .filter({ has: page.getByRole('rowheader', { name: 'DEMO-6' }) })
    .getByRole('link')
    .click();
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
  expect(closed.violations).toEqual([]);

  // И с открытой панелью «Фильтр»: у переключателей свои подписи и свои группы.
  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await page
    .getByRole('dialog', { name: 'Типы записей' })
    .getByRole('button', { name: 'Записи агента', exact: true })
    .click();
  await expect(page.getByRole('article').first()).toBeVisible();

  const filtered = await new AxeBuilder({ page }).analyze();
  expect(filtered.violations).toEqual([]);
});

test('доступность карточки задачи', async ({ page }) => {
  await page.goto('/tasks/DEMO-6');
  await expect(page.getByText('В деле 7 записей')).toBeVisible();

  const closed = await new AxeBuilder({ page }).analyze();
  expect(closed.violations).toEqual([]);

  await page.getByRole('button', { name: /Обзорная проверка 2/ }).click();
  await expect(page.getByText('Неприменимый оператор').first()).toBeVisible();

  const opened = await new AxeBuilder({ page }).analyze();
  expect(opened.violations).toEqual([]);
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

  // Отбор «Служебные» из панели «Фильтр» (UI-137) оставляет только записи трекера.
  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await page
    .getByRole('dialog', { name: 'Типы записей' })
    .getByRole('button', { name: 'Служебные', exact: true })
    .click();
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

/*
 * Шапка карточки читается группами (UI-143, вариант B из UI-143#10). Раньше очередь,
 * название, строка статуса и строка дат стояли на одном шаге 8 px, и статус был
 * одинаково близок к названию и к датам. Теперь состояние и время — одна полоса
 * свойств между линиями, где время отделено явным разрывом в правом конце полосы,
 * а строка действий отделена от шапки сильнее любого зазора внутри неё. DEMO-5 — с
 * родителем в строке «где», DEMO-1 — с признаками в полосе.
 */
for (const key of ['DEMO-1', 'DEMO-5']) {
  test(`шапка ${key} на 1440: группы разведены, статус не спорит с датами`, async ({ page }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/tasks/${key}`);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(key);
    await fontsReady(page);

    const box = async (selector: string) => {
      const found = await page.locator(selector).first().boundingBox();
      expect(found, selector).not.toBeNull();
      return found as { x: number; y: number; width: number; height: number };
    };
    /** Ячейка полосы по её подписи: `div` с `dt` внутри. */
    const cell = async (label: string) => {
      const found = await page
        .locator('main header dl > div')
        .filter({ has: page.getByRole('term').getByText(label, { exact: true }) })
        .boundingBox();
      expect(found, label).not.toBeNull();
      return found as { x: number; y: number; width: number; height: number };
    };

    const nav = await box('main > nav');
    const where = await box('main header p');
    const title = await box('main header h1');
    const strip = await box('main header dl');
    const status = await cell('Статус');
    const priority = await cell('Приоритет');
    const assignee = await cell('Исполнитель');
    const updated = await cell('Обновлена');

    // Зазоры внутри шапки: «где» → название, название → полоса.
    const inside = [title.y - (where.y + where.height), strip.y - (title.y + title.height)];
    const navGap = where.y - (nav.y + nav.height);
    expect(Math.min(...inside)).toBeGreaterThanOrEqual(0);
    expect(navGap).toBeGreaterThan(Math.max(...inside));

    // Статус и время — в полосе, ограниченной линиями сверху и снизу.
    const borders = await page
      .locator('main header dl')
      .evaluate((node) => [
        getComputedStyle(node).borderTopWidth,
        getComputedStyle(node).borderBottomWidth,
      ]);
    expect(borders.map((width) => parseFloat(width))).toEqual([1, 1]);
    for (const part of [status, updated]) {
      expect(part.y).toBeGreaterThanOrEqual(strip.y);
      expect(part.y + part.height).toBeLessThanOrEqual(strip.y + strip.height);
    }

    // Время отделено от состояния явным разрывом: он больше шага между ячейками
    // состояния по меньшей мере вчетверо.
    const step = priority.x - (status.x + status.width);
    const lastState = Math.max(
      ...(await page
        .locator('main header dl > div')
        .evaluateAll((cells) =>
          cells
            .filter((c) => !/Обновлена|Заведена/.test(c.querySelector('dt')?.textContent ?? ''))
            .map((c) => c.getBoundingClientRect().right),
        )),
    );
    expect(assignee.x).toBeGreaterThan(priority.x);
    expect(updated.x - lastState).toBeGreaterThan(step * 4);
  });
}
