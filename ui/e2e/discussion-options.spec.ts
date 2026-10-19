import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext } from '@playwright/test';
import { askWithOptions, fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Запись ответа в деле обсуждения — правда бэкенда, а не экрана. */
async function answersOf(
  request: APIRequestContext,
  address: string,
): Promise<{ type: string; body: string; payload: { choice?: string | null } }[]> {
  const response = await request.get(`/api/v1/discussions/${address}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as {
    data: { type: string; body: string; payload: { choice?: string | null } }[];
  };
  return body.data.filter((entry) => entry.type === 'answer');
}

const QUESTION = {
  title: 'Присылать числа сейчас или закрыть с «не измерено»?',
  body: 'Рекомендую вариант 1.',
  options: [
    {
      label: '1',
      text: 'Прислать числа сейчас как замер «до», через неделю ещё раз. Задача остаётся открытой.',
    },
    { label: '2', text: 'Прислать числа один раз и закрыть задачу с честным «не измерено».' },
    { label: '3', text: 'Замер не нужен: закрыть по проверке 1.' },
  ],
};

/**
 * Ответ выбором из вариантов вопроса (TRK-720, решение `TRK/discussions#3`). Пишет в демо
 * (ответ закрывает вопрос навсегда), поэтому идёт в проекте «запись»: имя файла начинается с
 * `discussion`. Вопрос заводится здесь же — вариантов у вопросов демо нет, а REST вопросы не
 * подшивает. Телефон 390 px — полноценная цель (TRK#241): страница без прокрутки вбок,
 * карточка не ниже 44 px.
 */
test('ответ выбором: карточки на телефоне, выбор уходит в choice, метка видна в записи', async ({
  page,
  request,
}) => {
  const address = askWithOptions(QUESTION);
  expect(address).toMatch(/^DEMO~\d+$/);

  await silenceJournal(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/discussions/${address}`);
  await page.getByRole('button', { name: 'Ответить на #1' }).click();
  await fontsReady(page);

  const group = page.getByRole('radiogroup', { name: 'Выберите вариант' });
  const cards = group.locator('label[data-option]');
  await expect(cards).toHaveCount(3);

  // Телефон: без прокрутки вбок, карточка на всю ширину группы и не ниже 44 px.
  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    inner: window.innerWidth,
  }));
  expect(widths.scroll).toBe(widths.inner);
  const groupBox = await group.boundingBox();
  for (let index = 0; index < 3; index += 1) {
    const box = await cards.nth(index).boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    expect(Math.round(box?.width ?? 0)).toBe(Math.round(groupBox?.width ?? -1));
  }

  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations).toEqual([]);

  const posts: string[] = [];
  page.on('request', (call) => {
    if (call.method() === 'POST' && call.url().endsWith(`/discussions/${address}/entries`)) {
      posts.push(call.postData() ?? '');
    }
  });

  // Выбор без слов и текст рядом.
  await cards.nth(0).click();
  await expect(group.getByRole('radio', { name: /Прислать числа сейчас/ })).toBeChecked();
  await page
    .getByRole('textbox', { name: /Пояснение или свой ответ/ })
    .fill('Всего 125 установок. Вызовов не было.');
  await page.getByRole('button', { name: 'Ответить', exact: true }).click();

  const thread = page.getByRole('list', { name: 'Записи обсуждения по времени' });
  const answer = thread.locator('[data-type="answer"]');
  await expect(answer.getByText('Выбрано: 1')).toBeVisible();
  await expect(answer.getByText(/Прислать числа сейчас как замер/)).toBeVisible();
  await expect(answer.getByText('Всего 125 установок. Вызовов не было.')).toBeVisible();
  await expect(thread.getByText('отвечено')).toBeVisible();
  expect(posts).toHaveLength(1);

  const stored = await answersOf(request, address);
  expect(stored).toHaveLength(1);
  expect(stored[0]?.payload.choice).toBe('1');
  expect(stored[0]?.body).toBe('Всего 125 установок. Вызовов не было.');

  // Широкий экран: тот же вид без прокрутки вбок.
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.reload();
  await expect(thread.locator('[data-type="answer"]').getByText('Выбрано: 1')).toBeVisible();
});

test('ответ одним выбором, без слов', async ({ page, request }) => {
  const address = askWithOptions({ ...QUESTION, title: 'Второй вопрос с вариантами' });

  await silenceJournal(page);
  await page.goto(`/discussions/${address}`);
  await page.getByRole('button', { name: 'Ответить на #1' }).click();
  await page.getByRole('radio', { name: /Замер не нужен/ }).check();
  await page.getByRole('button', { name: 'Ответить', exact: true }).click();

  const answer = page
    .getByRole('list', { name: 'Записи обсуждения по времени' })
    .locator('[data-type="answer"]');
  await expect(answer.getByText('Выбрано: 3')).toBeVisible();
  await expect(answer.getByText('Замер не нужен: закрыть по проверке 1.')).toBeVisible();

  const stored = await answersOf(request, address);
  expect(stored[0]?.payload.choice).toBe('3');
  expect(stored[0]?.body).toBe('');
});
