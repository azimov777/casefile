import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext } from '@playwright/test';
import { outsideArchive, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Столько задач помещается на страницу списка (`entities/task`, `TASK_PAGE_SIZE`). */
const PAGE_SIZE = 50;

/**
 * Сколько задач в очереди сейчас — по правде бэкенда, а не по длине прочитанной
 * страницы: `meta.total` считает всю выдачу по отбору и от размера страницы не зависит
 * (TRK-41). До него это же число собиралось запросом с `limit=200` и врало бы ровно
 * тогда, когда очередь перерастёт двести задач.
 *
 * Считаются задачи вне архива: столько список и показывает, пока архив не попросили
 * (UI-97).
 */
async function countTasks(request: APIRequestContext): Promise<number> {
  const query = new URLSearchParams({
    queue: 'DEMO',
    fields: 'status',
    limit: '1',
    query: outsideArchive(),
  });
  const response = await request.get(`/api/v1/tasks?${query.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { meta: { total: number | null } };
  const total = body.meta.total;
  expect(total, 'список задач обязан считать общее число выдачи').not.toBeNull();
  return total as number;
}

/**
 * Листание рядом страниц: в демо семь задач, а страница вмещает пятьдесят, и ряд без
 * этого сценария не появляется вовсе (замечено в задаче 02).
 *
 * Задачи заводятся в очереди DEMO — токен интерфейса набора `task` своих очередей
 * создавать не умеет. Поэтому сценарий пишущий и идёт последним, после читающих,
 * которые считают задачи демо поимённо (`playwright.config.ts`, проект «запись»).
 */
test('страницы списка листаются рядом номеров, и адрес называет открытую', async ({
  page,
  request,
}) => {
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

  const total = await countTasks(request);
  const pages = Math.ceil(total / PAGE_SIZE);
  expect(pages).toBeGreaterThan(1);

  await page.goto('/tasks?queue=DEMO');

  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(PAGE_SIZE);
  const firstPageKeys = await page.getByRole('rowheader').allInnerTexts();

  // Сколько задач нашлось по отбору и на какой странице человек стоит — видно, не
  // нажимая ничего. Число у заголовка — вся выдача, а не строки этой страницы.
  await expect(page.getByRole('heading', { level: 1 })).toContainText(String(total));
  await expect(page.getByText(`Страница 1 из ${pages}`)).toBeVisible();

  // Второго способа листать рядом нет: кнопки «Ещё» под таблицей не осталось.
  await expect(page.getByRole('button', { name: 'Ещё' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'В начало списка' })).toHaveCount(0);
  await expect(page.getByText('Это последняя страница.')).toHaveCount(0);

  const pager = page.getByRole('navigation', { name: 'Страницы выдачи' });
  // На первой странице шаг назад — глухая ступень: вести ему некуда, и ссылкой он
  // не притворяется.
  await expect(pager.getByRole('link', { name: 'Предыдущая страница' })).toHaveCount(0);

  await pager.getByRole('link', { name: 'Страница 2', exact: true }).click();

  // Номер страницы виден в адресе, значит ссылку на неё можно переслать.
  await expect(page).toHaveURL(/page=2/);
  await expect(pager.getByRole('link', { name: 'Страница 2', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );

  /*
   * Строки читаются только после того, как они сменились. Ряд и адрес меняются в том же
   * кадре, что и клик, — они собраны из адреса, — а таблица до ответа держит прежние
   * строки (`keepPreviousData`): прочитанные сразу после клика, они оказались бы
   * строками первой страницы, и проверка «страницы не перекрываются» падала бы на
   * скорости сети, а не на выдаче.
   */
  await expect(page.getByRole('rowheader').first()).not.toHaveText(firstPageKeys[0] as string);

  const secondPageKeys = await page.getByRole('rowheader').allInnerTexts();
  expect(secondPageKeys.length).toBeGreaterThan(0);
  // Страницы не перекрываются: смещение продолжает выдачу, а не начинает её заново.
  expect(secondPageKeys.filter((key) => firstPageKeys.includes(key))).toEqual([]);

  // Пересланная ссылка открывает ту же страницу: своего состояния у экрана нет.
  await page.reload();
  await expect(page.getByText(`Страница 2 из ${pages}`)).toBeVisible();
  expect(await page.getByRole('rowheader').allInnerTexts()).toEqual(secondPageKeys);

  // Шаг назад возвращает на первую страницу, и номер уходит из адреса: умолчания
  // в нём не пишутся.
  await pager.getByRole('link', { name: 'Предыдущая страница' }).click();
  await expect(page).not.toHaveURL(/page=/);

  /*
   * Строки читаются только после того, как пришли строки именно этой, первой страницы.
   * `toHaveCount(PAGE_SIZE)` тут ничего не ждёт: если вторая страница тоже полна,
   * строк ровно PAGE_SIZE и до ответа сервера (`keepPreviousData` держит строки второй
   * страницы), и после — число не меняется, и подпорка ничего не ловит (UI-89). Ждём
   * не число и не факт смены, а конкретное значение — первую строку первой страницы:
   * оно не совпадёт со строками второй ни при каком их числе, в отличие от числа строк.
   */
  await expect(page.getByRole('rowheader').first()).toHaveText(firstPageKeys[0] as string);

  await expect(rows).toHaveCount(PAGE_SIZE);
  expect(await page.getByRole('rowheader').allInnerTexts()).toEqual(firstPageKeys);

  /*
   * `axe` со **страницами на экране**: в остальных сценариях список короче страницы,
   * и ряда там нет вовсе — проверка доступности списка в `tasks.spec.ts` его просто
   * не видит. Здесь же под таблицей стоит и открытая ступень с `aria-current`,
   * и глухая, которой некуда вести.
   */
  const found = await new AxeBuilder({ page }).analyze();
  expect(found.violations).toEqual([]);
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
  const responses = await Promise.all(notes);
  for (const response of responses) {
    expect(response.status()).toBe(201);
  }

  /*
   * Номер дальней записи считается из **всех** ответов, а не берётся у последнего
   * обещания в массиве. `Promise.all` возвращает ответы в порядке запросов, но номера
   * выдаёт сервер в порядке, в котором он их обработал, и эти два порядка не связаны:
   * под нагрузкой последний отправленный POST регулярно получает не самый большой `no`
   * (UI-82, `docs/notes/testing.md`). Наибольший номер лежит за первой страницей при
   * любом порядке ответов, потому что записей заведено больше, чем в неё помещается.
   */
  const numbers = await Promise.all(
    responses.map(
      async (response) => ((await response.json()) as { data: { no: number } }).data.no,
    ),
  );
  const targetNo = Math.max(...numbers);
  expect(targetNo).toBeGreaterThan(ENTRY_PAGE_SIZE);

  await page.goto(`/tasks/${key}/case?entry=${targetNo}`);

  // Лента дочитывается сама, пока названная запись не найдётся.
  const target = page.getByLabel(`${key}#${targetNo}`, { exact: true });
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
