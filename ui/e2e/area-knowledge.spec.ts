import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady } from './contour';

/*
 * Знание области в интерфейсе (TRK-660, решение TRK#59), чтение на демо-данных: у
 * `DEMO/core` решение и две заметки, где вторая заменяет первую. Сценарий читающий —
 * ничего не пишет и идёт в светлой и тёмной темах. Записи человека и ссылки из задач —
 * в `area-knowledge-write.spec.ts`.
 */

const ADDRESS = 'DEMO/core';
const OLD_NOTE = 'Отклонённый запрос сжигает номер задачи';
const NEW_NOTE = 'Отклонённый запрос номер задачи больше не сжигает';

/** Вкладка страницы области по началу подписи. */
function tab(page: Page, name: RegExp) {
  return page.getByRole('navigation', { name: 'Разделы области' }).getByRole('link', { name });
}

test('на демо: проект → «Области» → область → заметки; заменённой нет, по переключателю есть с пометкой и ссылкой', async ({
  page,
}) => {
  await page.goto('/projects/DEMO');
  await page
    .getByRole('navigation')
    .getByRole('link', { name: /^Области/ })
    .click();
  await page.locator(`li[data-area-row="${ADDRESS}"]`).getByRole('link').first().click();
  await expect(page).toHaveURL(/\/projects\/DEMO\/areas\/core$/);

  // Без параметра открыты «Решения»; число вкладки — действующих.
  await expect(tab(page, /^Решения/)).toHaveAttribute('aria-current', 'true');
  await expect(
    page.getByText('Номер задачи выдаётся после проверки полей', { exact: true }),
  ).toBeVisible();

  await tab(page, /^Заметки/).click();
  await expect(page).toHaveURL(/tab=notes/);
  const notes = page.getByRole('list', { name: 'Заметки области' });
  await expect(notes.getByText(NEW_NOTE, { exact: true })).toBeVisible();
  await expect(page.getByText(OLD_NOTE, { exact: true })).toHaveCount(0);
  // Число на вкладке — одна действующая: заменённая в счёт не идёт.
  await expect(tab(page, /^Заметки/)).toHaveAccessibleName('Заметки 1');

  await page.getByRole('checkbox', { name: /Показать заменённые/ }).check();
  const old = page.locator('li[data-knowledge]', { hasText: OLD_NOTE });
  await expect(old).toHaveAttribute('data-status', 'superseded');
  await expect(old.getByText('заменено', { exact: true })).toBeVisible();
  const successor = old.getByRole('link', { name: new RegExp(`^${ADDRESS}#\\d+$`) });
  const href = await successor.getAttribute('href');
  expect(href).toMatch(/\/projects\/DEMO\/areas\/core\?entry=\d+$/);

  // Ссылка на преемника открывает его в «Деле» раскрытым.
  await successor.click();
  await expect(page.getByRole('button', { name: NEW_NOTE })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
});

test('на демо: поиск по слову из тела заметки находит её и снимается сбросом', async ({ page }) => {
  await page.goto('/projects/DEMO/areas/core?tab=notes');
  const notes = page.getByRole('list', { name: 'Заметки области' });
  await expect(notes.getByText(NEW_NOTE, { exact: true })).toBeVisible();

  // Слова нет в названии, оно — в теле второй заметки.
  const search = page.getByRole('searchbox', { name: 'Поиск по решениям и заметкам' });
  await search.fill('описывала');
  await expect(page).toHaveURL(/q=/);
  await expect(notes.getByText(NEW_NOTE, { exact: true })).toBeVisible();

  await search.fill('слова которого нет нигде');
  await expect(page.getByText('Среди заметок ничего не найдено.')).toBeVisible();

  await page.getByRole('button', { name: 'Сбросить поиск' }).click();
  await expect(page).not.toHaveURL(/q=/);
  await expect(notes.getByText(NEW_NOTE, { exact: true })).toBeVisible();
});

test('в «Деле» проекта и области заменённая заметка помечена ссылкой на преемника', async ({
  page,
}) => {
  await page.goto('/projects/DEMO/areas/core?tab=case');
  const row = page.getByRole('row', { name: new RegExp(OLD_NOTE) });
  await expect(row.getByText('заменено', { exact: true })).toBeVisible();
  await expect(row.getByRole('link', { name: new RegExp(`^${ADDRESS}#\\d+$`) })).toBeVisible();
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`вкладки знания на 390 px (${colorScheme}): без прокрутки вбок, без нарушений доступности, без ошибок консоли`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('pageerror', (error) => errors.push(error.message));
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });

    for (const path of [
      '/projects/DEMO/areas/core',
      '/projects/DEMO/areas/core?tab=notes',
      '/projects/DEMO/areas/webhooks',
    ]) {
      await page.goto(path);
      await expect(
        page.getByRole('searchbox', { name: 'Поиск по решениям и заметкам' }),
      ).toBeVisible();
      const toggle = page.getByRole('checkbox', { name: /Показать заменённые/ });
      if (await toggle.count()) await toggle.check();
      await fontsReady(page);
      expect((await new AxeBuilder({ page }).analyze()).violations, path).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
        path,
      ).toBeLessThanOrEqual(0);
    }
    expect(errors).toEqual([]);
  });
}
