import AxeBuilder from '@axe-core/playwright';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readAgentKey, readE2eToken } from './contour';

/*
 * Закрытие не целиком и реакция человека (TRK-561): агент закрывает задачу с проверкой
 * `unverifiable`, задача ждёт во «Входящих» в разделе «Требуют внимания», человек
 * открывает её и принимает предупреждение — и раздел пустеет.
 *
 * Закрывает агент своим ключом, принимает человек ключом интерфейса: принять
 * предупреждение подписью, закрывшей задачу, нельзя (`acceptance_by_closer`).
 *
 * Снимки экрана — только когда задан `SHOTS_DIR`: ими исполнитель показывает вид
 * «до» и «после» реакции; обычный прогон их не пишет.
 */

const agent = readAgentKey();

async function call(
  request: APIRequestContext,
  path: string,
  data: Record<string, unknown>,
  expected: number,
): Promise<Record<string, unknown>> {
  const response = await request.post(path, {
    headers: { Authorization: `Bearer ${agent}` },
    data,
  });
  expect(response.status(), await response.text()).toBe(expected);
  return ((await response.json()) as { data: Record<string, unknown> }).data;
}

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.SHOTS_DIR;
  if (dir === undefined || dir === '') return;
  mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: resolve(dir, `${name}.png`), fullPage: true });
}

/** Задача агента, закрытая с проверкой 2 `unverifiable`. Возвращает её ключ. */
async function closedNotInFull(request: APIRequestContext): Promise<string> {
  const task = await call(
    request,
    '/api/v1/tasks',
    {
      project: 'DEMO',
      area: 'DEMO/core',
      title: 'Подсказка о сгоревшем номере на телефоне',
      description: 'Заведена сквозным тестом закрытия не целиком.',
      goal: 'Подсказку видно на телефоне',
      context: 'Список задач',
      constraints: 'Счётчик не трогать',
      output: 'Подсказка в шапке списка',
      checks: ['Тест страницы списка зелёный', 'Подсказку видно в Safari владельца на телефоне'],
      assignee: 'demo_agent',
    },
    201,
  );
  const key = task.key as string;
  for (const to of ['open', 'in_progress']) {
    await call(request, `/api/v1/tasks/${key}/transition`, { to }, 200);
  }
  await call(
    request,
    `/api/v1/tasks/${key}/close`,
    {
      summary: {
        done: 'Подсказка есть; Safari не проверен',
        remaining: 'nothing',
        blockers: 'nothing',
        next_step: 'no steps',
        unmeasured: 'Вид в Safari на телефоне',
      },
      verdicts: [
        { check_no: 1, outcome: 'passed', evidence: 'pnpm test tasks-page: 12 passed' },
        {
          check_no: 2,
          outcome: 'unverifiable',
          evidence: 'Safari владельца недоступен; прогнан Chromium на 390 px',
        },
      ],
    },
    200,
  );
  return key;
}

test('закрытая не целиком задача ждёт во «Входящих», пока человек её не примет', async ({
  page,
  request,
}) => {
  const key = await closedNotInFull(request);

  await page.goto('/questions');
  const attention = page.getByRole('region', { name: 'Требуют внимания' });
  await expect(attention.getByRole('link', { name: key })).toBeVisible();
  await shot(page, 'inbox-before');

  await attention.getByRole('link', { name: key }).click();
  const panel = page.getByRole('region', { name: 'Закрыта не целиком' });
  await expect(panel).toContainText('невозможно проверить');
  await expect(panel).toContainText('Подсказку видно в Safari владельца на телефоне');
  const violations = (await new AxeBuilder({ page }).analyze()).violations;
  expect(violations.map((item) => item.id)).toEqual([]);
  await shot(page, 'task-before');

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel).toBeVisible();
  // Телефон — полноценная цель: страница не прокручивается вбок.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
  await shot(page, 'task-before-390');
  await page.setViewportSize({ width: 1280, height: 900 });

  await panel.getByRole('button', { name: 'Принять' }).click();
  await expect(panel).toHaveCount(0);
  await shot(page, 'task-after');

  await page.goto('/questions');
  await expect(page.getByRole('region', { name: 'Требуют внимания' })).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Требуют внимания' }).getByRole('link', { name: key }),
  ).toHaveCount(0);
  await shot(page, 'inbox-after');
});

/*
 * «Вернуть на доработку» (TRK-731): возврат — это замечание (TRK#117), форма которого живёт
 * в блоке «Замечания» ниже плашки. Нажатие должно привести человека к форме: она в видимой
 * области, курсор в поле. После отправки плашка уходит (замечание снимает предупреждение),
 * и на её месте остаётся пояснение, почему и что дальше.
 *
 * Меряется на телефоне и на десктопе: на длинной карточке форма раньше оставалась за краем
 * экрана, и нажатие выглядело как «ничего не произошло».
 */
for (const size of [
  { name: '390', width: 390, height: 800 },
  { name: '1280', width: 1280, height: 800 },
]) {
  test(`«Вернуть на доработку» ведёт к форме замечания и объясняет исход (${size.name} px)`, async ({
    page,
    request,
  }) => {
    const key = await closedNotInFull(request);
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.goto(`/tasks/${key}`);

    const panel = page.getByRole('region', { name: 'Закрыта не целиком' });
    await expect(panel).toBeVisible();
    await panel.getByRole('button', { name: 'Вернуть на доработку' }).click();

    const field = page.getByLabel(/^Замечание$/);
    await expect(field).toBeVisible();
    // Измерение до проверки: цифры нужны делу задачи, даже когда проверка падает.
    const seen = await field.evaluate((node) => {
      const box = node.getBoundingClientRect();
      return {
        top: Math.round(box.top),
        bottom: Math.round(box.bottom),
        viewport: window.innerHeight,
        scrollY: Math.round(window.scrollY),
        focused: document.activeElement === node,
      };
    });
    console.log(`TRK-731 ${size.name}: ${JSON.stringify(seen)}`);
    await shot(page, `return-opened-${size.name}`);

    // Форма целиком в видимой области, курсор в поле.
    expect(seen.top).toBeGreaterThanOrEqual(0);
    expect(seen.bottom).toBeLessThanOrEqual(seen.viewport);
    expect(seen.focused).toBe(true);

    await page.keyboard.type('Safari на телефоне так и не проверен, проверьте.');
    await page.getByRole('button', { name: 'Оставить замечание' }).click();

    // Плашка ушла, но не молча: на её месте сказано, что произошло.
    await expect(panel).toHaveCount(0);
    const note = page.getByRole('status').filter({ hasText: 'Замечание принято' });
    await expect(note).toBeVisible();
    await expect(note).toContainText('снимает предупреждение');
    await expect(note).toContainText('разберёт агент');
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
    await shot(page, `return-after-${size.name}`);

    // Правда бэкенда: в деле есть remark, предупреждение закрыто.
    const task = await request.get(`/api/v1/tasks/${key}`, {
      headers: { Authorization: `Bearer ${readE2eToken()}` },
    });
    const features = ((await task.json()) as { data: { features: { open_warnings: number } } }).data
      .features;
    expect(features.open_warnings).toBe(0);
    const remarks = await request.get(`/api/v1/tasks/${key}/entries?types=remark`, {
      headers: { Authorization: `Bearer ${readE2eToken()}` },
    });
    expect(((await remarks.json()) as { data: unknown[] }).data).toHaveLength(1);
  });
}
