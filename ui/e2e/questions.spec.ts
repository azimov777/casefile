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

  // Счётчик в боковой панели остаётся: открытый вопрос в деле виден на карточке задачи.
  await expect(
    side(page).getByText(/^\d+ открыт(ый вопрос|ых вопроса|ых вопросов)$/),
  ).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: 'только блокирующие' })).toHaveCount(0);
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#4' })).toHaveCount(0);
});

/**
 * Кромка блокирующего вопроса (решение Д17) проверяется замером, а не поиском класса.
 *
 * Класс в разметке стоял и тогда, когда кромки на экране не было: в модуле экрана
 * сокращение `border` соседнего правила перебивало левую сторону при равной
 * специфичности, и проигрыш был молчаливым — ни сборка, ни типы, ни разметка о нём
 * не говорили, а поймал его только замер на живом контуре (UI-53#5).
 *
 * Сценарий идёт обоими проектами, светлым и тёмным: цвет сверяется не с числом, а со
 * значением токена в текущей теме, поэтому ночной красный проверяется тем же кодом.
 */
test('блокирующий вопрос отмечен красной кромкой, а не только плашкой', async ({ page }) => {
  // Открытый блокирующий вопрос виден в истории: во входящей вопросов из дел нет (TRK-683).
  await page.goto('/questions?view=history');

  const question = page.getByRole('article', { name: 'Вопрос DEMO-4#4' });
  await expect(question).toBeVisible();

  const edge = await question.evaluate((node) => {
    const styles = getComputedStyle(node);

    // Токен доводится до `rgb(...)` тем же способом, что и в `foundation.spec.ts`:
    // сравнивать `borderLeftColor` с текстом `var(--color-danger)` бессмысленно.
    const probe = document.createElement('span');
    document.body.append(probe);
    const asRgb = (value: string): string => {
      probe.style.color = value;
      return getComputedStyle(probe).color;
    };

    const measured = {
      leftWidth: styles.borderLeftWidth,
      leftColor: styles.borderLeftColor,
      topWidth: styles.borderTopWidth,
      topColor: styles.borderTopColor,
      danger: asRgb(styles.getPropertyValue('--color-danger')),
      line: asRgb(styles.getPropertyValue('--color-line')),
    };
    probe.remove();
    return measured;
  });

  // Сначала о самих токенах: если тон опасности сравняется с линией, проверка ниже
  // пройдёт и на пропавшей кромке, ничего не заметив.
  expect(edge.danger).not.toBe(edge.line);

  expect(edge.leftWidth).toBe('3px');
  expect(edge.leftColor).toBe(edge.danger);

  // Меняется ровно одно место: остальные стороны — прежняя линия, красной рамки
  // вокруг карточки нет.
  expect(edge.topWidth).toBe('1px');
  expect(edge.topColor).toBe(edge.line);

  // Цвет не остаётся единственным носителем смысла: плашка рядом с кромкой обязана
  // быть на месте, иначе признак пропадает для того, кто цвета не различает.
  await expect(question.getByText('блокирующий')).toBeVisible();
});

test('ссылка вопроса ведёт в саму запись, а не только в задачу', async ({ page }) => {
  await page.goto('/questions?view=history');

  const link = page.getByRole('link', { name: 'DEMO-4#4' });
  await expect(link).toHaveAttribute('href', '/tasks/DEMO-4?entry=4');

  // Переход раскрывает названную запись на карточке, а перезагрузка её там и оставляет:
  // подпись `KEY#N` обещает запись, и открыться обязана именно она.
  await link.click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-4\?entry=4$/);
  const row = page.getByRole('button', { name: /Срок хранения дел отменённых задач/ });
  await expect(row).toHaveAttribute('aria-expanded', 'true');
  // Раскрыто — значит видно и тело записи, а не только её строка описи. Ищем внутри
  // описи: тот же вопрос показан выше целиком, в блоке открытых вопросов карточки.
  await expect(page.getByLabel('Дело').getByText(/Сколько храним\?/)).toBeVisible();

  await page.reload();
  await expect(
    page.getByRole('button', { name: /Срок хранения дел отменённых задач/ }),
  ).toHaveAttribute('aria-expanded', 'true');
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
