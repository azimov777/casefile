import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Заводит задачу в демо-очереди и возвращает её ключ. */
async function makeTask(
  request: APIRequestContext,
  title: string,
  sections: Record<string, unknown> = {},
): Promise<string> {
  // Разделы лежат верхним уровнем запроса, а не во вложенном `sections`: так их
  // описывает контракт (`TaskCreate` в `openapi.json`). Вложенный объект даёт 422.
  const created = await request.post('/api/v1/tasks', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      queue: 'DEMO',
      title,
      description: 'Заведена сквозным тестом ради проверки раскладки карточки.',
      ...sections,
    },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { data: { key: string } }).data.key;
}

async function addEntry(
  request: APIRequestContext,
  key: string,
  body: Record<string, unknown>,
): Promise<number> {
  const response = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { no: number } }).data.no;
}

/** Высота окна: по ней считается «первый экран». */
async function viewportHeight(page: Page): Promise<number> {
  return page.evaluate(() => window.innerHeight);
}

/**
 * Задача, на которой видно, ради чего карточку открывают: одна открытая просьба,
 * сводка из четырёх частей и дело из восьми записей.
 */
async function busyTask(request: APIRequestContext): Promise<string> {
  const key = await makeTask(request, 'Задача для проверки раскладки карточки');

  await addEntry(request, key, {
    type: 'summary',
    payload: {
      done: 'Разобрался, где теряется запись: граница выборки хвоста считает строго больше.',
      remaining: 'Поправить условие и написать тест на разрыв соединения посреди выдачи.',
      blockers: 'Ничего',
      next_step: 'Переписать условие выборки хвоста в journal_page',
    },
  });

  for (let index = 0; index < 6; index += 1) {
    await addEntry(request, key, {
      type: 'note',
      title: `Заметка ${index + 1} ради длины дела`,
      body: 'Тело заметки: в описи видно только заголовок.',
    });
  }

  await addEntry(request, key, {
    type: 'question',
    title: 'Считать ли пропуск записи ошибкой контракта?',
    body: 'Нужен ответ, чтобы продолжить.',
    payload: { addressees: ['owner'], blocking: false },
  });

  return key;
}

test.describe('карточка задачи на широком экране', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('на первом экране видно сводку, вопросы и начало описи', async ({ page, request }) => {
    const key = await busyTask(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    // Всё три ради чего карточку открывают — на первом экране, без прокрутки.
    // Раньше опись лежала за пятью разделами задания, на 1300-м пикселе.
    await expect(page.getByRole('heading', { name: 'Последняя сводка' })).toBeInViewport();
    await expect(page.getByRole('heading', { name: 'Открытые вопросы' })).toBeInViewport();
    await expect(page.getByText(/^В деле \d+ запис/)).toBeInViewport();
    await expect(page.locator('tbody tr').first()).toBeInViewport();
  });

  test('длинное задание видно целиком и ничем не обрезано', async ({ page, request }) => {
    const long = (label: string) =>
      Array.from(
        { length: 12 },
        (_, line) => `${label}: строка ${line + 1} длинного раздела.`,
      ).join('\n\n');

    const key = await makeTask(request, 'Задача с длинными разделами', {
      goal: long('Цель'),
      context: long('Контекст'),
      constraints: long('Ограничения'),
      output: long('Выход'),
      checks: Array.from({ length: 10 }, (_, index) => `Обзорная проверка номер ${index + 1}`),
    });

    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    // Последняя проверка присутствует на странице: ни гармошек, ни «первых N строк».
    await expect(page.getByText('Обзорная проверка номер 10')).toBeVisible();
    await expect(page.getByText('Цель: строка 12 длинного раздела.')).toBeVisible();

    // Ни один блок не прячет содержимое переполнением.
    const overflowing = await page.evaluate(() =>
      Array.from(document.querySelectorAll('main section'))
        .filter((node) => node.scrollHeight > node.clientHeight + 1)
        .map((node) => node.getAttribute('aria-labelledby') ?? 'без имени'),
    );
    expect(overflowing).toEqual([]);
  });

  test('пустые блоки не съедают первый экран', async ({ page, request }) => {
    const key = await makeTask(request, 'Задача без сводки и без вопросов');
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    const summary = page.locator('section').filter({ hasText: 'Сводки ещё нет' }).first();
    const questions = page
      .locator('section')
      .filter({ hasText: 'Вопросов без ответа нет' })
      .first();

    // Честность пустого состояния на месте: тексты никуда не делись.
    await expect(summary).toBeVisible();
    await expect(questions).toBeVisible();

    const together =
      ((await summary.boundingBox())?.height ?? 0) + ((await questions.boundingBox())?.height ?? 0);
    expect(together).toBeLessThan((await viewportHeight(page)) / 4);
  });

  test('возможные переходы не кликабельны и не получают фокус', async ({ page, request }) => {
    const key = await makeTask(request, 'Задача ради проверки справки о переходах');
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    const transitions = page
      .locator('dd')
      .filter({ hasText: /^(open|in_progress|done)/ })
      .first();
    await expect(transitions).toBeVisible();
    // Переходы человек не делает (`CONCEPT.md`, 7): ни кнопки, ни ссылки, ни фокуса.
    await expect(transitions.locator('button, a, [tabindex]')).toHaveCount(0);
  });
});

test.describe('карточка задачи на узком экране', () => {
  test.use({ viewport: { width: 900, height: 800 } });

  test('всё складывается в одну колонку без горизонтальной прокрутки', async ({
    page,
    request,
  }) => {
    const key = await busyTask(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);

    await expect(page.getByRole('heading', { name: 'Последняя сводка' })).toBeVisible();

    // Одна колонка: блоки идут в порядке разметки, каждый следующий ниже предыдущего.
    const tops = await page.evaluate(() =>
      Array.from(document.querySelectorAll('main section')).map(
        (node) => node.getBoundingClientRect().top,
      ),
    );
    for (const [index, top] of tops.entries()) {
      if (index === 0) continue;
      expect(top).toBeGreaterThan(tops[index - 1] as number);
    }

    const scroll = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(scroll.width).toBe(scroll.client);
  });
});
