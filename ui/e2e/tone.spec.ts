import { expect, test, type Locator, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/**
 * Плашка с точно таким текстом внутри таблицы. Область обязательна: подписи фильтров
 * над таблицей называются теми же словами контракта (`open`, `done`), и без `tbody`
 * поиск нашёл бы галочку отбора вместо плашки строки.
 */
function badge(page: Page, text: string): Locator {
  return page.locator('tbody').getByText(text, { exact: true }).first();
}

function background(target: Locator): Promise<string> {
  return target.evaluate((node) => getComputedStyle(node).backgroundColor);
}

test('статус читается тоном: работа, завершение и снятие рисуются разным фоном', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr')).toHaveCount(7);

  const inProgress = await background(badge(page, 'in_progress'));
  const done = await background(badge(page, 'done'));
  const cancelled = await background(badge(page, 'cancelled'));
  const open = await background(badge(page, 'open'));

  // Ради чего задача и заводилась: «работают сейчас» и «сделано» были одним серым.
  expect(inProgress).not.toBe(done);
  expect(inProgress).not.toBe(open);
  expect(done).not.toBe(open);

  // Снятое не занято ничем: заливки нет вовсе, и это видно без различения цвета.
  expect(cancelled).toBe('rgba(0, 0, 0, 0)');
  await expect(badge(page, 'cancelled')).toHaveCSS('border-style', 'dashed');

  // Обычный ход дел остаётся серым: покрасив `open`, тон перестал бы что-то значить.
  expect(open).toBe(await background(badge(page, 'normal')));
});

test('приоритет выше обычного виден взглядом: и high, и critical отличаются от normal', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  const normal = await background(badge(page, 'normal'));
  expect(await background(badge(page, 'high'))).not.toBe(normal);
  expect(await background(badge(page, 'critical'))).not.toBe(normal);
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

  const danger = await background(badge(page, 'заблокирована'));
  const neutral = await background(badge(page, 'normal'));

  expect(danger).not.toBe(neutral);
  expect(danger).not.toBe('rgba(0, 0, 0, 0)');
});

test('движение есть там, где оно отвечает на действие человека', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  // Проверка ниже требует, чтобы гасить было что: без этого «переход равен нулю»
  // проходило бы и на интерфейсе вовсе без переходов.
  await expect(page.getByRole('button', { name: 'Применить' })).not.toHaveCSS(
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
    .getByRole('button', { name: 'Применить' })
    .evaluate((node) => Number.parseFloat(getComputedStyle(node).transitionDuration));

  expect(duration).toBeLessThan(0.001);
});
