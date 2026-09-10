import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal } from './contour';

/** Хост шрифтов и хост их файлов: гасятся вместе, иначе останется половина. */
const FONT_HOSTS = ['https://fonts.googleapis.com/**', 'https://fonts.gstatic.com/**'];

/**
 * Сколько настоящих начертаний подобрано под этот текст этой гарнитурой.
 *
 * Именно `fonts.load`, а не `fonts.check`: `check` отвечает `true` и для семейства,
 * у которого нет ни одного `@font-face`, — браузер считает незнакомое имя системным.
 * На заблокированном хосте шрифтов проверка через `check` была бы зелёной всегда.
 * `load` возвращает подобранные начертания, и пустой список честно означает
 * «гарнитура не пришла».
 */
async function facesFor(page: Page, font: string, text: string): Promise<string[]> {
  return page.evaluate(
    async ([family, sample]) => {
      const faces = await document.fonts.load(`12px "${family}"`, sample);
      return faces.map((face) => face.status);
    },
    [font, text],
  );
}

test('с сетью: Fira Sans и Fira Code загружены, кириллица набирается моноширинной', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  expect(await facesFor(page, 'Fira Sans', 'Задачи')).toContain('loaded');
  // Моноширинным набираются идентификаторы контракта, и часть из них — свободные
  // строки: исполнителя и название очереди трекер не ограничивает латиницей. Без
  // кириллицы в Fira Code такое значение молча съезжало бы на запасную гарнитуру.
  expect(await facesFor(page, 'Fira Code', 'программа')).toContain('loaded');

  const body = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  expect(body).toContain('Fira Sans');
});

test('без хоста шрифтов: страница читаема запасной гарнитурой и не рассыпается', async ({
  page,
}) => {
  for (const host of FONT_HOSTS) await page.route(host, (route) => route.abort());
  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(7);
  await expect(page.getByRole('heading', { name: 'Задачи' })).toBeVisible();

  // Fira не пришла — значит буквы рисует системная запасная, названная в стеке.
  expect(await facesFor(page, 'Fira Sans', 'Задачи')).toEqual([]);
  expect(await facesFor(page, 'Fira Code', 'программа')).toEqual([]);
  const body = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  expect(body).toContain('system-ui');

  // Вёрстка держится на своих размерах, а не на метрике шрифта: страница не уезжает вбок.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);

  const found = await new AxeBuilder({ page }).analyze();
  expect(found.violations).toEqual([]);
});

test.describe('тёмная тема', () => {
  test.use({ colorScheme: 'dark' });

  test('приходит подстановкой значения, а не классом на html', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?queue=DEMO');
    await expect(page.locator('tbody tr').first()).toBeVisible();

    // Тема системная: переключателя нет, и класса, которым его обычно включают, тоже.
    const classes = await page.evaluate(() => document.documentElement.className);
    expect(classes).not.toContain('dark');

    const [background, token] = await page.evaluate(() => {
      const styles = getComputedStyle(document.body);
      return [styles.backgroundColor, styles.getPropertyValue('--t-ground').trim()];
    });

    // Фон страницы — ровно ночное значение токена, а не дневное и не браузерное.
    expect(background).toBe(await toRgb(page, token));
  });
});

/** Приводит значение токена к тому виду, в котором его отдаёт `getComputedStyle`. */
async function toRgb(page: Page, value: string): Promise<string> {
  return page.evaluate((color) => {
    const probe = document.createElement('span');
    probe.style.color = color;
    document.body.append(probe);
    const computed = getComputedStyle(probe).color;
    probe.remove();
    return computed;
  }, value);
}
