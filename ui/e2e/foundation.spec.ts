import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

/** Пять экранов из `CONCEPT.md`, 3: список, доска, карточка, дело, входящая. */
const SCREENS: [string, string][] = [
  ['список', '/tasks?queue=DEMO'],
  ['доска', '/tasks?queue=DEMO&view=board'],
  ['карточка', '/tasks/DEMO-3'],
  ['дело', '/tasks/DEMO-3/case'],
  ['входящая', '/questions'],
];

/**
 * Самый мелкий кегль на странице среди элементов с собственным текстом.
 *
 * Считается по собственному тексту, а не по потомкам: у обёртки кегль наследуется
 * от родителя, и меряя её, мы мерили бы один и тот же размер по всему дереву.
 */
async function smallestFontSize(page: Page): Promise<{ size: number; text: string }> {
  return page.evaluate(() => {
    let smallest = { size: Number.POSITIVE_INFINITY, text: '' };

    for (const node of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const own = Array.from<ChildNode>(node.childNodes)
        .filter((child) => child.nodeType === Node.TEXT_NODE)
        .map((child) => child.textContent ?? '')
        .join('')
        .trim();
      if (own === '') continue;

      const size = Number.parseFloat(getComputedStyle(node).fontSize);
      if (size < smallest.size) smallest = { size, text: own.slice(0, 40) };
    }

    return smallest;
  });
}

for (const [name, url] of SCREENS) {
  test(`нижняя граница кегля держится: ${name}`, async ({ page }) => {
    await silenceJournal(page);
    await page.goto(url);
    await expect(page.getByRole('main')).toBeVisible();
    await fontsReady(page);

    const smallest = await smallestFontSize(page);

    // Решение Д24: любая подпись не мельче 11 px. Ниже этого порога она перестаёт
    // читаться на ноутбучном экране и первой страдает у людей с дальнозоркостью.
    expect(smallest.size, `самый мелкий текст: «${smallest.text}»`).toBeGreaterThanOrEqual(11);
  });
}

test('в колонке «Активность» цифры табличные: разряды стоят друг под другом', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO&sort=-last_entry_at');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  // Замер на настоящей ячейке: копия того же узла с другими цифрами той же длины
  // наследует и шрифт, и кегль колонки — то есть меряется ровно то, что видит человек.
  const widths = await page.evaluate(() => {
    const original = document.querySelector<HTMLElement>('tbody time');
    if (original === null) return null;

    const copy = original.cloneNode(true) as HTMLElement;
    copy.textContent = (original.textContent ?? '').replace(/\d/g, (digit) =>
      digit === '1' ? '8' : '1',
    );
    original.parentElement?.append(copy);
    const measured = [original.getBoundingClientRect().width, copy.getBoundingClientRect().width];
    copy.remove();
    return measured;
  });

  expect(widths, 'в колонке «Активность» нет ни одной подписи времени').not.toBeNull();
  const [first, second] = widths as [number, number];
  expect(Math.abs(first - second)).toBeLessThanOrEqual(0.5);
});

test.describe('тёмная тема', () => {
  test.use({ colorScheme: 'dark' });

  test('фон и текст страницы — ночные значения токенов', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.locator('tbody tr').first()).toBeVisible();

    const measured = await page.evaluate(() => {
      const styles = getComputedStyle(document.body);
      const probe = document.createElement('span');
      document.body.append(probe);

      const asRgb = (value: string): string => {
        probe.style.color = value;
        return getComputedStyle(probe).color;
      };

      const result = {
        background: styles.backgroundColor,
        color: styles.color,
        // Ночные примитивы: подстановка обязана довести именно до них.
        expectedBackground: asRgb(styles.getPropertyValue('--d-950')),
        expectedColor: asRgb(styles.getPropertyValue('--d-50')),
      };
      probe.remove();
      return result;
    });

    expect(measured.background).toBe(measured.expectedBackground);
    expect(measured.color).toBe(measured.expectedColor);
  });
});
