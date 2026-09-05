import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Сколько ответов подшито в деле задачи — правда бэкенда, а не экрана. */
async function answersOf(request: APIRequestContext, key: string): Promise<number> {
  const response = await request.get(`/api/v1/tasks/${key}/entries?types=answer`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: unknown[] };
  return body.data.length;
}

/**
 * Единственный сквозной сценарий, который пишет в демо-установку: он отвечает на
 * вопрос, и после него вопрос закрыт навсегда. Поэтому он вынесен в свой файл и свой
 * проект Playwright, который зависит от читающих: тем нужен ещё открытый вопрос
 * (`playwright.config.ts`, проект «ответ»).
 */
test('ответ на вопрос из входящей закрывает его на всех экранах', async ({ page, request }) => {
  const before = await answersOf(request, 'DEMO-4');
  expect(before).toBe(0);

  const posts: string[] = [];
  page.on('request', (call) => {
    if (call.method() === 'POST' && call.url().includes('/entries')) {
      posts.push(call.headers()['idempotency-key'] ?? '');
    }
  });

  await page.goto('/questions');

  // Счётчик в шапке — то же число, что показывает `bootstrap`. Пишущие сценарии идут
  // по одному и убирают за собой, поэтому здесь открыт ровно вопрос демо.
  const header = page.getByRole('banner');
  await expect(header.getByText('Открытых вопросов: 1')).toBeVisible();

  const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
  await expect(question.getByText('блокирующий')).toBeVisible();

  await question.getByRole('button', { name: 'Ответить' }).click();
  await page
    .getByLabel(/^Ответ$/)
    .fill('Храним вечно: записи дела неизменяемы, срок хранения не вводим.');
  await page.getByRole('button', { name: 'Ответить' }).click();

  // Вопрос ушёл из входящей, счётчик перечитан у бэкенда.
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#4' })).toHaveCount(0);
  await expect(header.getByText('Открытых вопросов: 0')).toBeVisible();

  // Запрос ушёл с ключом повтора, и ответ в деле ровно один.
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(await answersOf(request, 'DEMO-4')).toBe(1);

  // В карточке блок открытых вопросов пуст, а в описи появилась запись `answer`.
  await page.goto('/tasks/DEMO-4');
  await expect(page.getByText('Вопросов без ответа нет.')).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'answer' })).toHaveCount(1);
});
