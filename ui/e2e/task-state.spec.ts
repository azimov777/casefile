import { expect, test } from '@playwright/test';
import { silenceJournal } from './contour';

/*
 * Блок «Сейчас» (TRK-579): считается бэкендом при чтении и стоит над двумя колонками
 * карточки. DEMO-6 в демо-наборе в работе, со сводкой и с блокером.
 */

test('карточка DEMO-6 показывает блок «Сейчас» и не прокручивается вбок на телефоне', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/tasks/DEMO-6');

  const now = page.getByRole('region', { name: 'Сейчас' });
  await expect(now).toBeVisible();
  await expect(now.getByText('Последний переход')).toBeVisible();
  await expect(now.getByRole('link', { name: 'DEMO-2' })).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
