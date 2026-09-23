import { expect, test } from '@playwright/test';

/**
 * Отмена формы ответа (`UI-156`): та же кнопка «Отмена» и то же подтверждение
 * (`Dialog(alert)`, не браузерный `confirm`), что и у формы замечания (`UI-142`,
 * `Composer.onCancel`) — сведена сюда, в оба места показа формы ответа: входящую
 * (`QuestionRow`) и карточку задачи (`QuestionAnswer`).
 *
 * Сценарий ничего не отправляет в демо-установку — ответ нигде не подшивается —
 * и потому читает наравне с остальными: идёт в обеих темах, а не в проекте «запись»
 * (`playwright.config.ts`). Имя файла не совпадает целиком ни с одним словом из
 * `testIgnore`/`testMatch` («answer» ловит ровно `answer.spec.ts`, не префикс —
 * находка `docs/notes/testing.md`).
 */
test.describe('входящая: DEMO-4#4', () => {
  test('«Отмена» на пустой форме сворачивает её без вопроса', async ({ page }) => {
    await page.goto('/questions');

    const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
    await question.getByRole('button', { name: 'Ответить' }).click();
    await expect(question.getByLabel(/^Ответ$/)).toHaveValue('');

    await question.getByRole('button', { name: 'Отмена' }).click();

    // Никакого диалога — форма ушла сразу, и открывающая кнопка снова на месте.
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(question.getByLabel(/^Ответ$/)).toHaveCount(0);
    await expect(question.getByRole('button', { name: 'Ответить' })).toBeVisible();
  });

  test('«Отмена» на непустом черновике спрашивает и выбрасывает его по подтверждению', async ({
    page,
  }) => {
    await page.goto('/questions');

    const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
    await question.getByRole('button', { name: 'Ответить' }).click();
    await question.getByLabel(/^Ответ$/).fill('Пробный черновик — проверяю отмену.');

    await question.getByRole('button', { name: 'Отмена' }).click();

    const dialog = page.getByRole('alertdialog', { name: 'Выбросить черновик?' });
    await expect(dialog).toBeVisible();
    // Диалог только спрашивает: форма и набранный текст ещё на экране. Поиск не через
    // `question` (`getByRole('article')`): пока диалог открыт, Radix прячет фон от
    // дерева доступности (`aria-hidden`), и ролевой локатор снаружи диалога перестаёт
    // находить что угодно — `getByLabel` от `page` это не задевает.
    await expect(page.getByLabel(/^Ответ$/)).toHaveValue('Пробный черновик — проверяю отмену.');

    await dialog.getByRole('button', { name: 'Выбросить' }).click();

    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(question.getByLabel(/^Ответ$/)).toHaveCount(0);

    // Черновик пропал не только из вида, а из хранилища: перечитывание страницы и
    // повторное открытие формы это подтверждают.
    await page.reload();
    const reopened = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
    await reopened.getByRole('button', { name: 'Ответить' }).click();
    await expect(reopened.getByLabel(/^Ответ$/)).toHaveValue('');
  });

  test('«Продолжить писать» закрывает диалог и не трогает черновик', async ({ page }) => {
    await page.goto('/questions');

    const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
    await question.getByRole('button', { name: 'Ответить' }).click();
    await question.getByLabel(/^Ответ$/).fill('Ещё не закончил.');
    await question.getByRole('button', { name: 'Отмена' }).click();

    const dialog = page.getByRole('alertdialog');
    await dialog.getByRole('button', { name: 'Продолжить писать' }).click();

    // Ни `Esc`, ни крестик диалога не отличаются от этой кнопки: тоже не выбрасывают.
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(question.getByLabel(/^Ответ$/)).toHaveValue('Ещё не закончил.');
  });
});

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
