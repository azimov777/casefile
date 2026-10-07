import { expect, test } from '@playwright/test';

/**
 * Отмена формы ответа (`UI-156`): та же кнопка «Отмена» и то же подтверждение
 * (`Dialog(alert)`, не браузерный `confirm`), что и у формы замечания (`UI-142`,
 * `Composer.onCancel`) — живёт в единственном месте показа формы ответа — на карточке
 * задачи (`QuestionAnswer`); из входящей форму ответа сняли вместе с разделом прежних
 * вопросов (TRK-683).
 *
 * Сценарий ничего не отправляет в демо-установку — ответ нигде не подшивается —
 * и потому читает наравне с остальными: идёт в обеих темах, а не в проекте «запись»
 * (`playwright.config.ts`). Имя файла не совпадает целиком ни с одним словом из
 * `testIgnore`/`testMatch` («answer» ловит ровно `answer.spec.ts`, не префикс —
 * находка `docs/notes/testing.md`).
 */
test.describe('карточка задачи: DEMO-4?entry=4', () => {
  test('«Отмена» сворачивает форму, раскрытую адресом, без вопроса на пустом черновике', async ({
    page,
  }) => {
    // Адрес называет вопрос — так сюда приводит уведомление и ссылка из входящей,
    // и форма раскрыта сразу, без клика «Ответить».
    await page.goto('/tasks/DEMO-4?entry=4');

    const field = page.getByLabel(/^Ответ$/);
    await expect(field).toBeVisible();
    await expect(field).toHaveValue('');

    await page.getByRole('button', { name: 'Отмена' }).click();

    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(page.getByLabel(/^Ответ$/)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Ответить' })).toBeVisible();
  });

  test('«Отмена» на непустом черновике выбрасывает его, и адрес больше не раскрывает форму сам', async ({
    page,
  }) => {
    await page.goto('/tasks/DEMO-4?entry=4');

    await page.getByLabel(/^Ответ$/).fill('Черновик на карточке задачи.');
    await page.getByRole('button', { name: 'Отмена' }).click();

    const dialog = page.getByRole('alertdialog', { name: 'Выбросить черновик?' });
    await dialog.getByRole('button', { name: 'Выбросить' }).click();

    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(page.getByLabel(/^Ответ$/)).toHaveCount(0);
    // Параметр `?entry=4` остаётся в адресе (задача не трогать его — не обязательна),
    // но принудительно раскрывать форму заново он больше не должен: человек, который
    // отменил, вправе увидеть кнопку «Ответить», а не форму, ожившую под руками.
    await expect(page).toHaveURL(/\?entry=4$/);
    await expect(page.getByRole('button', { name: 'Ответить' })).toBeVisible();
  });
});
