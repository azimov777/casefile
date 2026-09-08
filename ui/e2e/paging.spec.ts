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

/** Столько записей помещается на страницу ленты дела (`entities/entry`, `ENTRY_PAGE_SIZE`). */
const ENTRY_PAGE_SIZE = 25;

/**
 * Дело длиннее одной страницы: ссылка «см. #N» на запись с последней страницы обязана
 * привести к ней, а не оставить человека смотреть в ленту без неё.
 *
 * Записи заводятся своей задачей, а не в демонстрационной: демо читают поимённо
 * соседние сценарии, и три десятка заметок в чужом деле им бы помешали.
 */
test('запись с последней страницы дела дочитывается по ссылке', async ({ page, request }) => {
  test.setTimeout(180_000);
  await silenceJournal(page);

  const created = await request.post('/api/v1/tasks', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      queue: 'DEMO',
      title: 'Задача с делом длиннее одной страницы',
      description: 'Заведена сквозным тестом ради проверки ссылки на дальнюю запись.',
    },
  });
  expect(created.status()).toBe(201);
  const key = ((await created.json()) as { data: { key: string } }).data.key;

  // Заведение задачи уже подшило `created`, поэтому до переполнения страницы нужно
  // на одну запись меньше; берём с запасом в три.
  const notes = Array.from({ length: ENTRY_PAGE_SIZE + 3 }, (_, index) =>
    request.post(`/api/v1/tasks/${key}/entries`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        type: 'note',
        title: `Заметка номер ${index + 1}`,
        body: 'Заведена сквозным тестом, чтобы дело не поместилось на страницу.',
      },
    }),
  );
  const last = (await Promise.all(notes)).at(-1);
  expect(last?.status()).toBe(201);
  const lastNo = ((await last?.json()) as { data: { no: number } }).data.no;
  expect(lastNo).toBeGreaterThan(ENTRY_PAGE_SIZE);

  await page.goto(`/tasks/${key}/case?entry=${lastNo}`);

  // Лента дочитывается сама, пока названная запись не найдётся.
  const target = page.getByLabel(`${key}#${lastNo}`, { exact: true });
  await expect(target).toBeVisible({ timeout: 15_000 });
  await expect(target).toHaveAttribute('data-highlighted');
});

/**
 * Ответ показан не сам по себе, а внутри своего вопроса. Ссылка на него обязана вести
 * туда, где он виден, и пометить именно его — иначе человек, пришедший по ссылке
 * на ответ, видит подсвеченный вопрос и не понимает, тот ли это ответ.
 */
test('ссылка на ответ ведёт внутрь вопроса и помечает сам ответ', async ({ page, request }) => {
  await silenceJournal(page);

  const asked = await request.post('/api/v1/tasks/DEMO-3/entries', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      type: 'question',
      title: 'Вопрос ради проверки ссылки на ответ',
      body: 'Ответ на него показывается внутри этого вопроса.',
      payload: { addressees: ['owner'], blocking: false },
    },
  });
  expect(asked.status()).toBe(201);
  const questionNo = ((await asked.json()) as { data: { no: number } }).data.no;

  const answered = await request.post('/api/v1/tasks/DEMO-3/entries', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      type: 'answer',
      body: 'Ответ, на который ведёт ссылка.',
      payload: { question_no: questionNo },
    },
  });
  expect(answered.status()).toBe(201);
  const answerNo = ((await answered.json()) as { data: { no: number } }).data.no;

  await page.goto(`/tasks/DEMO-3/case?entry=${answerNo}`);

  const question = page.getByLabel(`DEMO-3#${questionNo}`, { exact: true });
  const answer = question.getByLabel(`DEMO-3#${answerNo}`, { exact: true });
  await expect(answer).toBeVisible();
  await expect(answer).toHaveAttribute('data-highlighted');
  await expect(question).not.toHaveAttribute('data-highlighted');
});
