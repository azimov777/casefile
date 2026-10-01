import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, shownKeys, silenceJournal } from './contour';

/** Файлы шрифтов интерфейса: свои, со своего узла (TRK-499). Гасятся все, иначе останется половина. */
const FONT_FILES = '**/*.woff2';

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
      // Файл начертания не пришёл (его погасили) — `load` отвечает отказом, а не пустым
      // списком: начертание объявлено, но загрузить его нечем.
      try {
        const faces = await document.fonts.load(`12px "${family}"`, sample);
        return faces.map((face) => face.status);
      } catch {
        return ['error'];
      }
    },
    [font, text],
  );
}

test('с сетью: Fira Sans и Fira Code загружены, кириллица набирается моноширинной', async ({
  page,
  baseURL,
}) => {
  // Страница не обращается ни к одному чужому узлу: шрифты отдаёт сам интерфейс (TRK-499).
  const foreign: string[] = [];
  page.on('request', (request) => {
    const { protocol, host } = new URL(request.url());
    const web = protocol === 'http:' || protocol === 'https:';
    if (web && host !== new URL(String(baseURL)).host) foreign.push(request.url());
  });
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await fontsReady(page);

  expect(await facesFor(page, 'Fira Sans', 'Задачи')).toContain('loaded');
  // Моноширинным набираются идентификаторы контракта, и часть из них — свободные
  // строки: исполнителя и название проекта трекер не ограничивает латиницей. Без
  // кириллицы в Fira Code такое значение молча съезжало бы на запасную гарнитуру.
  expect(await facesFor(page, 'Fira Code', 'программа')).toContain('loaded');

  const body = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  expect(body).toContain('Fira Sans');
  expect(foreign).toEqual([]);
});

test('без файлов шрифтов: страница читаема запасной гарнитурой и не рассыпается', async ({
  page,
  request,
}) => {
  const shown = await shownKeys(request);
  await page.route(FONT_FILES, (route) => route.abort());
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');

  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(shown.length);
  await expect(page.getByRole('heading', { name: 'Задачи' })).toBeVisible();

  // Fira не пришла — значит буквы рисует системная запасная, названная в стеке.
  expect(await facesFor(page, 'Fira Sans', 'Задачи')).not.toContain('loaded');
  expect(await facesFor(page, 'Fira Code', 'программа')).not.toContain('loaded');
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
    await page.goto('/tasks?project=DEMO');
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
