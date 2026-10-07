import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, side, silenceJournal } from './contour';

const token = readE2eToken();

/** Записи дела обсуждения — правда бэкенда, а не экрана. */
async function entriesOf(
  request: APIRequestContext,
  address: string,
): Promise<{ type: string; author: { kind: string }; title: string; body: string }[]> {
  const response = await request.get(`/api/v1/discussions/${address}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as {
    data: { type: string; author: { kind: string }; title: string; body: string }[];
  };
  return body.data;
}

/** Привязанные к обсуждению задачи — тоже правда бэкенда. */
async function attachedTo(request: APIRequestContext, address: string): Promise<string[]> {
  const response = await request.get(`/api/v1/discussions/${address}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: { tasks: { key: string }[] } };
  return body.data.tasks.map((task) => task.key);
}

/**
 * Сквозной сценарий обсуждений (TRK-672, решение проекта `TRK#51`, п. 8): обсуждение с
 * вопросом видно во входящей → ответ на экране обсуждения → обсуждение уходит из входящей;
 * заметка человека появляется в ленте; задача привязывается и отвязывается; у закрытого
 * обсуждения нет ни форм, ни кнопок привязки.
 *
 * Пишет в демо-установку (ответ закрывает вопрос навсегда), поэтому вынесен в проект
 * «запись» и идёт после читающих (`playwright.config.ts`). Три обсуждения демо — закрытое
 * `DEMO~1`, ждущее человека `DEMO~2` и ждущее агента `DEMO~3`, — все без привязок к
 * задачам, которые читают другие сценарии.
 */
test('обсуждение: из входящей — ответ на экране — уходит из входящей', async ({
  page,
  request,
}) => {
  await silenceJournal(page);
  await page.goto('/questions');

  const inbox = page.getByRole('region', { name: 'Обсуждения, ждущие вас' });
  const waiting = inbox.getByRole('article', { name: 'Обсуждение DEMO~2' });
  await expect(waiting).toBeVisible();
  await expect(waiting.getByText('1 вопрос без ответа')).toBeVisible();
  await expect(waiting.getByText('ждёт вас')).toBeVisible();
  // Ход агента и закрытое во входящей не ждут человека.
  await expect(inbox.getByRole('article')).toHaveCount(1);
  await expect(side(page).getByText('1 обсуждение ждёт вас')).toBeAttached();

  await waiting.getByRole('link', { name: 'DEMO~2', exact: true }).click();
  await expect(page).toHaveURL(/\/discussions\/DEMO~2$/);
  await expect(
    page.getByRole('heading', { level: 1, name: 'Сколько хранить дела отменённых задач?' }),
  ).toBeVisible();

  // Закрыть обсуждение человек не может: кнопки нет.
  await expect(
    page.getByRole('button', { name: /закрыть обсуждение|close discussion/i }),
  ).toHaveCount(0);

  const thread = page.getByRole('list', { name: 'Записи обсуждения по времени' });
  await expect(thread.getByText('ждёт ответа')).toBeVisible();

  const posts: string[] = [];
  page.on('request', (call) => {
    if (call.method() === 'POST' && call.url().endsWith('/discussions/DEMO~2/entries')) {
      posts.push(call.headers()['idempotency-key'] ?? '');
    }
  });

  await page.getByRole('button', { name: 'Ответить на #2' }).click();
  await page
    .getByRole('textbox', { name: 'Ответ', exact: true })
    .fill('Храним вечно: дело неизменяемо.');
  await page.getByRole('button', { name: 'Ответить', exact: true }).click();

  // Ответ появился в переписке, вопрос назван отвеченным, кнопки «Ответить» больше нет.
  await expect(thread.getByText('Храним вечно: дело неизменяемо.')).toBeVisible();
  await expect(thread.getByText('отвечено')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ответить на #2' })).toHaveCount(0);
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatch(/^[0-9a-f-]{36}$/);

  const stored = await entriesOf(request, 'DEMO~2');
  expect(stored.filter((entry) => entry.type === 'answer')).toHaveLength(1);

  // Обсуждение ушло из входящей, значок погас.
  await page.goto('/questions');
  await expect(page.getByText('Обсуждений, ждущих вас, нет.')).toBeVisible();
  await expect(page.getByRole('article', { name: 'Обсуждение DEMO~2' })).toHaveCount(0);
  await expect(side(page).getByText(/ждёт вас|ждут вас/)).toHaveCount(0);

  // В истории оно есть, и ход теперь за агентом.
  await page.goto('/questions?view=history');
  const history = page.getByRole('region', { name: 'Обсуждения', exact: true });
  const row = history.getByRole('article', { name: 'Обсуждение DEMO~2' });
  await expect(row.getByText('ход агента')).toBeVisible();
  await expect(
    history.getByRole('article', { name: 'Обсуждение DEMO~1' }).getByText('закрыто'),
  ).toBeVisible();
});

test('заметка человека появляется в переписке', async ({ page, request }) => {
  await silenceJournal(page);
  await page.goto('/discussions/DEMO~2');

  await page.getByRole('button', { name: 'Заметка', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Заметка', exact: true })
    .fill('Это касается и архивных проектов.\nСм. DEMO~1#2');
  await page.getByRole('button', { name: 'Подшить заметку' }).click();

  const thread = page.getByRole('list', { name: 'Записи обсуждения по времени' });
  await expect(thread.getByText('Это касается и архивных проектов.').first()).toBeVisible();

  const note = (await entriesOf(request, 'DEMO~2')).find(
    (entry) => entry.type === 'note' && entry.body.includes('архивных проектов'),
  );
  expect(note?.author.kind).toBe('human');
  expect(note?.title).toBe('Это касается и архивных проектов.');
});

test('задача привязывается и отвязывается, и это видно в её карточке', async ({
  page,
  request,
}) => {
  await silenceJournal(page);
  await page.goto('/discussions/DEMO~2');

  await page.getByRole('textbox', { name: 'Привязать задачу по ключу' }).fill('DEMO-9');
  await page.getByRole('button', { name: 'Привязать', exact: true }).click();

  const tasks = page.getByRole('region', { name: 'Задачи, ждущие итога' });
  await expect(tasks.getByRole('link', { name: 'DEMO-9' })).toBeVisible();
  expect(await attachedTo(request, 'DEMO~2')).toEqual(['DEMO-9']);

  // В карточке задачи — блок её обсуждений: адрес, название, чей ход.
  await page.goto('/tasks/DEMO-9');
  const block = page.getByRole('region', { name: 'Обсуждения', exact: true });
  await expect(block.getByRole('link', { name: 'DEMO~2' })).toHaveAttribute(
    'href',
    '/discussions/DEMO~2',
  );
  await expect(block.getByText('Сколько хранить дела отменённых задач?')).toBeVisible();
  await expect(block.getByText('ход агента')).toBeVisible();

  await block.getByRole('link', { name: 'DEMO~2' }).click();
  await page.getByRole('button', { name: 'Отвязать задачу DEMO-9' }).click();
  await expect(tasks.getByText('Задач к обсуждению не привязано.')).toBeVisible();
  expect(await attachedTo(request, 'DEMO~2')).toEqual([]);

  await page.goto('/tasks/DEMO-9');
  await expect(page.getByText('Обсуждений нет.')).toBeVisible();
});

test('у закрытого обсуждения нет форм и кнопок привязки, итог сверху', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/discussions/DEMO~1');

  await expect(page.getByText(/Обсуждение закрыто .*Закрывает его агент/)).toBeVisible();
  const conclusion = page.getByRole('region', { name: 'Итог', exact: true });
  await expect(conclusion.getByText('Решено')).toBeVisible();
  await expect(
    conclusion.getByText(/Вопросы архивных проектов во входящей не показываются/),
  ).toBeVisible();

  await expect(page.getByRole('button', { name: 'Заметка', exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Привязать задачу по ключу' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Привязать', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Отвязать/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Ответить/ })).toHaveCount(0);
  // Закрыть закрытое тоже нечем.
  await expect(page.getByRole('button', { name: /закры/i })).toHaveCount(0);
});

test('«Новое обсуждение» заводит запиской и открывает его', async ({ page, request }) => {
  await silenceJournal(page);
  await page.goto('/questions');

  await page.getByRole('button', { name: 'Новое обсуждение' }).click();
  const dialog = page.getByRole('dialog', { name: 'Новое обсуждение' });
  await dialog.getByLabel('Проект').selectOption('DEMO');
  await dialog.getByLabel('Название — сам вопрос').fill('Нужна ли тема для печати?');
  await dialog.getByLabel('Контекст').fill('Смотрел макет.\nСм. DEMO~1#2');
  await dialog.getByRole('button', { name: 'Завести обсуждение' }).click();

  await expect(page).toHaveURL(/\/discussions\/DEMO~\d+$/);
  await expect(
    page.getByRole('heading', { level: 1, name: 'Нужна ли тема для печати?' }),
  ).toBeVisible();
  // Заведено запиской человека, без вопроса: ход за агентом.
  await expect(page.getByText('ход агента').first()).toBeVisible();

  const address = new URL(page.url()).pathname.split('/').pop() ?? '';
  const entries = await entriesOf(request, decodeURIComponent(address));
  expect(entries.some((entry) => entry.type === 'note' && entry.author.kind === 'human')).toBe(
    true,
  );
  expect(entries.some((entry) => entry.type === 'question')).toBe(false);
});
