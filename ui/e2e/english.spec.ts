import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

/*
 * Дымовой прогон главных экранов на английском (UI-80).
 *
 * Язык здесь берётся из `locale` проекта (`playwright.config.ts`, «английская») при
 * чистом хранилище — то есть тем же путём, каким его получает человек с английским
 * браузером. Ничего не подменяется и не переключается: сценарий, который сам нажимает
 * на переключатель, проверял бы переключатель, а не то, что установка открывается
 * английской.
 *
 * Проверяется на каждом экране одна и та же пара, и обе половины обязательны:
 *
 * 1. подписи интерфейса английские — по фразам, вписанным сюда руками, а не взятым
 *    из словаря (иначе проверялась бы связь ключа с элементом, а не текст);
 * 2. данные остались русскими — по строке, спрошенной у бэкенда и сверенной знак
 *    в знак. Названия задач, тексты записей и названия очередей пишут агенты, и эта
 *    программа их не переводит (UI-76). Проверка именно явная: «тест не упал»
 *    доказывает только то, что никто не смотрел.
 *
 * Экранов четыре — список, карточка, дело, входящая. Остальные двадцать с лишним
 * сценариев остаются русскими: они проверяют не язык, а поведение, геометрию и тему,
 * и второй их прогон стоил бы времени ровно столько же, сколько первый.
 */

const token = readE2eToken();

/** Задача демо, какой её знает бэкенд: названия задач никто не переводит. */
async function demoTask(
  request: APIRequestContext,
  key: string,
): Promise<{ title: string; queueTitle: string }> {
  const response = await request.get(`/api/v1/tasks/${key}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as {
    data: { task: { title: string; queue: { title: string } } };
  };
  return { title: body.data.task.title, queueTitle: body.data.task.queue.title };
}

type Summary = { no: number; payload: { done: string; next_step: string } };

/** Сводки задачи по номерам: их текст — данные, а подписи их частей — интерфейс. */
async function summaries(request: APIRequestContext, key: string): Promise<Summary[]> {
  const response = await request.get(`/api/v1/tasks/${key}/entries?types=summary&limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as { data: Summary[] };
  expect(body.data.length, 'у демо-задачи обязана быть сводка').toBeGreaterThan(0);
  return body.data;
}

/** Последняя сводка: её показывает карточка задачи блоком «Latest summary». */
function latest(list: Summary[]): Summary {
  return list[list.length - 1];
}

/** Кириллица есть: без этой проверки сравнение с данными демо ничего бы не значило. */
function expectRussian(value: string): void {
  expect(value).toMatch(/[А-Яа-яЁё]/);
}

test('список задач: оболочка и таблица английские, названия задач и очередей русские', async ({
  page,
  request,
}) => {
  const { title, queueTitle } = await demoTask(request, 'DEMO-1');
  expectRussian(title);
  expectRussian(queueTitle);

  await silenceJournal(page);
  await page.goto('/tasks?queue=DEMO');

  await expect(page.getByRole('heading', { name: 'Tasks' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');

  const shell = page.getByRole('complementary', { name: 'Tracker sections' });
  await expect(shell).toContainText('Queues');
  await expect(shell).toContainText('All tasks');
  await expect(shell).toContainText('Inbox');

  /*
   * Заголовки столбцов сравниваются по `textContent`, а не по видимому тексту: они
   * набраны прописными средствами оформления (`uppercase`), и `innerText` вернул бы
   * `KEY` вместо `Key` — проверка ловила бы регистр из таблицы стилей, а не подпись
   * из словаря.
   */
  expect(await page.locator('thead th').allTextContents()).toEqual([
    'Key',
    'Title',
    'Status',
    'Assignee',
    'Priority',
    'Features',
    'Activity',
  ]);

  // Данные: название задачи в строке и название очереди в панели — те самые.
  const row = page
    .getByRole('row')
    .filter({ has: page.getByRole('rowheader', { name: 'DEMO-1' }) });
  await expect(row).toContainText(title);
  await expect(shell).toContainText(queueTitle);
});

test('карточка задачи: блоки задания английские, название и текст сводки русские', async ({
  page,
  request,
}) => {
  const { title } = await demoTask(request, 'DEMO-1');
  const summary = latest(await summaries(request, 'DEMO-1')).payload;
  expectRussian(summary.next_step);

  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1');

  for (const block of ['Latest summary', 'Case', 'Assignment', 'Links']) {
    await expect(page.getByRole('heading', { name: block, exact: true })).toBeVisible();
  }

  // Название задачи стоит рядом с ключом и приходит из базы как есть.
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(`DEMO-1 ${title}`);

  /*
   * Сводка — то место, где интерфейс и данные стоят вплотную: «Next step» пишет
   * словарь, а строку под ним — агент. Здесь видно сразу обе половины правила.
   */
  const block = page.getByRole('region', { name: 'Latest summary' });
  await expect(block).toContainText('Next step');
  await expect(block).toContainText(summary.next_step);
});

test('дело: подписи ленты английские, содержание записей русское', async ({ page, request }) => {
  const filed = await summaries(request, 'DEMO-1');

  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1/case');

  await expect(page.getByRole('heading', { name: 'Case DEMO-1' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose the types' })).toBeVisible();

  const entry = page.locator('article[data-type="summary"]').first();
  await expect(entry).toBeVisible();

  /*
   * Сверяется та самая запись, которую показал экран, а не та, которую тест счёл
   * первой: номер записи берётся из её же указателя (`DEMO-1#12`). Иначе проверка
   * зависела бы от того, с какого конца лента считает и сколько записей влезло
   * на первую страницу, — и падала бы от правки, которая языка не касается.
   */
  const reference = (await entry.getAttribute('aria-label')) ?? '';
  const shown = filed.find((summary) => summary.no === Number(reference.split('#')[1]));
  expect(shown, `сводка ${reference} обязана найтись в деле`).toBeDefined();
  const done = shown?.payload.done ?? '';
  expectRussian(done);

  // Части сводки называет словарь — по-английски...
  await expect(entry).toContainText('Done');
  await expect(entry).toContainText('Next step');
  // ...а написанное агентом осталось на своём языке.
  await expect(entry).toContainText(done);
});

test('входящая: разделы английские, вопросы русские', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/questions');

  await expect(page.getByRole('heading', { name: 'Inbox', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Questions for me' })).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'My remarks without a resolution' }),
  ).toBeVisible();

  // Отбор входящей — тоже подпись интерфейса, и он тоже английский: поле очереди
  // подписано, а его первое значение названо словами, а не пустой строкой.
  const filter = page.getByRole('form', { name: 'Inbox selection' });
  await expect(filter.getByRole('combobox', { name: 'Queue' })).toBeVisible();
  await expect(filter).toContainText('The queue selects both halves of the inbox.');

  /*
   * Текст вопроса пишет агент. Явное ожидание, а не «кириллица где-нибудь на
   * странице»: вопрос — это заголовок второго уровня внутри своей карточки.
   */
  const question = page.getByRole('heading', { level: 2 }).filter({ hasText: /[А-Яа-яЁё]/ });
  await expect(question.first()).toBeVisible();
});
