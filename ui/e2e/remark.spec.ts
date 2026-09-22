import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken } from './contour';

const token = readE2eToken();

/** Сколько замечаний подшито в деле задачи — правда бэкенда, а не экрана. */
async function remarksOf(request: APIRequestContext, key: string): Promise<number> {
  const response = await request.get(`/api/v1/tasks/${key}/entries?types=remark`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: unknown[] };
  return body.data.length;
}

/**
 * Пишущий сценарий: оставляет замечание в демо-установке, поэтому вынесен в проект
 * «запись» и идёт после читающих (`playwright.config.ts`). Читающим нужна карточка
 * ровно с тем, что положил демо-набор.
 */
test('замечание с карточки подшивается один раз и остаётся видно человеку', async ({
  page,
  request,
}) => {
  const before = await remarksOf(request, 'DEMO-3');

  const posts: string[] = [];
  page.on('request', (call) => {
    if (call.method() === 'POST' && call.url().includes('/entries')) {
      posts.push(call.headers()['idempotency-key'] ?? '');
    }
  });

  await page.goto('/tasks/DEMO-3');

  /*
   * До отправки блок занимает строку и не съедает первый экран. У DEMO-3 сводка,
   * вопросы и замечания пусты сразу все три и делят одну слитую рамку без
   * `aria-labelledby` (UI-132), поэтому честный текст ищется на странице целиком,
   * а не в `<section>` с заголовком «Замечания»: после отправки замечание сделает
   * блок непустым, и он выделится в свою секцию — искать его по прежней разметке
   * означало бы завязаться на устройство, которое меняется по ходу теста.
   */
  await expect(page.getByText('Неразобранных замечаний нет.')).toBeVisible();

  await page
    .getByRole('navigation', { name: /Навигация по задаче/ })
    .getByRole('button', { name: 'Оставить замечание' })
    .click();
  await page
    .getByLabel(/^Замечание$/)
    .fill('Из карточки не видно, чем задача отличается от соседней.');
  await page.getByRole('button', { name: 'Оставить замечание' }).click();

  // Подтверждение с номером записи: страница не схлопнулась и не увела человека.
  const receipt = page.getByRole('region', { name: 'Замечание к DEMO-3 подшито' });
  await expect(receipt).toBeVisible();
  const href = await receipt.getByRole('link', { name: /^DEMO-3#\d+$/ }).getAttribute('href');
  expect(href).toMatch(/^\/tasks\/DEMO-3\?entry=\d+$/);
  await expect(page).toHaveURL(/\/tasks\/DEMO-3$/);

  // Замечание тут же видно в списке неразобранных, а признак вырос.
  await expect(page.getByText(/Из карточки не видно/).first()).toBeVisible();
  await expect(page.getByText('1 замечание без разбора')).toBeVisible();

  // Запрос ушёл с ключом повтора, и замечание в деле ровно одно.
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(await remarksOf(request, 'DEMO-3')).toBe(before + 1);
});

test('черновик замечания переживает уход на другую страницу и возврат', async ({ page }) => {
  await page.goto('/tasks/DEMO-5');
  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  await page.getByLabel(/^Замечание$/).fill('Недописанное замечание');

  await page.getByRole('link', { name: 'Все задачи' }).click();
  await expect(page.getByRole('heading', { name: 'Задачи' })).toBeVisible();

  await page.goto('/tasks/DEMO-5');
  await page.getByRole('button', { name: 'Оставить замечание' }).click();
  await expect(page.getByLabel(/^Замечание$/)).toHaveValue('Недописанное замечание');
});
