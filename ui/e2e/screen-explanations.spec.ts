import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

/**
 * Пояснения семи экранов на настоящем контуре, ширина 390 px (TRK-363): каждый экран
 * при включённых пояснениях показывает своё, и страница не прокручивается вбок.
 *
 * Владелец контура открывается со скрытыми пояснениями (`global-setup.ts`), как и в
 * `explanations.spec.ts`: сценарий включает их в начале и возвращает `hidden_all: true`
 * в конце — иначе соседним пишущим сценариям достался бы экран с лишним блоком. Поэтому
 * файл идёт в проекте «запись» (имя оканчивается на `explanations.spec.ts`, и сюда его
 * ведёт та же запись в `playwright.config.ts`).
 */

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

async function ownerAccountId(request: APIRequestContext): Promise<string> {
  const response = await request.get('/api/v1/bootstrap', { headers: auth() });
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { data: { account: { id: string } | null } };
  const accountId = body.data.account?.id;
  if (accountId === undefined) throw new Error('у владельца контура нет учётной записи');
  return accountId;
}

async function setHints(
  request: APIRequestContext,
  accountId: string,
  hints: { hidden_all?: boolean; hidden?: string[] },
): Promise<void> {
  const response = await request.patch(`/api/v1/accounts/${accountId}/onboarding`, {
    headers: auth(),
    data: { hints },
  });
  expect(response.ok()).toBe(true);
}

/** Адрес экрана и начало его пояснения — первое предложение текста задания, `ru`. */
const SCREENS: { name: string; path: string; text: string }[] = [
  {
    name: 'список задач',
    path: '/tasks?project=DEMO',
    text: 'Здесь все задачи, которые ведут агенты.',
  },
  {
    name: 'доска',
    path: '/tasks?project=DEMO&view=board',
    text: 'Те же задачи по шести столбцам статусов — одного проекта или всех, смотря что выбрано.',
  },
  {
    name: 'карточка задачи',
    path: '/tasks/DEMO-6',
    text: 'Это задание агенту и то, что по нему сделано',
  },
  { name: 'дело', path: '/tasks/DEMO-1/case', text: 'Дело — журнал задачи' },
  { name: 'проект', path: '/projects/DEMO', text: 'Проект отвечает на вопрос «про что задачи».' },
  { name: 'подключить агента', path: '/connect', text: 'Агент работает с Casefile через MCP' },
  { name: 'доступы', path: '/access', text: 'Здесь все токены установки' },
];

test('на каждом из семи экранов при 390 px видно своё пояснение и нет прокрутки вбок', async ({
  page,
  request,
}) => {
  const accountId = await ownerAccountId(request);

  try {
    await setHints(request, accountId, { hidden_all: false, hidden: [] });
    await silenceJournal(page);
    await page.setViewportSize({ width: 390, height: 844 });

    for (const { name, path, text } of SCREENS) {
      await page.goto(path);
      // Оболочку на 390 px не ждём: боковая панель там — закрытая шторка, и счётчик в ней не виден.
      const main = page.getByRole('main');
      await expect(main.getByText(text), name).toBeVisible();
      // Ровно одно пояснение: блок с двумя кнопками управления на экране один.
      await expect(main.getByRole('button', { name: 'Закрыть пояснение' }), name).toHaveCount(1);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${name}: ${path} на 390 px`).toBeLessThanOrEqual(0);
    }
  } finally {
    await setHints(request, accountId, { hidden_all: true, hidden: [] });
  }
});
