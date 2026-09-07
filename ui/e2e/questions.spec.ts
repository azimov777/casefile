import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { fontsReady, readE2eToken, side } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

test('доступность входящей', async ({ page }) => {
  await page.goto('/questions');
  await expect(page.getByRole('heading', { name: 'Входящая' })).toBeVisible();

  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => violation.id);
  expect(serious).toEqual([]);
});

test('входящая показывает адресованный вопрос и отбирает блокирующие', async ({ page }) => {
  await page.goto('/questions');

  // Счётчик переехал из шапки в боковую панель (UI-38) и подписан там числом.
  await expect(side(page).getByText(/^Открытых вопросов: \d+$/)).toBeVisible();

  const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
  await expect(question).toBeVisible();
  await expect(question.getByText('блокирующий')).toBeVisible();
  await expect(question).toContainText('Сколько храним?');

  // Отбор живёт в адресе: ссылку на «только блокирующие» можно переслать, и она
  // открывает то же самое. Сам клик по флажку проверяет страничный тест — здесь важно,
  // что состояние читается из адреса, а не из памяти вкладки.
  await page.goto('/questions?blocking=true');
  await expect(page.getByRole('checkbox', { name: 'только блокирующие' })).toBeChecked();
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#4' })).toBeVisible();
});

/** Ширина широкого замера: та же, что в `test.use` ниже. */
const WIDE = 1440;

test.describe('раскладка входящей', () => {
  test.use({ viewport: { width: WIDE, height: 900 } });

  test('на широком экране оба списка видны рядом, а не под экраном', async ({ page }) => {
    await page.goto('/questions');
    await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toBeVisible();
    await fontsReady(page);

    const questions = page.getByRole('heading', { name: 'Вопросы ко мне' });
    const remarks = page.getByRole('heading', { name: 'Мои замечания без разбора' });

    // Списки стоят рядом (решение Д16): у заголовков совпадает верх, а левые края
    // разные — значит это две колонки, а не одна под другой.
    const [first, second] = await Promise.all([questions.boundingBox(), remarks.boundingBox()]);
    expect(Math.abs((first?.y ?? 0) - (second?.y ?? 0))).toBeLessThanOrEqual(2);
    expect(second?.x ?? 0).toBeGreaterThan((first?.x ?? 0) + 100);

    // Оба видны без прокрутки, и справа от содержания не пустует половина экрана.
    await expect(questions).toBeInViewport();
    await expect(remarks).toBeInViewport();

    const free = await page.evaluate(() => {
      const main = document.querySelector('main');
      if (main === null) return Number.POSITIVE_INFINITY;
      const box = main.getBoundingClientRect();
      return window.innerWidth - box.right;
    });
    expect(free).toBeLessThan(WIDE / 4);
  });
});

test.describe('входящая на узком экране', () => {
  test.use({ viewport: { width: 900, height: 900 } });

  test('складывается в одну колонку: вопросы выше замечаний', async ({ page }) => {
    await page.goto('/questions');
    await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toBeVisible();
    await fontsReady(page);

    const questions = await page.getByRole('heading', { name: 'Вопросы ко мне' }).boundingBox();
    const remarks = await page
      .getByRole('heading', { name: 'Мои замечания без разбора' })
      .boundingBox();

    // Порядок разметки и есть порядок чтения: вопросы первыми.
    expect(remarks?.y ?? 0).toBeGreaterThan(questions?.y ?? 0);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});
