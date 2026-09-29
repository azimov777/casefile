import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, shellReady, side } from './contour';

const token = readE2eToken();
const auth = { Authorization: `Bearer ${token}` };

/** Учётная запись владельца контура и правка её пояснений тем же ключом, что у интерфейса. */
async function ownerAccountId(request: APIRequestContext): Promise<string> {
  const response = await request.get('/api/v1/bootstrap', { headers: auth });
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { data: { account: { id: string } | null } };
  const id = body.data.account?.id;
  if (id === undefined) throw new Error('у владельца контура нет учётной записи');
  return id;
}

async function setHints(
  request: APIRequestContext,
  accountId: string,
  hints: { hidden_all: boolean; hidden: string[] },
): Promise<void> {
  const response = await request.patch(`/api/v1/accounts/${accountId}/onboarding`, {
    headers: auth,
    data: { hints },
  });
  expect(response.ok()).toBe(true);
}

/** Имя пункта «Начало» с подписью метки для диктора (TRK-415). */
const UNFINISHED_START = /^Начало\s+Знакомство не пройдено$/;
const TASKS_EXPLANATION = /Здесь все задачи, которые ведут агенты/;
const QUESTIONS_EXPLANATION = /Сюда приходят вопросы, которые агенты задали вам/;

/**
 * Единственный сценарий, который меняет состояние знакомства владельца установки
 * (`TRK-361`, `TRK-360#17`): свежий контур заводит его учётную запись со знакомством
 * `pending` (`app/db/migrations/versions/20260928_1200_onboarding_state.py`), и после
 * «Пропустить» это состояние меняется навсегда. Поэтому файл — в проекте «запись»
 * (`playwright.config.ts`): один сценарий, после читающих, без соседа, который увидел
 * бы уже пройденное «Начало» вместо свежего.
 *
 * Содержимое экрана (четыре раздела по порядку `TRK-360#14`, фразы «Завести задачи» и
 * «Выполнить задачи» с текстом о новой сессии между ними) проверяется здесь же, на
 * первом и единственном заходе, где `/` действительно открывает «Начало» на этом
 * контуре: у читающих сценариев (`start.spec.ts`) той же гарантии нет, поэтому они
 * открывают `/start` напрямую и в решение `/` не заглядывают.
 */
const SECTION_HEADINGS = [
  'Зачем это',
  'Откуда берутся задачи',
  'Что сказать агенту',
  'Что делать самому',
];

test('«Начало» на свежем контуре объясняет способ работы и уступает место списку задач после «Пропустить»', async ({
  page,
  browser,
  request,
}) => {
  // Контур поднят со скрытыми пояснениями (`global-setup.ts`); новому человеку они
  // показаны — возвращаем это состояние, чтобы «Пропустить» было что скрывать (TRK-385).
  const accountId = await ownerAccountId(request);
  await setHints(request, accountId, { hidden_all: false, hidden: [] });

  try {
    await page.goto('/');

    await expect(page).toHaveURL(/\/start$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Начало' })).toBeVisible();

    // Знакомство не пройдено — пункт «Начало» в панели отмечен (TRK-415).
    await expect(side(page).getByRole('link', { name: UNFINISHED_START })).toBeVisible();

    // Четыре раздела по порядку решения TRK-360#14 — это главное, что человек должен
    // понять с первого взгляда.
    expect(await page.locator('main h2').allTextContents()).toEqual(SECTION_HEADINGS);

    // Фразы «Завести задачи» и «Выполнить задачи», а между ними — про новую сессию
    // агента. Фразы «Знакомство» нет: учебного проекта в продукте больше нет (TRK-387).
    await expect(page.getByRole('heading', { name: 'Знакомство' })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Завести задачи' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Выполнить задачи' })).toBeVisible();

    const tellAgentText = (await page.locator('main').innerText()).replace(/\s+/g, ' ');
    const fileAt = tellAgentText.indexOf('Завести задачи');
    const sessionAt = tellAgentText.indexOf('новой сессии агента');
    const executeAt = tellAgentText.indexOf('Выполнить задачи');
    expect(fileAt).toBeGreaterThan(-1);
    expect(sessionAt).toBeGreaterThan(fileAt);
    expect(executeAt).toBeGreaterThan(sessionAt);

    await page.getByRole('button', { name: 'Пропустить' }).click();
    await expect(page).toHaveURL(/\/tasks$/);

    // Держится после перезагрузки: состояние живёт на сервере, не в браузере.
    await page.reload();
    await expect(page).toHaveURL(/\/tasks$/);
    await page.goto('/');
    await expect(page).toHaveURL(/\/tasks$/);

    // «Начало» остаётся достижимым пунктом панели, сколько бы раз его ни пропустили,
    // и пропустившему метка не гаснет (TRK-415): он объяснения не видел.
    await side(page).getByRole('link', { name: UNFINISHED_START }).click();
    await expect(page).toHaveURL(/\/start$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Начало' })).toBeVisible();

    // «Пропустить» — пропустить обучение целиком (TRK-385): на списке задач пояснения нет.
    await expect(page.getByRole('main').getByText(TASKS_EXPLANATION)).toHaveCount(0);

    // Новый браузерный контекст той же учётной записи: `/` открывает список, пояснений
    // нет ни на нём, ни на Входящей — скрытие серверное.
    const context = await browser.newContext();
    try {
      const fresh = await context.newPage();
      await fresh.goto('/');
      await shellReady(fresh);
      await expect(fresh).toHaveURL(/\/tasks$/);
      await expect(fresh.getByRole('main').getByText(TASKS_EXPLANATION)).toHaveCount(0);
      await fresh.goto('/questions');
      await shellReady(fresh);
      await expect(fresh.getByRole('main').getByText(QUESTIONS_EXPLANATION)).toHaveCount(0);
    } finally {
      await context.close();
    }

    // «Я разобрался» гасит метку без перезагрузки страницы (TRK-415).
    await page.goto('/start');
    await page.getByRole('button', { name: 'Я разобрался' }).click();
    await expect(page.getByRole('link', { name: 'Начало', exact: true })).toBeVisible();
    await expect(side(page).getByRole('link', { name: UNFINISHED_START })).toHaveCount(0);

    // Вернуть пояснения можно одним действием на «Начале».
    await page.goto('/start');
    await page.getByRole('button', { name: 'Показать пояснения снова' }).click();
    await expect(page.getByRole('button', { name: 'Показать пояснения снова' })).toHaveCount(0);
    await page.goto('/tasks');
    await expect(page.getByRole('main').getByText(TASKS_EXPLANATION)).toBeVisible();
  } finally {
    // Соседним пишущим сценариям нужен контур со скрытыми пояснениями.
    await setHints(request, accountId, { hidden_all: true, hidden: [] });
  }
});
