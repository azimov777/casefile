import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, readE2eToken } from './contour';

/*
 * Решения проекта (TRK-554): раздел «Решения» на экране проекта — действующие сверху,
 * заменённые свёрнуты вместе с тем, что их заменило, — обратный путь от решения к
 * задачам, сделанным по нему, и строка «Решения» в шапке задачи со статусом.
 *
 * Сценарий пишущий — заводит в проекте `TRK` два решения, второе заменяет первое, и
 * задачу, которая ссылается на первое, — и потому идёт в проекте «запись». Заголовки
 * несут метку прогона: на той же базе повторный прогон застаёт прежние решения, а
 * число задач по решению обязано быть ровно своим.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36);
const OLD = `Номер выдаёт счётчик проекта, прогон ${RUN}`;
const NEW = `Номер выдаётся последним, после проверок, прогон ${RUN}`;
const TASK = `Задача по решению проекта, прогон ${RUN}`;
/**
 * Кнопка свёрнутых заменённых решений: её имя — знак состояния псевдоэлементом и счёт.
 * Число зависит от прежних прогонов на той же базе, поэтому оно не названо.
 */
const SUPERSEDED_TOGGLE = /^[▸▾] Не действу/;

async function api(
  request: APIRequestContext,
  method: 'post' | 'patch',
  path: string,
  data: Record<string, unknown>,
  expected: number[] = [200, 201],
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(expected, await response.text()).toContain(response.status());
  return ((await response.json()) as { data?: Record<string, unknown> }).data ?? {};
}

interface Seeded {
  oldNo: number;
  newNo: number;
  taskKey: string;
}

let ready: Promise<Seeded> | null = null;

/** Решение, задача по нему и решение, которое его заменило, — один раз на файл. */
function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= seedOnce(request);
  return ready;
}

async function seedOnce(request: APIRequestContext): Promise<Seeded> {
  await api(request, 'post', '/api/v1/projects', { key: 'TRK', title: 'Бэкенд' }, [201, 409]);
  const old = await api(request, 'post', '/api/v1/projects/TRK/entries', {
    type: 'decision',
    title: OLD,
    body: 'Счётчик проекта выдаёт номер атомарным запросом.',
  });
  const oldNo = old.no as number;
  const task = await api(request, 'post', '/api/v1/tasks', {
    project: 'TRK',
    title: TASK,
    description: 'Заведена сквозным тестом решений проекта.',
    decisions: [`TRK#${oldNo}`],
  });
  const added = await api(request, 'post', '/api/v1/projects/TRK/entries', {
    type: 'decision',
    title: NEW,
    body: 'Отказ не должен сжигать номер.',
    supersedes: [oldNo],
  });
  return { oldNo, newNo: added.no as number, taskKey: task.key as string };
}

function decisionRow(scope: Page | Locator, ref: string): Locator {
  return scope.locator(`li[data-decision="${ref}"]`);
}

test('экран проекта: действующее решение, заменённое свёрнуто, задачи по решению', async ({
  page,
  request,
}) => {
  const { oldNo, newNo, taskKey } = await seed(request);
  await page.goto('/projects/TRK');

  const region = page.getByRole('region', { name: 'Решения' });
  const current = decisionRow(region, `TRK#${newNo}`);
  await expect(current).toHaveAttribute('data-status', 'in_force');
  await expect(current).toContainText(NEW);
  await expect(current).toContainText('действует');
  await expect(current.getByRole('link', { name: `TRK#${oldNo}` })).toBeVisible();

  // Заменённое — история: свёрнуто, пока его не попросили.
  await expect(decisionRow(region, `TRK#${oldNo}`)).toHaveCount(0);
  await region.getByRole('button', { name: SUPERSEDED_TOGGLE }).click();
  const old = decisionRow(region, `TRK#${oldNo}`);
  await expect(old).toHaveAttribute('data-status', 'superseded');
  await expect(old).toContainText(OLD);
  await expect(old).toContainText(`Заменено решением TRK#${newNo}`);

  // Обратный путь: по заменённому решению — список задач, которые по нему делались.
  await old.getByRole('link', { name: '1 задача по решению' }).click();
  await expect(page).toHaveURL(/\/tasks\?/);
  await expect(page.getByRole('link', { name: new RegExp(TASK) }).first()).toBeVisible();
  await expect(page.getByText(taskKey).first()).toBeVisible();

  // Ссылка решения раскрывает его запись в деле проекта — тело читается там.
  await page.goto('/projects/TRK');
  await decisionRow(page.getByRole('region', { name: 'Решения' }), `TRK#${newNo}`)
    .getByRole('link', { name: `TRK#${newNo}`, exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`[?&]entry=${newNo}(&|$)`));
  await expect(page.getByRole('table').getByRole('button', { name: NEW })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await expect(page.getByText('Отказ не должен сжигать номер.')).toBeVisible();
});

test('шапка задачи: строка «Решения» со статусом и преемником заменённого', async ({
  page,
  request,
}) => {
  const { oldNo, newNo, taskKey } = await seed(request);
  await page.goto(`/tasks/${taskKey}`);

  const row = decisionRow(page, `TRK#${oldNo}`);
  await expect(row).toHaveAttribute('data-status', 'superseded');
  await expect(row).toContainText(OLD);
  await expect(row).toContainText('заменено');
  await expect(row.getByRole('link', { name: `TRK#${newNo}` })).toBeVisible();
  await expect(row).toContainText(NEW);

  await row.getByRole('link', { name: `TRK#${oldNo}`, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/TRK\\?entry=${oldNo}$`));
  await expect(page.getByText('Счётчик проекта выдаёт номер атомарным запросом.')).toBeVisible();
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`доступность решений проекта и шапки задачи: ${colorScheme}, 390px`, async ({
    page,
    request,
  }) => {
    const { oldNo, taskKey } = await seed(request);
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto('/projects/TRK');
    const region = page.getByRole('region', { name: 'Решения' });
    await region.getByRole('button', { name: SUPERSEDED_TOGGLE }).click();
    await expect(decisionRow(region, `TRK#${oldNo}`)).toBeVisible();
    await fontsReady(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(0);

    await page.goto(`/tasks/${taskKey}`);
    await expect(decisionRow(page, `TRK#${oldNo}`)).toBeVisible();
    await fontsReady(page);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(0);
  });
}
