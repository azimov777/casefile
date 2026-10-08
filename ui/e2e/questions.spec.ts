import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { fontsReady, side } from './contour';

test('доступность входящей', async ({ page }) => {
  await page.goto('/questions');
  await expect(page.getByRole('heading', { name: 'Входящая' })).toBeVisible();

  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

test('доступность истории вопросов', async ({ page }) => {
  await page.goto('/questions?view=history');
  await expect(page.getByRole('heading', { name: 'Вопросы и ответы' })).toBeVisible();
  await expect(page.getByRole('article').first()).toBeVisible();

  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
});

test('без параметров экран показывает входящую, а история — второй вид', async ({ page }) => {
  await page.goto('/questions');

  // Первый экран — входящая: обсуждения, задачи, закрытые не целиком, и мои замечания.
  const views = page.getByRole('navigation', { name: 'Вид входящей' });
  await expect(views.getByRole('link', { name: 'Ждут ответа' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  await expect(page.getByRole('heading', { name: 'Мои замечания без разбора' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Вопросы и ответы' })).toHaveCount(0);
  // Во входящей только открытые: отмеченных отвеченными строк здесь нет.
  await expect(page.locator('article[data-answered="true"]')).toHaveCount(0);

  // «Назад» из истории возвращает к входящей: вид — это переход, а не форма.
  await views.getByRole('link', { name: 'История вопросов' }).click();
  await expect(page.getByRole('heading', { name: 'Вопросы и ответы' })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Мои замечания без разбора' })).toBeVisible();
});

test('во входящей нет раздела прежних вопросов в делах (TRK-683)', async ({ page }) => {
  await page.goto('/questions');
  await expect(page.getByRole('heading', { name: 'Мои замечания без разбора' })).toBeVisible();

  // Счётчик прежних вопросов в панели остаётся, но в демо открытых вопросов в делах нет:
  // DEMO-4 ждёт ответа в обсуждении (TRK-684), и это видно отдельным знаком обсуждений.
  await expect(side(page).getByText('Открытых вопросов нет')).toBeVisible();
  await expect(side(page).getByText('1 обсуждение ждёт вас')).toBeAttached();

  await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: 'только блокирующие' })).toHaveCount(0);
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#' })).toHaveCount(0);
  // Ожидание DEMO-4 — вопрос обсуждения: оно стоит во входящей первым разделом.
  const inbox = page.getByRole('region', { name: 'Обсуждения, ждущие вас' });
  await expect(inbox.getByRole('article', { name: 'Обсуждение DEMO~2' })).toBeVisible();
});

test('проект отбирает все части входящей, и это сказано словами', async ({ page }) => {
  await page.goto('/questions');
  await expect(page.getByRole('main')).toBeVisible();

  // Область действия названа у самого поля; флажка «только блокирующие» больше нет.
  await expect(page.getByText('Проект отбирает все части входящей.')).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'только блокирующие' })).toHaveCount(0);

  // Отбор по проекту уходит в адрес и держится.
  await page.goto('/questions?project=DEMO');
  await expect(page.getByRole('combobox', { name: 'Проект' })).toHaveValue('DEMO');
  await expect(page.getByRole('heading', { name: 'Мои замечания без разбора' })).toBeVisible();
});

test.describe('раскладка входящей', () => {
  for (const width of [390, 900, 1440]) {
    test(`входящая в одну колонку не уезжает вбок на ширине ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/questions');
      await expect(page.getByRole('heading', { name: 'Мои замечания без разбора' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Требуют внимания' })).toBeVisible();
      await fontsReady(page);

      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBe(0);
    });
  }
});
