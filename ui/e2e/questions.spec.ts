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

  // Первый экран — прежняя входящая: открытые вопросы ко мне и мои замечания.
  const views = page.getByRole('navigation', { name: 'Вид входящей' });
  await expect(views.getByRole('link', { name: 'Ждут ответа' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Мои замечания без разбора' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Вопросы и ответы' })).toHaveCount(0);
  // Во входящей только открытые: отмеченных отвеченными строк здесь нет.
  await expect(page.locator('article[data-answered="true"]')).toHaveCount(0);

  // «Назад» из истории возвращает к входящей: вид — это переход, а не форма.
  await views.getByRole('link', { name: 'История вопросов' }).click();
  await expect(page.getByRole('heading', { name: 'Вопросы и ответы' })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Вопросы ко мне' })).toBeVisible();
});

test('входящая показывает адресованный вопрос и отбирает блокирующие', async ({ page }) => {
  await page.goto('/questions');

  // Счётчик переехал из шапки в боковую панель (UI-38) и подписан там числом.
  await expect(
    side(page).getByText(/^\d+ открыт(ый вопрос|ых вопроса|ых вопросов)$/),
  ).toBeVisible();

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
  await page.goto('/questions');

  const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
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
  await page.goto('/questions');

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

test('очередь отбирает обе половины, и это сказано словами', async ({ page }) => {
  await page.goto('/questions');
  await expect(page.getByRole('main')).toBeVisible();

  // Область действия названа у самого поля: очередь общая, «только блокирующие» —
  // условие вопросов и стоит внутри их половины.
  await expect(page.getByText('Очередь отбирает обе половины входящей.')).toBeVisible();
  const questions = page.getByRole('region').filter({ hasText: 'Вопросы ко мне' });
  await expect(page.getByRole('checkbox', { name: 'только блокирующие' })).toBeVisible();

  // Отбор по очереди уходит в адрес и держится в обеих половинах.
  await page.goto('/questions?queue=DEMO');
  await expect(page.getByRole('combobox', { name: 'Очередь' })).toHaveValue('DEMO');
  await expect(questions.getByRole('article').first()).toBeVisible();
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
