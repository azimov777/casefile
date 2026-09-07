import { expect, test, type APIRequestContext } from '@playwright/test';
import { fontsReady, readE2eToken, side } from './contour';

const token = readE2eToken();

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/** Сколько ответов подшито в деле задачи — правда бэкенда, а не экрана. */
async function answersOf(request: APIRequestContext, key: string): Promise<number> {
  const response = await request.get(`/api/v1/tasks/${key}/entries?types=answer`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: unknown[] };
  return body.data.length;
}

/**
 * Единственный сквозной сценарий, который пишет в демо-установку: он отвечает на
 * вопрос, и после него вопрос закрыт навсегда. Поэтому он вынесен в свой файл и свой
 * проект Playwright, который зависит от читающих: тем нужен ещё открытый вопрос
 * (`playwright.config.ts`, проект «ответ»).
 */
test('ответ на вопрос из входящей закрывает его на всех экранах', async ({ page, request }) => {
  const before = await answersOf(request, 'DEMO-4');
  expect(before).toBe(0);

  const posts: string[] = [];
  page.on('request', (call) => {
    if (call.method() === 'POST' && call.url().includes('/entries')) {
      posts.push(call.headers()['idempotency-key'] ?? '');
    }
  });

  await page.goto('/questions');

  // Счётчик в панели — то же число, что показывает `bootstrap`. Пишущие сценарии идут
  // по одному и убирают за собой, поэтому здесь открыт ровно вопрос демо.
  await expect(side(page).getByText('Открытых вопросов: 1')).toBeVisible();

  const question = page.getByRole('article').filter({ hasText: 'DEMO-4#4' });
  await expect(question.getByText('блокирующий')).toBeVisible();

  await question.getByRole('button', { name: 'Ответить' }).click();
  await page
    .getByLabel(/^Ответ$/)
    .fill('Храним вечно: записи дела неизменяемы, срок хранения не вводим.');
  await page.getByRole('button', { name: 'Ответить' }).click();

  // Ответ подшит, и это сказано словами с номером записи: раньше здесь исчезал весь
  // блок, а единственным признаком, что что-то произошло, был счётчик в шапке.
  const receipt = page.getByRole('region', { name: 'Ответ на DEMO-4#4 подшит' });
  await expect(receipt).toBeVisible();
  const entry = receipt.getByRole('link', { name: /^DEMO-4#\d+$/ });
  const href = await entry.getAttribute('href');
  expect(href).toMatch(/^\/tasks\/DEMO-4\?entry=\d+$/);

  // Вопрос при этом никуда не делся, а счётчик всё равно перечитан у бэкенда.
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#4' })).toHaveCount(1);
  // Ноль называется словами, а не числом: «Открытых вопросов: 0» человек читает
  // как счётчик, который надо расшифровать, а «вопросов нет» — как ответ.
  await expect(side(page).getByText('Открытых вопросов нет')).toBeVisible();

  // Подтверждение закрывает человек, а не таймер, — и только после этого вопрос
  // уходит с экрана.
  await receipt.getByRole('button', { name: 'Закрыть' }).click();
  await expect(page.getByRole('article').filter({ hasText: 'DEMO-4#4' })).toHaveCount(0);

  // Номер из подтверждения ведёт к самому ответу в ленте дела. Отдельным переходом,
  // а не «туда и обратно»: подтверждение живёт в состоянии страницы, и уход с неё —
  // это решение человека, после которого показывать его больше незачем.
  const no = /entry=(\d+)/.exec(href ?? '')?.[1] ?? '';
  await page.goto(href ?? '');
  // Номер в описи рисуется числом, без решётки: решётка живёт в ссылке `DEMO-4#9`,
  // а строка описи называет запись заголовком столбца.
  await expect(
    page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: no }) }),
  ).toBeVisible();
  await expect(
    page.getByText('Храним вечно: записи дела неизменяемы, срок хранения не вводим.').first(),
  ).toBeVisible();

  // Запрос ушёл с ключом повтора, и ответ в деле ровно один.
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(await answersOf(request, 'DEMO-4')).toBe(1);

  // В карточке блок открытых вопросов пуст, а в описи появилась запись `answer`.
  await page.goto('/tasks/DEMO-4');
  await expect(page.getByText('Вопросов без ответа нет.')).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'answer' })).toHaveCount(1);
});

/**
 * Заводит вопрос владельцу и возвращает его номер вместе со способом убрать за собой.
 *
 * Свой вопрос, а не демонстрационный: в демо открыт ровно один вопрос владельцу, его
 * забирает главный сценарий выше, и занимать его замерами вёрстки значит связать два
 * сценария через данные.
 */
async function askOwner(
  request: APIRequestContext,
  key: string,
  title: string,
  body: string,
): Promise<{ no: number; cleanup: () => Promise<void> }> {
  const asked = await request.post(`/api/v1/tasks/${key}/entries`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { type: 'question', title, body, payload: { addressees: ['owner'], blocking: false } },
  });
  expect(asked.status()).toBe(201);
  const no = ((await asked.json()) as { data: { no: number } }).data.no;

  return {
    no,
    cleanup: async () => {
      const closed = await request.post(`/api/v1/tasks/${key}/entries`, {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          type: 'answer',
          body: 'Закрыт сквозным тестом, чтобы входящая осталась какой была.',
          payload: { question_no: no },
        },
      });
      expect(closed.status()).toBe(201);
    },
  };
}

/**
 * Кнопка «Ответить» обязана стоять на месте в любом состоянии формы. Раньше её
 * опускало появление упрёка (на 24 px) и раскрытие предпросмотра (ещё на 140 px) —
 * то есть промахнуться мимо неё человек мог ровно в тот момент, когда собирался
 * нажать второй раз.
 */
test('кнопка «Ответить» не уезжает из-под курсора ни в одном состоянии формы', async ({
  page,
  request,
}) => {
  const question = await askOwner(
    request,
    'DEMO-3',
    'Вопрос для замера неподвижности кнопки',
    'Тело вопроса, на состав которого замер не опирается.',
  );

  // Номер вопроса в адресе: форма на карточке раскрывается сразу, когда адрес
  // называет именно этот вопрос, — так сюда приводит уведомление и входящая.
  await page.goto(`/tasks/DEMO-3?entry=${question.no}`);
  // Карточка догружается блоками, и последний из них — опись дела. Пока её нет,
  // замер снимается с ещё не сложившейся страницы, и «кнопка уехала» означало бы
  // только «страница дорисовалась».
  await expect(page.getByText(/Записей в деле:/)).toBeVisible();

  const form = page.getByRole('form', { name: `Ответ на DEMO-3#${question.no}` });
  const submit = form.getByRole('button', { name: 'Ответить' });
  const field = form.getByLabel(/^Ответ$/);

  async function top(): Promise<number> {
    // Шрифт обязан прийти до первого замера: подстановка Fira двигает всё, что ниже.
    await fontsReady(page);
    const box = await submit.boundingBox();
    if (box === null) return -1;
    /*
     * Координата в документе, а не в окне: проверяется, что кнопку не двигает
     * содержимое над ней, а прокрутка страницы к этому отношения не имеет. На
     * коротком документе она к тому же непостоянна — браузер откатывает её сам,
     * когда страница дорисовывается и становится короче окна.
     */
    return box.y + (await page.evaluate(() => window.scrollY));
  }

  try {
    // Кнопку надо привести в вид до первого замера: `click()` сам прокручивает
    // элемент в вид, и снимать «до» с кнопки ниже сгиба значило бы сравнивать
    // разные состояния страницы.
    await submit.scrollIntoViewIfNeeded();

    const empty = await top();
    expect(empty).toBeGreaterThan(0);

    // Состояние «с ошибкой»: пустая отправка отклонена проверкой формы.
    await submit.click();
    await expect(form.getByText(/Пустой ответ отправить нельзя/)).toBeVisible();
    const withProblem = await top();

    // Состояние «с текстом»: упрёк гаснет первым же символом.
    await field.fill('Ответ в одну строку.');
    await expect(form.getByText(/Пустой ответ отправить нельзя/)).toBeHidden();
    const withText = await top();

    // Состояние «с раскрытым предпросмотром».
    await form.getByRole('button', { name: 'Предпросмотр' }).click();
    await expect(form.getByText('Как это увидит агент')).toBeVisible();
    const withPreview = await top();

    expect(withProblem).toBe(empty);
    expect(withText).toBe(empty);
    expect(withPreview).toBe(empty);
  } finally {
    // Уборка обязана случиться и при падении: оставленный открытым вопрос ломает
    // соседние сценарии, и разбирать пришлось бы уже два падения вместо одного.
    await question.cleanup();
  }
});

/**
 * Ответ не должен схлопывать страницу под руками. Замер идёт на закреплённых данных —
 * вопрос в три абзаца и ответ в десять строк, — потому что беда была именно на
 * длинном содержимом: блок терял около 500 px.
 */
test('ответ не схлопывает блок открытых вопросов и ничего не обрезает', async ({
  page,
  request,
}) => {
  const question = await askOwner(
    request,
    'DEMO-3',
    'Длинный вопрос для замера высоты',
    [
      'Первый абзац вопроса: он длинный, потому что беда была именно на длинном.',
      'Второй абзац вопроса: здесь агент объясняет, что именно ему мешает.',
      'Третий абзац вопроса: и чего он ждёт от человека, чтобы продолжить.',
    ].join('\n\n'),
  );

  const answer = Array.from({ length: 10 }, (_, line) => `Строка ответа номер ${line + 1}.`).join(
    '\n\n',
  );

  await page.goto(`/tasks/DEMO-3?entry=${question.no}`);
  const block = page
    .locator('section')
    .filter({ has: page.getByText('Открытые вопросы') })
    .first();
  await expect(block.getByText('Длинный вопрос для замера высоты')).toBeVisible();

  await fontsReady(page);
  const before = (await block.boundingBox())?.height ?? 0;
  expect(before).toBeGreaterThan(0);

  const form = page.getByRole('form', { name: `Ответ на DEMO-3#${question.no}` });
  await form.getByLabel(/^Ответ$/).fill(answer);
  await form.getByRole('button', { name: 'Ответить' }).click();

  const receipt = page.getByRole('region', { name: `Ответ на DEMO-3#${question.no} подшит` });
  await expect(receipt).toBeVisible();

  const after = (await block.boundingBox())?.height ?? 0;
  expect(Math.abs(after - before)).toBeLessThanOrEqual(80);

  // Неподвижность не куплена обрезанием: видны и последний абзац вопроса, и обе
  // крайние строки ответа — длинный ответ прокручивается внутри подтверждения.
  await expect(block.getByText('Третий абзац вопроса:', { exact: false })).toBeVisible();
  await expect(receipt.getByText('Строка ответа номер 1.')).toBeVisible();
  await expect(receipt.getByText('Строка ответа номер 10.')).toBeVisible();
});
