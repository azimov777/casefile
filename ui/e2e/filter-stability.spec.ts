import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/*
 * Применение и сброс фильтра не двигают строку «Задачи N · поиск · Фильтр · сортировка ·
 * Запрос» и верх доски (TRK-418): меняются цифры и карточки, а не координаты. Сдвиги
 * меряются boundingBox до и после, включая вертикальные. Каталог снимков — `SHOTS_DIR`
 * (только для ручного «до/после»; в обычном прогоне переменной нет и снимков нет).
 */

const SHOTS_DIR = process.env.SHOTS_DIR;
/** Приоритет, который сужает двузначную выдачу до однозначной. */
const NARROW = 'low';
/** Сколько задач нужно, чтобы число у заголовка было двузначным. */
const WIDE = 30;

type Frame = Record<string, { x: number; y: number; width: number; height: number } | null>;

/** Координаты всего, что не должно двигаться. */
async function frame(page: Page): Promise<Frame> {
  return page.evaluate(() => {
    const rect = (node: Element | null) => {
      if (node === null) return null;
      const box = node.getBoundingClientRect();
      return { x: box.x, y: box.y, width: box.width, height: box.height };
    };
    const section = document.querySelector('section[aria-label]');
    const tools = section?.children[0]?.children ?? [];
    const states = section?.children[1]?.children ?? [];
    const out: Record<string, ReturnType<typeof rect>> = {
      title: rect(document.querySelector('main h1')),
      counter: rect(document.querySelector('main h1 span')),
      section: rect(section ?? null),
      search: rect(document.querySelector('main input[type="search"]')),
      main: rect(document.querySelector('main')),
      top: rect(document.querySelector('header')),
      content: rect(
        document.querySelector('[data-board]') ??
          document.querySelector('main table') ??
          document.querySelector('main thead'),
      ),
    };
    Array.from(tools).forEach((node, index) => (out[`tool${index}`] = rect(node)));
    Array.from(states).forEach((node) => {
      const name =
        node.tagName === 'UL'
          ? 'state-chips'
          : node.tagName === 'LABEL'
            ? 'state-archive'
            : node.tagName === 'BUTTON' && node.getAttribute('aria-label') !== null
              ? 'state-help'
              : node.tagName === 'BUTTON'
                ? 'state-reset'
                : null;
      if (name !== null) out[name] = rect(node);
    });
    return out;
  });
}

function diff(before: Frame, after: Frame): string[] {
  const lines: string[] = [];
  for (const name of Object.keys(before)) {
    const a = before[name];
    const b = after[name];
    if (a === null || b === null || b === undefined) continue;
    // Высота выдачи и ширина строки состояния меняются законно: меньше строк, другие
    // чипы. Не должны двигаться начало и всё, что в строке инструментов.
    const keys =
      name === 'main' || name === 'content'
        ? (['x', 'y'] as const)
        : name === 'state-chips' || name === 'state-reset'
          ? (['y', 'height'] as const)
          : (['x', 'y', 'width', 'height'] as const);
    for (const key of keys) {
      const delta = Math.round((b[key] - a[key]) * 100) / 100;
      if (delta !== 0) lines.push(`${name}.${key}: ${a[key]} -> ${b[key]} (${delta})`);
    }
  }
  return lines;
}

async function shot(page: Page, name: string, scheme: string) {
  if (SHOTS_DIR === undefined) return;
  mkdirSync(SHOTS_DIR, { recursive: true });
  await page.screenshot({
    path: resolve(SHOTS_DIR, `${name}-${scheme}-${page.viewportSize()?.width}.png`),
  });
}

/** Число выдачи из заголовка. */
async function found(page: Page): Promise<number> {
  const text = (await page.locator('main h1 span').textContent()) ?? '';
  return Number(text.replace(/\D/g, ''));
}

/**
 * В демо семь задач: число у заголовка однозначное, и сужаться ему некуда. Сценарий
 * доводит выдачу до двузначной и заводит одну задачу с приоритетом `low`, чтобы после
 * фильтра число было однозначным. Поэтому он пишущий и идёт проектом «запись»
 * (`playwright.config.ts`), как `paging.spec.ts`.
 */
async function seed(request: APIRequestContext): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` };
  const query = new URLSearchParams({ project: 'DEMO', fields: 'status', limit: '1' });
  const listed = await request.get(`/api/v1/tasks?${query.toString()}`, { headers });
  const total = ((await listed.json()) as { meta: { total: number | null } }).meta.total ?? 0;
  const make = (index: number, priority: string) =>
    request.post('/api/v1/tasks', {
      headers,
      data: {
        project: 'DEMO',
        area: 'DEMO/core',
        title: `Задача для проверки сдвига при фильтре № ${index}`,
        description: 'Заведена сквозным тестом, чтобы число выдачи было двузначным.',
        priority,
      },
    });
  const created = [make(0, NARROW)];
  for (let index = 1; index < WIDE - total; index += 1) created.push(make(index, 'normal'));
  for (const response of await Promise.all(created)) expect(response.status()).toBe(201);
}

test.beforeAll(async ({ request }) => {
  await seed(request);
});

const WIDTHS = [1440, 390];
const SCHEMES = ['light', 'dark'] as const;

for (const [view, width, scheme] of SCHEMES.flatMap((c) =>
  WIDTHS.flatMap((w) => ['', '&view=board'].map((v) => [v, w, c] as const)),
)) {
  test(`фильтр и сброс не двигают строку отбора и верх выдачи (${view === '' ? 'таблица' : 'доска'}, ${width} px), ${scheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.setViewportSize({ width, height: 900 });
    await silenceJournal(page);
    const priority = NARROW;
    await page.goto(`/tasks?project=DEMO${view}`);
    await expect(page.locator('main h1 span')).toBeVisible();
    await fontsReady(page);
    await page.waitForTimeout(500);
    const wide = await found(page);
    const start = await frame(page);
    await shot(
      page,
      `${process.env.SHOTS_TAG ?? 'before'}-${view === '' ? 'table' : 'board'}-0`,
      scheme,
    );

    await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
    await page
      .getByRole('dialog', { name: 'Условия отбора задач' })
      .getByRole('button', { name: `приоритет ${priority}`, exact: true })
      .click();
    await expect(page).toHaveURL(new RegExp(`priority=${priority}`));
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(async () => expect(await found(page)).toBeLessThan(10)).toPass();
    await page.waitForTimeout(500);
    const narrowed = await frame(page);
    await shot(
      page,
      `${process.env.SHOTS_TAG ?? 'before'}-${view === '' ? 'table' : 'board'}-1`,
      scheme,
    );

    await page.getByRole('button', { name: 'Сбросить' }).click();
    await expect(async () => expect(await found(page)).toBe(wide)).toPass();
    await page.waitForTimeout(500);
    const back = await frame(page);

    const applied = diff(start, narrowed);
    const reset = diff(start, back);
    console.log(
      `[TRK-418 ${view || 'table'} ${width} ${scheme}] применение:\n${applied.join('\n')}`,
    );
    console.log(`[TRK-418 ${view || 'table'} ${width} ${scheme}] сброс:\n${reset.join('\n')}`);
    expect(applied, 'применение фильтра сдвинуло разметку').toEqual([]);
    expect(reset, 'сброс вернул не на те координаты').toEqual([]);
  });
}
