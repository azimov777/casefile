import { expect, test, type Locator, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

function background(target: Locator): Promise<string> {
  return target.evaluate((node) => getComputedStyle(node).backgroundColor);
}

/** Знак статуса или приоритета в строке списка: форма и имя значения рядом. */
function mark(page: Page, kind: 'status' | 'priority', value: string): Locator {
  return (
    page
      .locator('tbody')
      .locator(`[data-mark="${kind}"]`)
      // Текст знака — это род и значение вместе: «статус in_progress». Род читается
      // диктором и не виден глазом, но в `textContent` он есть, и якорь `^…$` без него
      // не совпадёт ни с чем.
      .filter({ hasText: new RegExp(`^(?:статус|приоритет)\\s+${value}$`) })
      .first()
  );
}

/** Цвет формы: у знака красится сам рисунок, а не заливка под ним. */
function shapeColor(target: Locator): Promise<string> {
  return target.locator('svg').evaluate((node) => getComputedStyle(node).color);
}

test('статус читается тоном формы: работа, завершение и снятие покрашены по-разному', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr')).toHaveCount(7);

  const inProgress = await shapeColor(mark(page, 'status', 'in_progress'));
  const done = await shapeColor(mark(page, 'status', 'done'));
  const open = await shapeColor(mark(page, 'status', 'open'));

  // Ради чего задача и заводилась: «работают сейчас» и «сделано» были одним серым.
  expect(inProgress).not.toBe(done);
  expect(inProgress).not.toBe(open);
  expect(done).not.toBe(open);

  // Снятое по-прежнему отличается от остальных, но уже формой и своим цветом.
  const cancelled = await shapeColor(mark(page, 'status', 'cancelled'));
  expect(cancelled).not.toBe(done);
  expect(cancelled).not.toBe(inProgress);

  // Ожидание — единственный статус тона тревоги: ход не за агентом, а за человеком,
  // и это ровно то положение дел, которое меняет решение смотрящего. Янтарный он делит
  // с приоритетом `high` и открытым вопросом намеренно: тон называет положение дел,
  // а не сущность (`docs/notes/ui.md`).
  const waiting = await shapeColor(mark(page, 'status', 'waiting'));
  expect(waiting).not.toBe(open);
  expect(waiting).not.toBe(inProgress);
  expect(waiting).not.toBe(done);

  // Заливки у статуса больше нет вовсе: смысл несёт форма, цвет только помогает
  // (решение Д1). Плашка ушла — с ней ушёл и фон под ней.
  expect(await background(mark(page, 'status', 'cancelled'))).toBe('rgba(0, 0, 0, 0)');

  // Обычный ход дел остаётся серым: покрасив `open`, тон перестал бы что-то значить.
  expect(open).toBe(await shapeColor(mark(page, 'priority', 'normal')));
});

test('приоритет выше обычного виден взглядом: и high, и critical отличаются от normal', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  const normal = await shapeColor(mark(page, 'priority', 'normal'));
  expect(await shapeColor(mark(page, 'priority', 'high'))).not.toBe(normal);
  expect(await shapeColor(mark(page, 'priority', 'critical'))).not.toBe(normal);
});

/**
 * Тон тревоги носит не только `critical`: его же получает признак «заблокирована».
 * Проверяется он отдельно, потому что признак и приоритет — разные поводы для тревоги,
 * и разойтись они могут независимо.
 *
 * Раньше эта проверка была единственным способом сказать что-либо о `critical`: в демо
 * не было ни одной такой задачи. Теперь есть (`../tracker/app/services/demo.py`), и
 * различимость `critical` от `normal` проверяется прямо, соседним тестом.
 */
test('тон тревоги отличается от нейтрального', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  // После UI-31 признак — знак, а не плашка: заливки у него нет, и тревога выражена
  // цветом самого рисунка. Сравнивается он с нейтральной плашкой тега — единственной
  // нейтральной вещью, оставшейся в строке.
  const danger = await page
    .locator('tbody [data-mark="feature"]')
    .filter({ hasText: /^заблокирована/ })
    .first()
    .locator('svg')
    .evaluate((node) => getComputedStyle(node).color);
  const neutral = await page
    .locator('tbody [data-badge="neutral"]')
    .first()
    .evaluate((node) => getComputedStyle(node).color);

  expect(danger).not.toBe(neutral);
});

test('движение есть там, где оно отвечает на действие человека', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  // Проверка ниже требует, чтобы гасить было что: без этого «переход равен нулю»
  // проходило бы и на интерфейсе вовсе без переходов.
  await expect(page.getByRole('button', { name: 'Изменить отбор' })).not.toHaveCSS(
    'transition-duration',
    '0s',
  );
});

test('человек просит не двигать интерфейс — переходы гаснут', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  // `emulateMedia`, а не `contextOptions` в `test.use`: просьба не двигать интерфейс
  // приходит от системы в любой момент, и гасить движение надо на уже открытой
  // странице — ровно это здесь и проверяется.
  await page.emulateMedia({ reducedMotion: 'reduce' });

  // Сравнение числом, а не строкой: браузер печатает те же `0.01ms` то как
  // `0.0001s`, то как `1e-05s`, и проверка на текст ломалась бы от формата,
  // ничего не говоря о том, видно движение или нет.
  const duration = await page
    .getByRole('button', { name: 'Изменить отбор' })
    .evaluate((node) => Number.parseFloat(getComputedStyle(node).transitionDuration));

  expect(duration).toBeLessThan(0.001);
});
