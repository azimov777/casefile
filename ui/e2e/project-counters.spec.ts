import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  fileLegacyQuestion,
  fontsReady,
  readAgentKey,
  readE2eToken,
  silenceJournal,
} from './contour';

/*
 * Счётчики задач в шапке экрана проекта и страницы области (TRK-619, TRK#46):
 * «В работе», «Открыто», «Ждут ответа», «Закрыты не целиком». Число каждого равно числу
 * в заголовке списка по его ссылке — на экране проекта и на странице области.
 *
 * Сценарий пишущий — заводит проект, область и задачи — и идёт в проекте «запись».
 * Ключ проекта несёт метку прогона: чужие задачи в его выдачу не попадают, и числа
 * известны наперёд.
 */

const token = readE2eToken();
const agent = readAgentKey();
const RUN = Date.now().toString(36).toUpperCase();
const KEY = `C${RUN}`.slice(0, 16);
const ADDRESS = `${KEY}/promo`;

type Counter = 'В работе' | 'Открыто' | 'Ждут ответа' | 'Закрыты не целиком';
const COUNTERS: readonly Counter[] = ['В работе', 'Открыто', 'Ждут ответа', 'Закрыты не целиком'];

async function api(
  request: APIRequestContext,
  method: 'post' | 'patch',
  path: string,
  data: Record<string, unknown>,
  as = token,
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${as}` },
    data,
  });
  expect([200, 201], await response.text()).toContain(response.status());
  return ((await response.json()) as { data: Record<string, unknown> }).data;
}

interface Seeded {
  /** Задача с открытым вопросом `blocking` и номер вопроса. */
  waiting: string;
  question: number;
  /** Задача, закрытая не целиком. */
  gaps: string;
}

let ready: Promise<Seeded> | null = null;

/**
 * Проект с областью `promo` и пятью задачами: в работе — две (одна в области),
 * открыта одна (в области), в черновиках одна с открытым вопросом `blocking`, закрыта
 * не целиком одна (в области).
 *
 * Ждущая задача лежит в `backlog`: ждёт ответа и она (`HELD_STATUSES`), а открытых
 * ей не нужны разделы.
 */
function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= seedOnce(request);
  return ready;
}

async function seedOnce(request: APIRequestContext): Promise<Seeded> {
  await api(request, 'post', '/api/v1/projects', { key: KEY, title: `Счётчики ${RUN}` });
  await api(request, 'post', `/api/v1/projects/${KEY}/areas`, {
    key: 'promo',
    title: `Продвижение ${RUN}`,
  });

  // Задача без области новой не бывает: «чужие» задачи лежат в другой области проекта.
  await api(request, 'post', `/api/v1/projects/${KEY}/areas`, {
    key: 'rest',
    title: `Остальное ${RUN}`,
  });
  const create = async (title: string, area: string) =>
    (
      await api(
        request,
        'post',
        '/api/v1/tasks',
        {
          project: KEY,
          title,
          description: 'Заведена сквозным тестом счётчиков (TRK-619).',
          goal: 'Число счётчика равно списку',
          context: 'Экран проекта',
          constraints: 'Ничего не считать на клиенте',
          output: 'Число в шапке',
          checks: ['Число равно заголовку списка'],
          assignee: 'demo_agent',
          area,
        },
        agent,
      )
    ).key as string;
  const move = async (key: string, targets: string[]) => {
    for (const to of targets) {
      await api(request, 'post', `/api/v1/tasks/${key}/transition`, { to }, agent);
    }
  };

  await move(await create('В работе, в области', ADDRESS), ['open', 'in_progress']);
  await move(await create('В работе, в другой области', `${KEY}/rest`), ['open', 'in_progress']);
  await move(await create('Открыта, в области', ADDRESS), ['open']);

  const waiting = await create('Ждёт ответа, в другой области', `${KEY}/rest`);
  // Прежний вопрос дела задачи от агента (TRK-671: новые — в обсуждениях): счётчик
  // «Ждёт ответа» считается из признака, который несёт и он.
  const asked = fileLegacyQuestion({
    key: waiting,
    title: 'Вопрос, на который ждут ответа',
    body: 'Вопрос сквозного теста счётчиков.',
    blocking: true,
    author: 'demo_agent',
  });

  const gaps = await create('Закрыта не целиком, в области', ADDRESS);
  await move(gaps, ['open', 'in_progress']);
  await api(
    request,
    'post',
    `/api/v1/tasks/${gaps}/close`,
    {
      summary: {
        done: 'Сделано; часть не проверена',
        remaining: 'nothing',
        blockers: 'nothing',
        next_step: 'no steps',
        unmeasured: 'Вид в Safari',
      },
      verdicts: [{ check_no: 1, outcome: 'unverifiable', evidence: 'Safari недоступен' }],
    },
    agent,
  );
  return { waiting, question: asked.no, gaps };
}

/** Число счётчика строки: хвост его текста. */
async function counterValue(page: Page, name: Counter): Promise<number> {
  const link = page.getByRole('list', { name: 'Число задач' }).getByRole('link', {
    name: new RegExp(`^${name}`),
  });
  await expect(link).toHaveText(new RegExp(`^${name}\\s*\\d+$`));
  return Number(((await link.textContent()) ?? '').replace(/\D+/g, ''));
}

/** Число в заголовке списка задач: последний знак его `h1`. */
async function listTotal(page: Page): Promise<number> {
  // Число — своим элементом: в самом заголовке могут быть цифры, но не в нём.
  const total = page.getByRole('heading', { level: 1 }).locator('[aria-hidden="true"]');
  await expect(total).toHaveText(/^\d+$/);
  return Number(await total.textContent());
}

async function checkCounters(page: Page, path: string, expected: number[]): Promise<void> {
  await silenceJournal(page);
  await page.goto(path);
  const counters = page.getByRole('list', { name: 'Число задач' });
  await expect(counters).toBeVisible();

  const values = [];
  for (const name of COUNTERS) values.push(await counterValue(page, name));
  expect(values, 'числа известны по заведённым задачам').toEqual(expected);

  for (const [index, name] of COUNTERS.entries()) {
    await page.goto(path);
    await counters.getByRole('link', { name: new RegExp(`^${name}`) }).click();
    await expect(page).toHaveURL(/\/tasks\?/);
    expect(await listTotal(page), `${name}: заголовок списка`).toBe(expected[index]);
  }
}

test('числа счётчиков проекта равны числам в заголовке списка по их ссылкам', async ({
  page,
  request,
}) => {
  await seed(request);
  await checkCounters(page, `/projects/${KEY}`, [2, 1, 1, 1]);
});

test('числа счётчиков области равны числам в заголовке списка по их ссылкам', async ({
  page,
  request,
}) => {
  await seed(request);
  await checkCounters(page, `/projects/${KEY}/areas/promo`, [1, 1, 0, 1]);
});

test('счётчики читают по четыре запроса с limit=1, не прокручивают вбок на телефоне и проходят axe', async ({
  page,
  request,
}) => {
  await seed(request);
  await silenceJournal(page);
  const calls: URL[] = [];
  page.on('request', (call) => {
    const url = new URL(call.url());
    if (url.pathname === '/api/v1/tasks') calls.push(url);
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${KEY}`);
  await fontsReady(page);
  const counters = page.getByRole('list', { name: 'Число задач' });
  await expect(counters.getByRole('link', { name: /^В работе\s*2$/ })).toBeVisible();

  expect(calls).toHaveLength(4);
  for (const url of calls) expect(url.searchParams.get('limit')).toBe('1');

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);

  const violations = (await new AxeBuilder({ page }).analyze()).violations;
  expect(violations.map((item) => item.id)).toEqual([]);
});

test('уборка: вопрос отвечен, предупреждение принято — «Входящие» остаются чистыми для соседей', async ({
  request,
}) => {
  const { waiting, question, gaps } = await seed(request);
  await api(request, 'post', `/api/v1/tasks/${waiting}/entries`, {
    type: 'answer',
    body: 'Ответ сквозного теста счётчиков.',
    payload: { question_no: question },
  });
  await api(request, 'post', `/api/v1/tasks/${gaps}/entries`, {
    type: 'acceptance',
    title: 'Принято сквозным тестом счётчиков',
  });
});
