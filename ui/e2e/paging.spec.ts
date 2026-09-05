import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Столько задач помещается на страницу списка (`entities/task`, `TASK_PAGE_SIZE`). */
const PAGE_SIZE = 50;

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Сколько задач в очереди сейчас. */
async function countTasks(request: APIRequestContext): Promise<number> {
  const response = await request.get('/api/v1/tasks?queue=DEMO&fields=status&limit=200', {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: unknown[] };
  return body.data.length;
}

/**
 * Листание по курсору: в демо семь задач, а страница вмещает пятьдесят, и кнопка «ещё»
 * без этого сценария не появляется вовсе (замечено в задаче 02).
 *
 * Задачи заводятся в очереди DEMO — токен интерфейса набора `task` своих очередей
 * создавать не умеет. Поэтому сценарий пишущий и идёт последним, после читающих,
 * которые считают задачи демо поимённо (`playwright.config.ts`, проект «запись»).
 */
test('вторая страница списка читается по курсору из адреса', async ({ page, request }) => {
  test.setTimeout(180_000);
  await silenceJournal(page);

  const before = await countTasks(request);
  const needed = PAGE_SIZE + 3 - before;

  // Заводим ровно столько, чтобы страница переполнилась: лишние стоят времени прогона.
  const created = Array.from({ length: Math.max(needed, 0) }, (_, index) =>
    request.post('/api/v1/tasks', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        queue: 'DEMO',
        title: `Задача для проверки листания № ${index + 1}`,
        description: 'Заведена сквозным тестом, чтобы список не поместился на страницу.',
      },
    }),
  );
  for (const response of await Promise.all(created)) {
    expect(response.status()).toBe(201);
  }

  await page.goto('/tasks?queue=DEMO');

  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(PAGE_SIZE);
  const firstPageKeys = await page.getByRole('rowheader').allInnerTexts();

  // «Ещё» уводит на следующую страницу — и курсор виден в адресе, значит ссылку
  // на эту страницу можно переслать.
  await page.getByRole('button', { name: 'Ещё' }).click();
  await expect(page).toHaveURL(/cursor=/);
  await expect(page.getByText('Это последняя страница.')).toBeVisible();

  const secondPageKeys = await page.getByRole('rowheader').allInnerTexts();
  expect(secondPageKeys.length).toBeGreaterThan(0);
  // Страницы не перекрываются: курсор продолжает выдачу, а не начинает её заново.
  expect(secondPageKeys.filter((key) => firstPageKeys.includes(key))).toEqual([]);

  // Возврат в начало списка убирает курсор из адреса.
  await page.getByRole('button', { name: 'В начало списка' }).click();
  await expect(page).not.toHaveURL(/cursor=/);
  await expect(rows).toHaveCount(PAGE_SIZE);
});
