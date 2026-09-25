import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

/*
 * Перенос задачи между проектами в интерфейсе (TRK-173, `CONCEPT.md`, «Карточка
 * задачи»): адрес по прежнему ключу открывает задачу и заменяется на текущий, номер
 * записи остаётся; прежний ключ виден в карточке; ссылка `ПРЕЖНИЙ-N`, написанная в
 * тексте другой записи, ведёт на ту же задачу. Запись `moved` в ленте дела и её текст —
 * дело TRK-172, здесь только смотрим, что она видна.
 *
 * Сценарий пишущий (переносит задачу через настоящий REST, а не подмену) и идёт в
 * проекте «запись» по той же причине, что `project-archive.spec.ts`: свои проекты и
 * задачи с меткой прогона, чтобы не разойтись с соседними пишущими сценариями.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Заводит проект прогона с буквой-меткой теста; ключ не длиннее 16 знаков. */
async function createProject(request: APIRequestContext, mark: string): Promise<string> {
  const key = `${mark}${RUN}`.slice(0, 16);
  const response = await request.post('/api/v1/projects', {
    headers: auth(),
    data: { key, title: `Перенос прогона ${RUN}`, description: 'Заведён сквозным тестом TRK-173.' },
  });
  expect(response.status()).toBe(201);
  return key;
}

async function createTask(
  request: APIRequestContext,
  project: string,
  title: string,
  description: string,
): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: { project, title, description },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

/** Запись без нагрузки (`decision`/`note`): своя, а не выведенная строка. */
async function addEntry(
  request: APIRequestContext,
  key: string,
  type: 'decision' | 'note',
  title: string,
  body: string,
): Promise<number> {
  const response = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: auth(),
    data: { type, title, body },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { no: number } }).data.no;
}

/** Переносит задачу в другой проект и отдаёт её новый ключ. */
async function moveTask(
  request: APIRequestContext,
  key: string,
  project: string,
  reason: string,
): Promise<string> {
  const response = await request.post(`/api/v1/tasks/${key}/move`, {
    headers: auth(),
    data: { project, reason },
  });
  expect(response.status()).toBe(200);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

test('перенос задачи меняет адрес по прежнему ключу на текущий, и ссылка на прежний ключ из другой задачи тоже ведёт на неё', async ({
  page,
}) => {
  const source = await createProject(page.request, 'S');
  const target = await createProject(page.request, 'T');

  const moving = await createTask(
    page.request,
    source,
    'Задача, которую перенесут',
    'Сквозной тест TRK-173: перенос и адрес по прежнему ключу.',
  );
  const decisionBody = 'Тело решения переносимой задачи, которую перенесут сквозным тестом.';
  const decisionNo = await addEntry(
    page.request,
    moving,
    'decision',
    'Решение, на которое сошлётся другая задача',
    decisionBody,
  );

  const referring = await createTask(
    page.request,
    source,
    'Задача со ссылкой на прежний ключ',
    'Сквозной тест TRK-173: ссылка `ПРЕЖНИЙ-N` в тексте записи.',
  );
  await addEntry(
    page.request,
    referring,
    'note',
    'Ссылка на решение соседней задачи',
    `См. ${moving}#${decisionNo} — решение переносимой задачи.`,
  );

  const movedTo = await moveTask(page.request, moving, target, 'Перенос сквозным тестом TRK-173');
  expect(movedTo).not.toBe(moving);

  await silenceJournal(page);

  // Голый прежний ключ: адрес открывает задачу и сам заменяется на текущий ключ.
  await page.goto(`/tasks/${moving}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(movedTo);
  await expect(page).toHaveURL(new RegExp(`/tasks/${movedTo}$`));

  // Прежний ключ с номером записи: адрес меняется на текущий ключ, номер остаётся тем
  // же, и запись раскрыта.
  await page.goto(`/tasks/${moving}?entry=${decisionNo}`);
  await expect(page).toHaveURL(new RegExp(`/tasks/${movedTo}\\?entry=${decisionNo}$`));
  await expect(page.getByText(decisionBody, { exact: false })).toBeVisible();

  // Прежний ключ виден в шапке карточки и сам ведёт на ту же задачу. `main header`, а
  // не `getByRole('banner')`: своя шапка карточки вложена в `main` и роли `banner`
  // не несёт (её несёт шапка оболочки).
  const header = page.locator('main header');
  const previousLink = header.getByRole('link', { name: moving });
  await expect(previousLink).toBeVisible();
  await expect(previousLink).toHaveAttribute('href', `/tasks/${moving}`);

  // Лента дела показывает перенос. Фильтр — по слову контракта `moved` (латиницей), а
  // не по переведённому заголовку «Перенос»: он не спутается со словом «переносимой» в
  // теле решения регистронезависимо (`hasText` со строкой у Playwright не различает
  // регистр).
  await page.goto(`/tasks/${movedTo}/case`);
  const movedEntry = page.getByRole('article').filter({ hasText: 'moved' });
  await expect(movedEntry).toHaveCount(1);
  await expect(movedEntry).toContainText(moving);
  await expect(movedEntry).toContainText(movedTo);

  // Ссылка `ПРЕЖНИЙ-N`, написанная в тексте другой, не перенесённой задачи, ведёт на
  // перенесённую и тоже переписывает адрес на текущий ключ.
  await page.goto(`/tasks/${referring}`);
  await page.getByRole('button', { name: /Ссылка на решение соседней задачи/ }).click();
  await page.getByRole('link', { name: `${moving}#${decisionNo}` }).click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${movedTo}\\?entry=${decisionNo}$`));
  await expect(page.getByText(decisionBody, { exact: false })).toBeVisible();
});
