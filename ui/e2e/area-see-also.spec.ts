import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { fontsReady } from './contour';

/*
 * Смежные области на странице области (TRK-738, TRK~24#12), чтение на демо-данных: единственная
 * связь демо — `DEMO/ui` читает также `DEMO/core`. У `DEMO/ui` она в группе «Читать также», у
 * `DEMO/core` — в «Ссылаются сюда»; в деле обеих лежит запись `link_added`. Сценарий читающий.
 */

const REASON = 'Экраны показывают механики ядра: их правила — там.';
const SNAPS = '/Users/azimov/PycharmProjects/agents/casefile-artifacts/TRK-738';

test('на демо: DEMO/ui → «Читать также» DEMO/core с причиной; ссылка ведёт на DEMO/core, где DEMO/ui в «Ссылаются сюда»', async ({
  page,
}) => {
  await page.goto('/projects/DEMO/areas/ui');
  const block = page.getByRole('region', { name: 'Смежные области' });
  const out = block.locator('[data-see-also-group="see_also"]');
  await expect(out.getByRole('heading', { name: 'Читать также' })).toBeVisible();
  await expect(out.getByText(REASON, { exact: true })).toBeVisible();
  await expect(block.locator('[data-see-also-group="see_also_from"]')).toHaveCount(0);
  await expect(block.getByRole('button')).toHaveCount(0);

  await out.getByRole('link', { name: 'DEMO/core' }).click();
  await expect(page).toHaveURL(/\/projects\/DEMO\/areas\/core$/);
  const incoming = page
    .getByRole('region', { name: 'Смежные области' })
    .locator('[data-see-also-group="see_also_from"]');
  await expect(incoming.getByRole('heading', { name: 'Ссылаются сюда' })).toBeVisible();
  await expect(incoming.getByRole('link', { name: 'DEMO/ui' })).toBeVisible();
  await expect(incoming.getByText(REASON, { exact: true })).toBeVisible();
});

test('на демо: в «Деле» DEMO/ui запись о связи читается фразой со ссылкой на DEMO/core', async ({
  page,
}) => {
  // В строке описи адрес назван (строка — кнопка раскрытия, ссылке внутри неё не место);
  // в раскрытой записи он ссылка на страницу области, а причина стоит телом.
  await page.goto('/projects/DEMO/areas/ui?tab=case');
  const row = page.getByRole('row', { name: /Читать также DEMO\/core/ });
  await row.getByRole('button').first().click();
  await expect(page.getByRole('link', { name: 'DEMO/core' })).toHaveAttribute(
    'href',
    '/projects/DEMO/areas/core',
  );
  await expect(page.getByText(REASON, { exact: true })).toBeVisible();

  await page.goto('/projects/DEMO/areas/core?tab=case');
  const back = page.getByRole('row', { name: /Ссылается сюда DEMO\/ui/ });
  await back.getByRole('button').first().click();
  await expect(page.getByRole('link', { name: 'DEMO/ui' })).toBeVisible();
});

for (const [width, height] of [
  [1280, 900],
  [390, 844],
] as const) {
  test(`DEMO/ui на ${width} px: без прокрутки вбок, без нарушений доступности`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height });
    await page.goto('/projects/DEMO/areas/ui');
    await expect(page.getByRole('region', { name: 'Смежные области' })).toBeVisible();
    await fontsReady(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
    ).toBeLessThanOrEqual(0);
    if (testInfo.project.name === 'светлая') {
      await page.screenshot({ path: `${SNAPS}/demo-ui-${width}.png`, fullPage: true });
    }
  });
}
