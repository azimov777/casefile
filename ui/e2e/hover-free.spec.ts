import { expect, test } from '@playwright/test';
import { silenceJournal } from './contour';

/**
 * Смысл, который раньше жил только в подсказке `title`, достижим нажатием (UI-163): на
 * телефоне наведения нет. Ширина — телефонная (390 px, как аудит UI-149), и нажатие —
 * `tap`, а не `click`: касание не приносит наведения, и подсказка по пути не всплывёт.
 *
 * Сценарии только читают: нажатия меняют состояние экрана, а не установки.
 */
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

test('подробность живого потока открывается нажатием на индикатор', async ({ page }) => {
  // Поток не глушится: нужен настоящий «на связи», а не вечное «подключаемся».
  await page.goto('/tasks?queue=DEMO');
  const banner = page.getByRole('banner');
  await expect(banner.getByText('на связи')).toBeVisible();

  await banner.getByRole('button', { name: /Живой поток: на связи/ }).tap();
  const detail = page.getByRole('dialog');
  await expect(detail).toHaveText('Живой поток журнала открыт: экран обновляется сам');

  // Панель не вылезает за край узкого экрана.
  const box = await detail.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);

  await page.keyboard.press('Escape');
  await expect(detail).toBeHidden();
});

test('смысл признака в шапке задачи раскрывается нажатием на знак', async ({ page }) => {
  await silenceJournal(page);
  // У DEMO-6 в демо есть блокер: знак «заблокирована» стоит в шапке.
  await page.goto('/tasks/DEMO-6');
  const header = page.getByRole('main').locator('header').first();
  const phrase = /^заблокирована: есть связь blocked_by/;

  const mark = header.getByRole('button', { name: phrase });
  await expect(mark).toHaveAttribute('aria-pressed', 'false');
  // До нажатия фраза есть только для диктора: глазу виден один знак.
  await expect(mark.getByText(phrase)).toHaveClass(/\bsr-only\b/);
  const closed = (await mark.boundingBox())!.width;

  await mark.tap();
  await expect(mark).toHaveAttribute('aria-pressed', 'true');
  await expect(mark.getByText(phrase)).not.toHaveClass(/\bsr-only\b/);
  // Фраза встала строкой: кнопка стала шире знака, но не шире экрана.
  const open = (await mark.boundingBox())!;
  expect(open.width).toBeGreaterThan(closed);
  expect(open.x + open.width).toBeLessThanOrEqual(390);
});

test('в строке списка знак признака не перехватывает нажатие: оно ведёт в задачу', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  const mark = page
    .locator('tbody [data-mark="feature"]')
    .filter({ hasText: /^заблокирована/ })
    .first();
  await expect(mark).toBeVisible();
  const href = await mark
    .locator('xpath=ancestor::tr')
    .locator('[data-link="task"]')
    .getAttribute('href');
  expect(href).toMatch(/^\/tasks\/DEMO-\d+$/);
  await mark.tap();
  await expect(page).toHaveURL(new RegExp(`${href}$`));
});

test('значение набора токена раскрывается нажатием на плашку', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/access');

  // Ключ контура — набора `main` (TRK-69): такой доступ в списке есть всегда.
  const own = page.locator('article[data-token-scope="main"]').first();
  const scope = own.getByRole('button', { name: 'Что открывает набор main' });
  const hint = own.getByText('Рабочий цикл плюс запись реестров: участники, токены и очереди.');
  await expect(hint).toBeHidden();

  await scope.tap();
  await expect(scope).toHaveAttribute('aria-expanded', 'true');
  await expect(hint).toBeVisible();

  await scope.tap();
  await expect(hint).toBeHidden();
});
