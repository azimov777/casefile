import { expect, test } from '@playwright/test';
import { askLegacyOwner } from './contour';

/**
 * Прежний вопрос в деле задачи, каким его видят история вопросов, карточка и дело
 * (TRK-684). Демо таких вопросов не держит: DEMO-4 ждёт ответа вопросом в обсуждении
 * `DEMO~2` (`TRK#51`, п. 4 и 6), а отвеченный прежний вопрос лежит только у DEMO-2. Прежний
 * открытый вопрос в установке живёт, пока его не закрыли, и его отрисовку проверяют эти
 * сценарии на своём вопросе — отсюда они пишущие: проект «запись», одна тема, вопрос
 * закрывается после каждого.
 */
let asked: Awaited<ReturnType<typeof askLegacyOwner>>;

test.beforeEach(async ({ request }) => {
  asked = await askLegacyOwner(request, {
    key: 'DEMO-3',
    title: 'Вопрос для замера кромки и ссылки',
    body: 'Тело вопроса для замера кромки и ссылки.',
    blocking: true,
  });
});

test.afterEach(async () => {
  await asked.cleanup();
});

/**
 * Кромка блокирующего вопроса (решение Д17) проверяется замером, а не поиском класса.
 *
 * Класс в разметке стоял и тогда, когда кромки на экране не было: в модуле экрана
 * сокращение `border` соседнего правила перебивало левую сторону при равной
 * специфичности, и проигрыш был молчаливым — ни сборка, ни типы, ни разметка о нём
 * не говорили, а поймал его только замер на живом контуре (UI-53#5).
 *
 * Сценарий идёт в обеих темах — тема задана самим сценарием, а не проектом Playwright: цвет
 * сверяется не с числом, а со значением токена в текущей теме, поэтому ночной красный
 * проверяется тем же кодом.
 */
for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`тема: ${colorScheme}`, () => {
    test.use({ colorScheme });
    edgeTest();
  });
}

function edgeTest(): void {
  test('блокирующий вопрос отмечен красной кромкой, а не только плашкой', async ({ page }) => {
    // Открытый блокирующий вопрос виден в истории: во входящей вопросов из дел нет (TRK-683).
    await page.goto('/questions?view=history');

    const question = page.getByRole('article', { name: `Вопрос DEMO-3#${asked.no}` });
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
}

test('ссылка вопроса ведёт в саму запись, а не только в задачу', async ({ page }) => {
  await page.goto('/questions?view=history');

  const link = page.getByRole('link', { name: `DEMO-3#${asked.no}` });
  await expect(link).toHaveAttribute('href', `/tasks/DEMO-3?entry=${asked.no}`);

  // Переход раскрывает названную запись на карточке, а перезагрузка её там и оставляет:
  // подпись `KEY#N` обещает запись, и открыться обязана именно она.
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/tasks/DEMO-3\\?entry=${asked.no}$`));
  const row = page.getByRole('button', { name: /Вопрос для замера кромки и ссылки/ });
  await expect(row).toHaveAttribute('aria-expanded', 'true');
  // Раскрыто — значит видно и тело записи, а не только её строка описи. Ищем внутри
  // описи: тот же вопрос показан выше целиком, в блоке открытых вопросов карточки.
  await expect(
    page.getByLabel('Дело').getByText(/Тело вопроса для замера кромки и ссылки/),
  ).toBeVisible();

  await page.reload();
  await expect(
    page.getByRole('button', { name: /Вопрос для замера кромки и ссылки/ }),
  ).toHaveAttribute('aria-expanded', 'true');
});

test('ответ на вопрос стоит под вопросом: открытый без ответа назван словами', async ({ page }) => {
  await page.goto('/tasks/DEMO-3/case');

  // В деле открытый вопрос: ответа под ним ещё нет, и это сказано словами.
  const question = page.getByRole('article').filter({ hasText: 'question' }).first();
  await expect(question).toBeVisible();
  await expect(question.getByText('Ответа пока нет.')).toBeVisible();
});
