import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

/**
 * Проход по экранам на настоящем контуре с учебным проектом `START` (TRK-364): кнопка
 * на «Начало», восемь шагов по порядку таблицы задания, на каждом — пояснение с
 * ключом шага и счётчик «Шаг N из 8», «Закончить» возвращает на `/start`. Контур
 * поднимается с `hidden_all: true` (`global-setup.ts`), и проход показывает пояснения
 * всё равно. Файл идёт в проект «запись» вместе с прочими сценариями пояснений
 * (`explanations.spec.ts` в его выражении): проход сам ничего не пишет, но читает
 * состояние пояснений, которое соседи по проекту включают и возвращают.
 *
 * Снимки шагов 1, 3 и 6 кладутся в каталог из `WALK_SHOTS`, если он задан.
 */

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Шаги по порядку: адрес без `walk` (для `START`) и начало текста пояснения, `ru`. */
const STEPS: { path: string; text: string }[] = [
  {
    path: '/tasks?project=START',
    text: 'Здесь все задачи, которые ведут агенты.',
  },
  {
    path: '/tasks?project=START&view=board',
    text: 'Те же задачи одного проекта по шести столбцам статусов.',
  },
  { path: '/tasks/START-', text: 'Это задание агенту и то, что по нему сделано' },
  { path: '/tasks/START-', text: 'Дело — журнал задачи' },
  { path: '/projects/START', text: 'Проект отвечает на вопрос «про что задачи».' },
  { path: '/questions', text: 'Сюда приходят вопросы, которые агенты задали вам.' },
  { path: '/connect', text: 'Агент работает с Casefile через MCP' },
  { path: '/access', text: 'Здесь все токены установки' },
];

/** Состояние знакомства владельца контура: то, чего проход менять не вправе. */
async function onboarding(request: APIRequestContext): Promise<unknown> {
  const response = await request.get('/api/v1/bootstrap', { headers: auth() });
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as {
    data: { account: { onboarding: { status: string; hints: unknown } } | null };
  };
  return body.data.account?.onboarding;
}

async function startWalk(page: Page): Promise<void> {
  await page.goto('/start');
  await page.getByRole('main').getByRole('link', { name: 'Пройти по экранам' }).click();
}

async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

test('кнопка на /start ведёт по восьми адресам в порядке таблицы, на каждом пояснение и счётчик', async ({
  page,
}) => {
  await silenceJournal(page);
  await startWalk(page);
  const main = page.getByRole('main');

  for (const [index, { path, text }] of STEPS.entries()) {
    const n = index + 1;
    await expect(main.getByText(`Шаг ${n} из 8`), `шаг ${n}`).toBeVisible();
    const url = new URL(page.url());
    const wanted = new URL(path, url.origin);
    if (path.endsWith('-')) {
      // Ключ задачи проекта `START` называет сам контур: сверяется его начало.
      expect(url.pathname.startsWith(wanted.pathname), `шаг ${n}: ${url.pathname}`).toBe(true);
      if (n === 4) expect(url.pathname.endsWith('/case')).toBe(true);
      else expect(url.pathname.endsWith('/case')).toBe(false);
    } else {
      expect(url.pathname, `шаг ${n}`).toBe(wanted.pathname);
      expect(url.searchParams.get('project'), `шаг ${n}`).toBe(wanted.searchParams.get('project'));
      expect(url.searchParams.get('view'), `шаг ${n}`).toBe(wanted.searchParams.get('view'));
    }
    expect(url.searchParams.get('walk'), `шаг ${n}`).toBe(String(n));
    await expect(main.getByText(text), `шаг ${n}`).toBeVisible();

    if (n < 8) await main.getByRole('link', { name: 'Далее' }).click();
  }

  await main.getByRole('link', { name: 'Далее' }).click();
  await expect(page).toHaveURL(/\/start$/);
});

test('«Закончить» на третьем шаге возвращает на /start', async ({ page }) => {
  await silenceJournal(page);
  await startWalk(page);
  const main = page.getByRole('main');
  await main.getByRole('link', { name: 'Далее' }).click();
  await main.getByRole('link', { name: 'Далее' }).click();
  await expect(main.getByText('Шаг 3 из 8')).toBeVisible();
  await main.getByRole('link', { name: 'Закончить' }).click();
  await expect(page).toHaveURL(/\/start$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Начало' })).toBeVisible();
});

test('при hidden_all проход показывает пояснения, ничего не меняет на сервере и переживает перезагрузку', async ({
  page,
  request,
}) => {
  await silenceJournal(page);
  const before = await onboarding(request);
  expect((before as { hints: { hidden_all: boolean } }).hints.hidden_all).toBe(true);

  // Без прохода скрытое пояснение не показано.
  await page.goto('/access');
  await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();
  await expect(page.getByRole('main').getByText('Здесь все токены установки')).toHaveCount(0);

  await startWalk(page);
  const main = page.getByRole('main');
  const writes: string[] = [];
  page.on('request', (item) => {
    if (item.method() === 'PATCH') writes.push(item.url());
  });

  for (let n = 1; n < 4; n += 1) await main.getByRole('link', { name: 'Далее' }).click();
  await expect(main.getByText('Шаг 4 из 8')).toBeVisible();
  await expect(main.getByText('Дело — журнал задачи')).toBeVisible();

  await page.reload();
  await expect(page.getByRole('main').getByText('Шаг 4 из 8')).toBeVisible();
  await expect(page.getByRole('main').getByText('Дело — журнал задачи')).toBeVisible();
  expect(new URL(page.url()).searchParams.get('walk')).toBe('4');

  await page.getByRole('main').getByRole('link', { name: 'Закончить' }).click();
  await expect(page).toHaveURL(/\/start$/);
  expect(writes).toEqual([]);
  expect(await onboarding(request)).toEqual(before);
});

for (const width of [390, 1280]) {
  test(`на ширине ${width} px на восьми шагах нет прокрутки вбок`, async ({ page }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await startWalk(page);
    const main = page.getByRole('main');
    const shots = process.env.WALK_SHOTS;

    for (let n = 1; n <= 8; n += 1) {
      await expect(main.getByText(`Шаг ${n} из 8`)).toBeVisible();
      await expect(main.getByText(STEPS[n - 1]!.text)).toBeVisible();
      await fontsReady(page);
      expect(await overflow(page), `шаг ${n} на ${width} px`).toBeLessThanOrEqual(0);
      if (shots !== undefined && [1, 3, 6].includes(n)) {
        await page.screenshot({ path: `${shots}/walk-step-${n}-${width}.png` });
      }
      await main.getByRole('link', { name: 'Далее' }).click();
    }
  });
}
