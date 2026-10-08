import { expect, test } from '@playwright/test';
import { askLegacyOwner } from './contour';

/**
 * Отмена формы ответа (`UI-156`): та же кнопка «Отмена» и то же подтверждение
 * (`Dialog(alert)`, не браузерный `confirm`), что и у формы замечания (`UI-142`,
 * `Composer.onCancel`) — живёт в единственном месте показа формы ответа — на карточке
 * задачи (`QuestionAnswer`); из входящей форму ответа сняли вместе с разделом прежних
 * вопросов (TRK-683).
 *
 * Форме нужен открытый прежний вопрос в деле задачи, а демо таких не держит (TRK-684: ожидание
 * ответа — вопрос в обсуждении, DEMO-4 ждёт ответа в `DEMO~2`). Сценарий заводит свой вопрос
 * на DEMO-3 и закрывает его после — поэтому он пишущий и идёт в проекте «запись»
 * (`playwright.config.ts`), одной темой. Ответ в форме не отправляется.
 */
test.describe('карточка задачи: форма ответа на прежний вопрос', () => {
  let question: Awaited<ReturnType<typeof askLegacyOwner>>;

  test.beforeEach(async ({ request }) => {
    question = await askLegacyOwner(request, {
      key: 'DEMO-3',
      title: 'Вопрос для отмены формы ответа',
      body: 'Тело вопроса, на состав которого сценарий не опирается.',
      blocking: true,
    });
  });

  // Уборка обязана случиться и при падении: оставленный открытым вопрос ломает соседей.
  test.afterEach(async () => {
    await question.cleanup();
  });

  test('«Отмена» сворачивает форму, раскрытую адресом, без вопроса на пустом черновике', async ({
    page,
  }) => {
    // Адрес называет вопрос — так сюда приводит уведомление и ссылка из входящей,
    // и форма раскрыта сразу, без клика «Ответить».
    await page.goto(`/tasks/DEMO-3?entry=${question.no}`);

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
    await page.goto(`/tasks/DEMO-3?entry=${question.no}`);

    await page.getByLabel(/^Ответ$/).fill('Черновик на карточке задачи.');
    await page.getByRole('button', { name: 'Отмена' }).click();

    const dialog = page.getByRole('alertdialog', { name: 'Выбросить черновик?' });
    await dialog.getByRole('button', { name: 'Выбросить' }).click();

    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(page.getByLabel(/^Ответ$/)).toHaveCount(0);
    // Параметр `?entry=N` остаётся в адресе (задача не трогать его — не обязательна),
    // но принудительно раскрывать форму заново он больше не должен: человек, который
    // отменил, вправе увидеть кнопку «Ответить», а не форму, ожившую под руками.
    await expect(page).toHaveURL(new RegExp(`\\?entry=${question.no}$`));
    await expect(page.getByRole('button', { name: 'Ответить' })).toBeVisible();
  });
});
