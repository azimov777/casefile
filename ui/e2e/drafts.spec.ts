import { expect, test } from '@playwright/test';
import { silenceJournal } from './contour';

/**
 * Неподнятое знание (TRK-661, решение TRK#57, раздел 8). Демо после TRK-659: у закрытой
 * DEMO-1 черновик решения для `DEMO/core` поднят решением области, у закрытой DEMO-8
 * черновик находки для `DEMO/ui` не поднят.
 *
 * Сценарий только читает. Закрытые задачи в списке стоят и без сдвига часов: правило
 * архива не прячет задачу с неподнятым знанием.
 */
test.use({ viewport: { width: 1440, height: 900 } });

test('отбор «есть неподнятое знание» находит DEMO-8 и не находит DEMO-1', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  const menu = page.getByRole('dialog', { name: 'Условия отбора задач' });
  await menu.getByRole('button', { name: 'есть неподнятое знание', exact: true }).click();
  await expect(page).toHaveURL(/drafts=true/);
  await page.keyboard.press('Escape');

  const conditions = page.getByRole('list', { name: 'Условия отбора' });
  await expect(conditions).toContainText('есть неподнятое знание');

  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('DEMO-8');
  await expect(page.locator('tbody')).not.toContainText('DEMO-1 ');
  // Признак с числом стоит и на самой строке списка.
  await expect(rows.first().locator('[data-mark="feature"]')).toHaveAttribute(
    'title',
    /1 черновик знания не поднят/,
  );

  // Отбор живёт в адресе: перезагрузка отдаёт то же.
  await page.reload();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody tr').first()).toContainText('DEMO-8');
});

test('на странице DEMO-8 черновик назван «не поднят», признак стоит в шапке', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-8');
  const open = page.getByText('Черновик в DEMO/ui — не поднят');
  await expect(open).toBeVisible();
  await expect(open.locator('xpath=ancestor::*[@data-draft][1]')).toHaveAttribute(
    'data-draft',
    'open',
  );

  const header = page.getByRole('heading', { name: /DEMO-8/ }).locator('xpath=ancestor::header[1]');
  await expect(header.getByRole('button', { name: /1 черновик знания не поднят/ })).toBeVisible();
});

test('на странице DEMO-1 черновик «Поднят» со ссылкой на запись области, признака нет', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1');
  const lifted = page.getByText('Поднят:', { exact: true });
  await expect(lifted).toBeVisible();
  const mark = lifted.locator('xpath=ancestor::*[@data-draft][1]');
  await expect(mark).toHaveAttribute('data-draft', 'lifted');

  const header = page.getByRole('heading', { name: /DEMO-1/ }).locator('xpath=ancestor::header[1]');
  await expect(header.getByRole('button', { name: /черновик/ })).toHaveCount(0);

  const link = mark.getByRole('link', { name: /^DEMO\/core#\d+$/ });
  await expect(link).toBeVisible();
  const reference = (await link.textContent()) as string;
  const no = reference.split('#')[1] as string;
  await link.click();

  // Ссылка ведёт на запись адресата: страницу области DEMO/core с раскрытой записью.
  await expect(page).toHaveURL(new RegExp(`/projects/DEMO/areas/core\\?entry=${no}$`));
  await expect(page.getByText('Номера задач не переиспользуются').first()).toBeVisible();
});
