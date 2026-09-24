import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, motionSettled, readE2eToken, silenceJournal } from './contour';

/**
 * Родитель с длинным названием у двух задач (UI-119) и отказ второму родителю (UI-167).
 * Таких в демо нет, поэтому сценарий заводит их сам и потому идёт в проекте «запись».
 * Родителя из демо, как он есть, проверяет читающий `parents.spec.ts`.
 *
 * До TRK-135 здесь стояла задача с двумя родителями и подпись «+1». С TRK-135 родитель
 * у задачи один: второй `link` бэкенд отклоняет `409 task_has_parent`, и сценарий
 * проверяет этот отказ с обеих сторон связи, а не невозможное теперь состояние.
 */

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Исполнитель, по которому отбираются ровно задачи этого сценария. */
const PROBE = 'ui119_probe';

/**
 * Название родителя из путей этого же репозитория. Внутри слов нет ни пробела, ни
 * дефиса: косая черта, точка и подчёркивание перенос не разрешают, и такое слово
 * задаёт `min-content` подписи во всю свою длину — именно оно разводило столбец доски
 * вбок до UI-115. Выписано целиком, а не собрано из кусков: укоротившееся название
 * молча перестало бы проверять что-либо.
 */
const LONG_TITLE =
  'Подпись родителя на доске: src/entities/task/ui/task-parents.tsx, src/entities/task/ui/task-card.tsx и src/shared/i18n/dictionaries/ru/ui.ts';

/** Столбец, в котором рождаются новые задачи. */
const BORN = 'backlog';

async function create(request: APIRequestContext, title: string): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      project: 'DEMO',
      title,
      description: 'Заведена сквозным тестом UI-119: подпись родителя на карточке и в строке.',
      assignee: PROBE,
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

/** Ставит связь «`parent` — родитель `child`» со стороны родителя. */
async function adopt(request: APIRequestContext, parent: string, child: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${parent}/links`, {
    headers: auth(),
    data: { kind: 'parent', other: child },
  });
  expect(response.status(), `${parent} parent ${child}`).toBe(201);
}

/**
 * Второй родитель отклоняется с любой стороны связи: `parent` со стороны нового родителя
 * и `child` со стороны ребёнка — одна и та же строка (TRK-135). Отказ называет нынешнего
 * родителя в `details.parent`.
 */
async function refuseSecondParent(
  request: APIRequestContext,
  side: { key: string; kind: 'parent' | 'child'; other: string },
  current: string,
): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${side.key}/links`, {
    headers: auth(),
    data: { kind: side.kind, other: side.other },
  });
  expect(response.status(), `${side.key} ${side.kind} ${side.other}`).toBe(409);
  const { error } = (await response.json()) as {
    error: { code: string; details: { parent?: string } };
  };
  expect(error.code).toBe('task_has_parent');
  expect(error.details.parent).toBe(current);
}

/**
 * Уборка: отменённая задача без записей агента в архиве сразу (UI-97), и соседи по
 * проекту «запись» её больше не видят. Детей раньше родителей: родитель с незакрытыми
 * детьми не закрывается.
 */
async function cancel(request: APIRequestContext, key: string): Promise<void> {
  await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-119' },
  });
}

function column(page: Page, status: string): Locator {
  return page.getByRole('region', { name: status });
}

function cardOf(page: Page, title: string): Locator {
  return page
    .getByRole('article')
    .filter({ has: page.getByRole('link', { name: title, exact: true }) });
}

function caption(scope: Locator): Locator {
  return scope.locator('[data-mark="parents"]');
}

/** Геометрия подписи: одна ли строка, усечена ли ссылка, нет ли за ней числа «+N». */
async function measure(shown: Locator) {
  return shown.evaluate((node) => {
    const link = node.querySelector('a') as HTMLElement;
    const more = link.nextElementSibling as HTMLElement | null;
    const style = getComputedStyle(link);
    const box = node.getBoundingClientRect();
    return {
      height: link.getBoundingClientRect().height,
      line: parseFloat(style.lineHeight),
      wrap: style.whiteSpace,
      overflow: style.textOverflow,
      truncated: link.scrollWidth > link.clientWidth,
      title: link.getAttribute('title'),
      captionRight: box.right,
      more: more === null ? null : more.textContent,
    };
  });
}

/** Ширина столбца и то, не прокручивается ли он вбок от содержимого. */
async function lane(section: Locator) {
  return section.evaluate((node) => ({
    width: node.getBoundingClientRect().width,
    over: node.scrollWidth - node.clientWidth,
  }));
}

test('длинное название родителя — одна строка с многоточием, подсказка целиком, столбец той же ширины; второй родитель — отказ', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);

  const program = await create(request, LONG_TITLE);
  const second = await create(request, 'Второй родитель: доставка журнала без потерь');
  const single = await create(request, 'Карточка с родителем, чьё название — пути');
  const double = await create(request, 'Карточка, которой отказали во втором родителе');
  await adopt(request, program, single);
  await adopt(request, program, double);
  // Второй родитель — отказ с обеих сторон связи, и родитель у `double` остаётся прежним.
  await refuseSecondParent(request, { key: second, kind: 'parent', other: double }, program);
  await refuseSecondParent(request, { key: double, kind: 'child', other: second }, program);

  try {
    await silenceJournal(page);
    await page.setViewportSize({ width: 1440, height: 900 });

    /*
     * Ширина столбца без единой подписи: отбор, под который не подходит ни одна задача.
     * Ширина задана токеном `--ui-board-column`, и сравнивается она с той, что под
     * карточками с подписями, — а не с числом, выписанным здесь.
     */
    await page.goto('/tasks?project=DEMO&view=board&assignee=никого-с-таким-именем-нет');
    await expect(column(page, BORN)).toBeVisible();
    await expect(column(page, BORN).getByRole('article')).toHaveCount(0);
    await fontsReady(page);
    const empty = await lane(column(page, BORN));

    await page.goto(`/tasks?project=DEMO&view=board&assignee=${PROBE}`);
    const born = column(page, BORN);
    await expect(born.getByRole('article')).toHaveCount(4);
    await fontsReady(page);

    const one = cardOf(page, 'Карточка с родителем, чьё название — пути');
    const two = cardOf(page, 'Карточка, которой отказали во втором родителе');
    const top = cardOf(page, LONG_TITLE);
    await expect(caption(one)).toBeVisible();
    await expect(caption(two)).toBeVisible();
    await expect(caption(top)).toHaveCount(0);

    const filled = await lane(born);
    const oneShown = await measure(caption(one));
    const twoShown = await measure(caption(two));
    const cards = await born.getByRole('article').evaluateAll((nodes) =>
      nodes.map((node) => ({
        width: node.getBoundingClientRect().width,
        over: node.scrollWidth - node.clientWidth,
      })),
    );

    await test.info().attach('замеры подписи и столбца', {
      body: JSON.stringify({ empty, filled, single: oneShown, double: twoShown, cards }, null, 2),
      contentType: 'application/json',
    });
    const shot = await born.screenshot({ path: test.info().outputPath('board-backlog-light.png') });
    await test.info().attach('столбец backlog с подписями родителей', {
      body: shot,
      contentType: 'image/png',
    });

    // Столбец той же ширины, что без подписей, и вбок не прокручивается.
    expect(filled.width).toBe(empty.width);
    expect(filled.over).toBeLessThanOrEqual(0);
    // Карточки одной ширины — с подписью и без, — и ни одна не переполнена вбок.
    expect(new Set(cards.map((card) => card.width)).size).toBe(1);
    for (const card of cards) expect(card.over).toBeLessThanOrEqual(0);

    // Подпись — одна строка с многоточием, а полное название — в подсказке.
    expect(oneShown.height).toBeLessThanOrEqual(oneShown.line + 1);
    expect(oneShown.wrap).toBe('nowrap');
    expect(oneShown.overflow).toBe('ellipsis');
    expect(oneShown.truncated).toBe(true);
    expect(oneShown.title).toBe(`${program} · ${LONG_TITLE}`);

    // Задача, которой отказали во втором родителе: подпись та же, родитель один — прежний,
    // и числа «+N» за ссылкой нет (TRK-135).
    expect(twoShown.height).toBeLessThanOrEqual(twoShown.line + 1);
    expect(twoShown.truncated).toBe(true);
    expect(twoShown.title).toBe(`${program} · ${LONG_TITLE}`);
    expect(twoShown.more).toBeNull();
    expect(oneShown.more).toBeNull();
    await expect(caption(two)).not.toContainText(second);
    await expect(caption(two).getByRole('link')).toHaveAttribute('href', `/tasks/${program}`);

    // Тот же столбец в тёмной теме — снимком для дела, без проверок: сразу после смены
    // темы кадр бывает смешанным (`docs/notes/testing.md`), поэтому снимок — после покоя
    // переходов цвета у карточек.
    await page.emulateMedia({ colorScheme: 'dark' });
    await motionSettled(born);
    await born.screenshot({ path: test.info().outputPath('board-backlog-dark.png') });
    await page.emulateMedia({ colorScheme: 'light' });

    /*
     * Таблица: высота строки с подписью и без родителя одна до пикселя (решение Д4).
     */
    await page.goto(`/tasks?project=DEMO&assignee=${PROBE}&sort=key`);
    const rows = page.locator('tbody tr');
    await expect(rows).toHaveCount(4);
    await fontsReady(page);
    const heights = await rows.evaluateAll((nodes) =>
      nodes.map((node) => ({
        key: node.querySelector('th')?.textContent ?? '',
        height: node.getBoundingClientRect().height,
        parents: node.querySelector('[data-mark="parents"]') !== null,
      })),
    );
    await test.info().attach('высоты строк таблицы', {
      body: JSON.stringify(heights, null, 2),
      contentType: 'application/json',
    });
    const table = await page
      .locator('table')
      .screenshot({ path: test.info().outputPath('table-light.png') });
    await test.info().attach('таблица с подписями родителей', {
      body: table,
      contentType: 'image/png',
    });
    expect(heights.filter((row) => row.parents)).toHaveLength(2);
    expect(new Set(heights.map((row) => row.height)).size, JSON.stringify(heights)).toBe(1);

    /*
     * Проверка 1 UI-152: на 1440 px видимая ширина названия у дочерней задачи не меньше,
     * чем у задачи без родителя в той же таблице, и стоит оно на том же месте. Гнездо
     * под плашку одно у всех строк, поэтому ширины равны до пикселя.
     */
    const titles = await rows.evaluateAll((nodes) =>
      nodes.map((node) => {
        const span = node.querySelector('a[data-link="task"] span') as HTMLElement;
        const box = span.getBoundingClientRect();
        return {
          key: node.querySelector('th')?.textContent ?? '',
          parents: node.querySelector('[data-mark="parents"]') !== null,
          left: box.left,
          top: box.top - node.getBoundingClientRect().top,
          width: box.width,
          truncated: span.scrollWidth > span.clientWidth,
        };
      }),
    );
    await test.info().attach('название в строках на 1440 px (UI-152)', {
      body: JSON.stringify(titles, null, 2),
      contentType: 'application/json',
    });
    const withParent = titles.filter((row) => row.parents);
    const without = titles.filter((row) => !row.parents);
    expect(withParent).toHaveLength(2);
    expect(without).toHaveLength(2);
    for (const child of withParent) {
      for (const top of without) {
        expect(child.width, JSON.stringify(titles)).toBeGreaterThanOrEqual(top.width);
        expect(child.left).toBe(top.left);
        // Четверть пикселя по высоте даёт `truncate` (overflow: hidden сдвигает базовую
        // линию), а не родитель: у урезанного и неурезанного названия без родителя она та же.
        expect(Math.abs(child.top - top.top)).toBeLessThanOrEqual(0.5);
      }
    }

    // Плашка — «родитель KEY», без «+N»: родитель один (TRK-135); панель — одной ссылкой.
    const doubleRow = page.getByRole('row').filter({
      has: page.getByRole('link', {
        name: 'Карточка, которой отказали во втором родителе',
        exact: true,
      }),
    });
    const doubleBadge = doubleRow.locator('[data-mark="parents"]');
    await expect(doubleBadge).toHaveText(new RegExp(`^родитель\\s*${program}$`));
    // Ключ родителя в плашке виден целиком.
    const keyClipped = await doubleBadge
      .locator('.font-mono')
      .evaluate((node) => node.scrollWidth > node.clientWidth);
    expect(keyClipped).toBe(false);
    await doubleBadge.click();
    const panel = page.getByRole('dialog');
    await expect(panel).toContainText(`Родитель задачи ${double}`);
    await expect(panel.getByRole('link')).toHaveText([`${program} · ${LONG_TITLE}`]);
    // Длинное название родителя в панели переносится, а не режется, и панель не шире окна.
    const wrapped = await panel
      .getByRole('link')
      .first()
      .evaluate((node) => ({
        wrap: getComputedStyle(node).whiteSpace,
        over: node.scrollWidth - node.clientWidth,
        right: node.getBoundingClientRect().right,
      }));
    expect(wrapped.wrap).not.toBe('nowrap');
    expect(wrapped.over).toBeLessThanOrEqual(0);
    expect(wrapped.right).toBeLessThanOrEqual(1440);
    await page.keyboard.press('Escape');

    /*
     * Телефон: строка — карточка, плашка под названием только у дочерней задачи, мишень
     * не мельче 24 px (UI-154), и панель открывается нажатием — наведения там нет.
     */
    await page.setViewportSize({ width: 390, height: 844 });
    await fontsReady(page);
    const phone = await rows.evaluateAll((nodes) =>
      nodes
        .map((node) => node.querySelector('[data-mark="parents"]'))
        .filter((node): node is Element => node !== null)
        .map((node) => {
          const box = node.getBoundingClientRect();
          return { width: box.width, height: box.height };
        }),
    );
    await test.info().attach('плашка на 390 px', {
      body: JSON.stringify(phone),
      contentType: 'application/json',
    });
    expect(phone).toHaveLength(2);
    for (const box of phone) {
      expect(box.height).toBeGreaterThanOrEqual(24);
      expect(box.width).toBeGreaterThanOrEqual(24);
    }
    await doubleBadge.click();
    await expect(page.getByRole('dialog')).toContainText('Родитель задачи');
    const narrow = await page.getByRole('dialog').evaluate((node) => ({
      left: node.getBoundingClientRect().left,
      right: node.getBoundingClientRect().right,
    }));
    expect(narrow.left).toBeGreaterThanOrEqual(0);
    expect(narrow.right).toBeLessThanOrEqual(390);
    await page.keyboard.press('Escape');
  } finally {
    for (const key of [single, double, program, second]) await cancel(request, key);
  }
});
