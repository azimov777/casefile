import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

/**
 * Мишени нажатия на телефоне не мельче 24×24 px (WCAG 2.2 SC 2.5.8, UI-154).
 *
 * Ширина телефона взята той же, что аудит UI-149 (390 px): выше этой точки плотность
 * важнее (`ui/docs/CONCEPT.md`, §6), и сюда мишени не растят.
 */
const WIDTH = 390;
const HEIGHT = 844;
const MIN = 24;

/**
 * Четыре экрана из проверки задачи — с тем, чего дождаться перед замером.
 *
 * `getByRole('main')` подтверждает только каркас: опись и лента приходят отдельным
 * запросом и дорисовываются кадром позже. Без своего ожидания замер через раз ловит
 * страницу без них — мишени открытия записи (кнопка строки описи, `IndexRow`) тогда
 * не попадают в выдачу вовсе, и проверка молчит о том, что должна была найти.
 */
const SCREENS: [string, string, (page: Page) => Promise<unknown>][] = [
  [
    'подключить агента',
    '/connect',
    (page) => expect(page.getByRole('navigation', { name: 'Клиент' })).toBeVisible(),
  ],
  [
    'карточка задачи',
    '/tasks/DEMO-3',
    (page) => expect(page.locator('tbody tr').first()).toBeVisible(),
  ],
  ['дело', '/tasks/DEMO-3/case', (page) => expect(page.locator('article').first()).toBeVisible()],
  [
    'список задач',
    '/tasks?queue=DEMO',
    (page) => expect(page.locator('tbody tr').first()).toBeVisible(),
  ],
];

interface Target {
  tag: string;
  label: string;
  width: number;
  height: number;
}

/**
 * Все самостоятельные мишени нажатия страницы: кнопки и флажки вместе с их подписью.
 *
 * Флажок меряется по `label`, который его оборачивает, — не голым `input`: подпись
 * кликабельна, и мишень нажатия человек видит именно такой (`UI-154`).
 * `[role=tab]` этот стек не заводит нигде (`SegmentedNavLink` — настоящая ссылка,
 * решение UI-128): для вкладок-ссылок клиента на `/connect` есть отдельная проверка
 * ниже, по имени дорожки, а не по роли, которой у них нет и не должно быть.
 *
 * Элементы нулевого размера (`display: none`, свёрнутая панель) пропускаются: правило
 * действует, пока мишень показана, а не когда её нет на экране.
 */
async function tapTargets(page: Page): Promise<Target[]> {
  return page.evaluate(() => {
    const nodes = Array.from(
      document.querySelectorAll<HTMLElement>('button, [role="tab"], input[type="checkbox"]'),
    );

    return nodes
      .map((node) => {
        const target =
          node instanceof HTMLInputElement && node.type === 'checkbox'
            ? (node.closest('label') ?? node)
            : node;
        const rect = target.getBoundingClientRect();
        return {
          tag: node.tagName.toLowerCase(),
          label: (node.getAttribute('aria-label') ?? target.textContent ?? '').trim().slice(0, 60),
          width: rect.width,
          height: rect.height,
        };
      })
      .filter((item) => item.width > 0 && item.height > 0);
  });
}

for (const [name, url, ready] of SCREENS) {
  test(`мишени нажатия не мельче 24×24 px на 390: ${name}`, async ({ page }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width: WIDTH, height: HEIGHT });
    await page.goto(url);
    await expect(page.getByRole('main')).toBeVisible();
    await ready(page);
    await fontsReady(page);

    const targets = await tapTargets(page);
    // Пустая выдача не значит «проверка прошла» — значит, страница ещё не отрисована.
    expect(targets.length, `${url}: на странице не нашлось ни одной мишени`).toBeGreaterThan(0);

    for (const target of targets) {
      expect(
        Math.min(target.width, target.height),
        `${url} — «${target.label}» (${target.tag}): ${target.width}×${target.height}`,
      ).toBeGreaterThanOrEqual(MIN);
    }
  });
}

test('ссылки вне абзацев не мельче 24×24 px на 390: возврат и крошка очереди', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });

  // «← Ко всем задачам»: единственная ссылка возврата в липкой навигации задачи.
  await page.goto('/tasks/DEMO-3');
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  const back = await page.getByRole('link', { name: 'Ко всем задачам' }).boundingBox();
  expect(back, 'ссылка «← Ко всем задачам» не найдена').not.toBeNull();
  expect(Math.min(back!.width, back!.height), '← Ко всем задачам').toBeGreaterThanOrEqual(MIN);

  // Крошка очереди — ссылка только на карточке и в деле (на самом списке она текущее
  // место, не ссылка): демо-очередь `DEMO` шире 24 px даже без минимума, поэтому здесь
  // же проверяется и вычисленный `min-width`, а не только по случаю широкий рендер —
  // короткие ключи (`UI`, `TRK` на установке владельца) без него остались бы мельче.
  const crumb = page.getByRole('link', { name: 'DEMO', exact: true });
  const crumbBox = await crumb.boundingBox();
  expect(crumbBox, 'крошка очереди «DEMO» не найдена').not.toBeNull();
  expect(Math.min(crumbBox!.width, crumbBox!.height), 'крошка очереди').toBeGreaterThanOrEqual(MIN);

  const minWidth = await crumb.evaluate((node) => getComputedStyle(node).minWidth);
  expect(minWidth, 'крошка очереди: вычисленный min-width').toBe('24px');
});

test('вкладки клиента на /connect не мельче 24×24 px на 390', async ({ page }) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });
  await page.goto('/connect');
  await expect(page.getByRole('main')).toBeVisible();
  await fontsReady(page);

  // Дорожка клиентов на узком экране — сетка два на два (`ConnectionSnippets`), а не
  // строка: `items-stretch` там ничего не тянет, и вкладку от голой строки текста
  // отделяет только её собственный `min-height` (UI-154).
  //
  // Дорожка стоит в дереве только после ответа `installation`: без ожидания `.all()`
  // снимает пустой список раньше, чем компонент вообще появился, и проверка молчит
  // о том, что должна была найти.
  const nav = page.getByRole('navigation', { name: 'Клиент' });
  await expect(nav).toBeVisible();
  const tabs = await nav.getByRole('link').all();
  expect(tabs.length).toBeGreaterThan(0);

  for (const tab of tabs) {
    const box = await tab.boundingBox();
    expect(box, 'вкладка клиента без рамки').not.toBeNull();
    const name = (await tab.textContent())?.trim() ?? '';
    expect(Math.min(box!.width, box!.height), `вкладка «${name}»`).toBeGreaterThanOrEqual(MIN);
  }
});

/**
 * Чип отбора (`FilterChip`) и «Сбросить» (`FilterResetButton`) не рендерятся вовсе, пока
 * условие не применено, — экраны из `SCREENS` их поэтому не ловят (UI-164). Общий кирпич
 * `shared/ui/filter-chip.tsx` держит отбор задач и отбор записей дела одним компонентом,
 * но замер на каждой странице свой: у кнопки-текста и крестика чипа разные проверяемые
 * подписи, а без применённого условия сама мишень не появляется на экране.
 */
test('чип отбора и «Сбросить» не мельче 24×24 px на 390: список задач с условием', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });
  await page.goto('/tasks?queue=DEMO&status=open');
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  // Кнопка-текст чипа: открывает панель «Фильтр» — вторая мишень, отдельная от крестика.
  const chipText = page.getByRole('button', { name: 'статус open', exact: true });
  const textBox = await chipText.boundingBox();
  expect(textBox, 'кнопка-текст чипа «статус open» не найдена').not.toBeNull();
  expect(
    Math.min(textBox!.width, textBox!.height),
    'чип «статус open»: кнопка-текст',
  ).toBeGreaterThanOrEqual(MIN);

  const chipRemove = page.getByRole('button', { name: 'Убрать условие: статус open' });
  const removeBox = await chipRemove.boundingBox();
  expect(removeBox, 'крестик чипа «статус open» не найден').not.toBeNull();
  expect(
    Math.min(removeBox!.width, removeBox!.height),
    'чип «статус open»: крестик',
  ).toBeGreaterThanOrEqual(MIN);

  const reset = page.getByRole('button', { name: 'Сбросить', exact: true });
  const resetBox = await reset.boundingBox();
  expect(resetBox, 'кнопка «Сбросить» не найдена').not.toBeNull();
  expect(Math.min(resetBox!.width, resetBox!.height), '«Сбросить»').toBeGreaterThanOrEqual(MIN);
});

test('чип отбора и «Сбросить» не мельче 24×24 px на 390: дело с отбором записей', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: WIDTH, height: HEIGHT });
  // DEMO-1 — единственная демо-задача с записью `decision` в деле (`_done_task`),
  // отбор по типу без совпадений оставил бы страницу без самого дела, но не без
  // строки отбора — чипу для рендера совпадения не нужны, только применённое условие.
  await page.goto('/tasks/DEMO-1/case?type=decision');
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.locator('article').first()).toBeVisible();
  await fontsReady(page);

  const chipText = page.getByRole('button', { name: 'decision', exact: true });
  const textBox = await chipText.boundingBox();
  expect(textBox, 'кнопка-текст чипа «decision» не найдена').not.toBeNull();
  expect(
    Math.min(textBox!.width, textBox!.height),
    'чип «decision»: кнопка-текст',
  ).toBeGreaterThanOrEqual(MIN);

  const chipRemove = page.getByRole('button', { name: 'Убрать тип: decision' });
  const removeBox = await chipRemove.boundingBox();
  expect(removeBox, 'крестик чипа «decision» не найден').not.toBeNull();
  expect(
    Math.min(removeBox!.width, removeBox!.height),
    'чип «decision»: крестик',
  ).toBeGreaterThanOrEqual(MIN);

  const reset = page.getByRole('button', { name: 'Сбросить', exact: true });
  const resetBox = await reset.boundingBox();
  expect(resetBox, 'кнопка «Сбросить» не найдена').not.toBeNull();
  expect(Math.min(resetBox!.width, resetBox!.height), '«Сбросить»').toBeGreaterThanOrEqual(MIN);
});

test.describe('тёмная тема', () => {
  test.use({ colorScheme: 'dark' });

  test('мишени нажатия не мельче 24×24 px на 390: карточка задачи', async ({ page }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width: WIDTH, height: HEIGHT });
    await page.goto('/tasks/DEMO-3');
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.locator('tbody tr').first()).toBeVisible();
    await fontsReady(page);

    const targets = await tapTargets(page);
    expect(targets.length).toBeGreaterThan(0);
    for (const target of targets) {
      expect(
        Math.min(target.width, target.height),
        `«${target.label}» (${target.tag}): ${target.width}×${target.height}`,
      ).toBeGreaterThanOrEqual(MIN);
    }
  });

  test('чип отбора и «Сбросить» не мельче 24×24 px на 390: список задач с условием', async ({
    page,
  }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width: WIDTH, height: HEIGHT });
    await page.goto('/tasks?queue=DEMO&status=open');
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.locator('tbody tr').first()).toBeVisible();
    await fontsReady(page);

    const chipText = page.getByRole('button', { name: 'статус open', exact: true });
    const textBox = await chipText.boundingBox();
    expect(textBox, 'кнопка-текст чипа «статус open» не найдена').not.toBeNull();
    expect(
      Math.min(textBox!.width, textBox!.height),
      'чип «статус open»: кнопка-текст',
    ).toBeGreaterThanOrEqual(MIN);

    const chipRemove = page.getByRole('button', { name: 'Убрать условие: статус open' });
    const removeBox = await chipRemove.boundingBox();
    expect(removeBox, 'крестик чипа «статус open» не найден').not.toBeNull();
    expect(
      Math.min(removeBox!.width, removeBox!.height),
      'чип «статус open»: крестик',
    ).toBeGreaterThanOrEqual(MIN);

    const reset = page.getByRole('button', { name: 'Сбросить', exact: true });
    const resetBox = await reset.boundingBox();
    expect(resetBox, 'кнопка «Сбросить» не найдена').not.toBeNull();
    expect(Math.min(resetBox!.width, resetBox!.height), '«Сбросить»').toBeGreaterThanOrEqual(MIN);
  });
});
