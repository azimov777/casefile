import { expect, test } from '@playwright/test';

/**
 * Отмена формы замечания (`UI-142`): раскрытая форма сворачивается по кнопке
 * «Отмена», а черновик она выбрасывает — сразу для пустого поля, после
 * подтверждения окном (не браузерным `confirm`) для непустого.
 *
 * Сценарий ничего не отправляет в демо-установку — замечание нигде не подшивается —
 * и потому читает наравне с остальными: идёт в обеих темах, а не в проекте «запись»
 * (`playwright.config.ts`).
 */
test('«Отмена» на пустой форме сворачивает её без вопроса', async ({ page }) => {
  await page.goto('/tasks/DEMO-5');

  const nav = page.getByRole('navigation', { name: /Навигация по задаче/ });
  await nav.getByRole('button', { name: 'Оставить замечание' }).click();
  await expect(page.getByLabel(/^Замечание$/)).toHaveValue('');

  await page.getByRole('button', { name: 'Отмена' }).click();

  // Никакого диалога — форма ушла сразу, и открывающая кнопка снова на месте.
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByLabel(/^Замечание$/)).toHaveCount(0);
  await expect(nav.getByRole('button', { name: 'Оставить замечание' })).toBeVisible();
});

test('«Отмена» на непустом черновике спрашивает и выбрасывает его по подтверждению', async ({
  page,
}) => {
  await page.goto('/tasks/DEMO-5');

  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  await page.getByLabel(/^Замечание$/).fill('Пробный черновик — проверяю отмену.');

  const cancelButton = page.getByRole('button', { name: 'Отмена' });
  await cancelButton.click();

  let dialog = page.getByRole('alertdialog', { name: 'Выбросить черновик?' });
  await expect(dialog).toBeVisible();
  // Диалог только спрашивает: форма и набранный текст ещё на экране.
  await expect(page.getByLabel(/^Замечание$/)).toHaveValue('Пробный черновик — проверяю отмену.');

  // `Esc` тоже значит «не выбрасывать» и возвращает фокус на «Отмена»: она стоит
  // `Dialog.Trigger`, и без этого Radix отправлял бы фокус на `body`
  // (`UI-175#11`, `UI-178`).
  await page.keyboard.press('Escape');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(cancelButton).toBeFocused();
  await expect(page.getByLabel(/^Замечание$/)).toHaveValue('Пробный черновик — проверяю отмену.');

  await cancelButton.click();
  dialog = page.getByRole('alertdialog', { name: 'Выбросить черновик?' });
  await dialog.getByRole('button', { name: 'Выбросить' }).click();

  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByLabel(/^Замечание$/)).toHaveCount(0);

  // Черновик пропал не только из вида, а из хранилища: перечитывание страницы и
  // повторное открытие формы это подтверждают.
  await page.reload();
  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  await expect(page.getByLabel(/^Замечание$/)).toHaveValue('');
});

test('«Продолжить писать» закрывает диалог и не трогает черновик', async ({ page }) => {
  await page.goto('/tasks/DEMO-5');

  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  await page.getByLabel(/^Замечание$/).fill('Ещё не закончил.');
  const cancelButton = page.getByRole('button', { name: 'Отмена' });
  await cancelButton.click();

  const dialog = page.getByRole('alertdialog');
  await dialog.getByRole('button', { name: 'Продолжить писать' }).click();

  // Фокус возвращается на «Отмена»: как и после `Esc`, окно закрылось, не выбросив
  // черновик, и человек продолжает с той же кнопки (`UI-178`).
  await expect(cancelButton).toBeFocused();

  // Ни `Esc`, ни крестик диалога не отличаются от этой кнопки: тоже не выбрасывают.
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByLabel(/^Замечание$/)).toHaveValue('Ещё не закончил.');
});
